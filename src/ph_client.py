"""Minimal client for the Product Hunt v2 GraphQL API.

Get a developer token: log into producthunt.com -> account settings ->
Applications -> create an application -> copy the "Developer Token".
Set it as PRODUCTHUNT_TOKEN (env var or .env file).
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests

PH_API_URL = "https://api.producthunt.com/v2/api/graphql"


class ProductHuntError(RuntimeError):
    pass


POSTS_QUERY = """
query Posts($topic: String, $after: String, $postedAfter: DateTime, $postedBefore: DateTime) {
  posts(first: 50, after: $after, topic: $topic, postedAfter: $postedAfter, postedBefore: $postedBefore, order: RANKING) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        tagline
        description
        slug
        url
        website
        votesCount
        commentsCount
        createdAt
        featuredAt
        topics(first: 10) { edges { node { name slug } } }
        makers { id name username headline twitterUsername }
      }
    }
  }
}
"""

USER_POST_COUNT_QUERY = """
query UserPostCount($id: ID!) {
  user(id: $id) {
    id
    madePosts(first: 1) {
      totalCount
    }
  }
}
"""


class ProductHuntClient:
    def __init__(self, token: Optional[str] = None, session: Optional[requests.Session] = None):
        self.token = token or os.environ.get("PRODUCTHUNT_TOKEN")
        if not self.token:
            raise ProductHuntError(
                "PRODUCTHUNT_TOKEN not set. Create a developer token at "
                "https://www.producthunt.com/v2/oauth/applications and set it "
                "as an environment variable or in a .env file (see .env.example)."
            )
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "ai-scout-pipeline/1.0 (personal research project)",
            }
        )

    def query(self, query: str, variables: Optional[dict] = None, max_retries: int = 5) -> dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        backoff = 2
        last_error: Optional[Exception] = None
        for _ in range(max_retries):
            try:
                resp = self.session.post(PH_API_URL, json=payload, timeout=30)
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", backoff))
                time.sleep(wait)
                backoff *= 2
                continue
            if resp.status_code >= 500:
                time.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
            body = resp.json()
            if "errors" in body:
                raise ProductHuntError(str(body["errors"]))
            remaining = resp.headers.get("X-Rate-Limit-Remaining")
            if remaining is not None and int(remaining) < 5:
                time.sleep(2)
            return body["data"]
        raise ProductHuntError(f"Exceeded retries against Product Hunt API: {last_error}")

    def iter_posts(
        self,
        topic: Optional[str] = None,
        posted_after: Optional[str] = None,
        posted_before: Optional[str] = None,
    ):
        """Yield raw post nodes for a topic + date window, following pagination."""
        after = None
        while True:
            data = self.query(
                POSTS_QUERY,
                {
                    "topic": topic,
                    "after": after,
                    "postedAfter": posted_after,
                    "postedBefore": posted_before,
                },
            )
            connection = data["posts"]
            for edge in connection["edges"]:
                yield edge["node"]
            page_info = connection["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            after = page_info["endCursor"]

    def user_post_count(self, user_id: str) -> Optional[int]:
        """Best-effort continuous proxy for repeat-founder signal. Returns None on failure."""
        try:
            data = self.query(USER_POST_COUNT_QUERY, {"id": user_id})
            return data["user"]["madePosts"]["totalCount"]
        except Exception:
            return None
