"""Pull AI-topic Product Hunt launches for a date range into a clean JSONL file.

Usage:
    python -m src.ingest --after 2026-06-01 --before 2026-09-01 --out data/raw/launches.jsonl

Strategy (per task rec:01M1H5HE99GHRQCJ21ZZAK00D0):
- Query the artificial-intelligence and developer-tools topics for the window.
- Dedup by post id across topics.
- Flag is_ai_confirmed: topic == artificial-intelligence, OR AI keyword match on
  tagline/description. developer-tools launches that don't clear the keyword bar
  are dropped (that topic alone is too broad / not AI-specific).
- Resolve the website field through any tracking redirect to the real domain.
- Best-effort populate each maker's prior-post count (continuous repeat-founder
  proxy) — never blocks ingestion if it fails.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from src.ph_client import ProductHuntClient, ProductHuntError

TOPICS = ["artificial-intelligence", "developer-tools"]

AI_KEYWORDS = re.compile(
    r"\b(ai|artificial intelligence|machine learning|ml|llm|gpt|genai|"
    r"generative ai|neural network|nlp|chatbot|copilot|ai agent|deep learning)\b",
    re.IGNORECASE,
)


def resolve_domain(url: str, timeout: float = 8.0) -> str | None:
    if not url:
        return None
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout)
        if resp.status_code >= 400 or not resp.url:
            resp = requests.get(url, allow_redirects=True, timeout=timeout, stream=True)
        final_url = resp.url
    except requests.RequestException:
        return None
    netloc = urlparse(final_url).netloc
    return netloc or None


def is_ai_related(node: dict) -> bool:
    topic_slugs = {edge["node"]["slug"] for edge in node.get("topics", {}).get("edges", [])}
    if "artificial-intelligence" in topic_slugs:
        return True
    text = f"{node.get('tagline', '')} {node.get('description', '')}"
    return bool(AI_KEYWORDS.search(text))


def normalize(node: dict, client: ProductHuntClient, fetch_maker_history: bool) -> dict:
    domain = resolve_domain(node.get("website") or node.get("url"))
    makers = node.get("makers") or []
    maker_records = []
    for m in makers:
        prior_posts = None
        if fetch_maker_history and m.get("id"):
            prior_posts = client.user_post_count(m["id"])
        maker_records.append(
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "username": m.get("username"),
                "headline": m.get("headline"),
                "twitter": m.get("twitterUsername"),
                "prior_post_count": prior_posts,
            }
        )
    return {
        "ph_id": node["id"],
        "name": node["name"],
        "tagline": node.get("tagline"),
        "description": node.get("description"),
        "slug": node.get("slug"),
        "ph_url": node.get("url"),
        "website_raw": node.get("website"),
        "domain": domain,
        "votes_count": node.get("votesCount", 0),
        "comments_count": node.get("commentsCount", 0),
        "created_at": node.get("createdAt"),
        "featured_at": node.get("featuredAt"),
        "topics": [edge["node"]["slug"] for edge in node.get("topics", {}).get("edges", [])],
        "makers": maker_records,
    }


def ingest(posted_after: str, posted_before: str, fetch_maker_history: bool = True) -> list[dict]:
    load_dotenv()
    client = ProductHuntClient()
    seen: dict[str, dict] = {}
    for topic in TOPICS:
        for node in client.iter_posts(topic=topic, posted_after=posted_after, posted_before=posted_before):
            if node["id"] in seen:
                continue
            if not is_ai_related(node):
                continue
            seen[node["id"]] = normalize(node, client, fetch_maker_history)
    return list(seen.values())


def main():
    parser = argparse.ArgumentParser(description="Ingest AI-topic Product Hunt launches.")
    parser.add_argument("--after", required=True, help="ISO date, e.g. 2026-06-01")
    parser.add_argument("--before", required=True, help="ISO date, e.g. 2026-09-01")
    parser.add_argument("--out", required=True, help="Output JSONL path")
    parser.add_argument(
        "--no-maker-history",
        action="store_true",
        help="Skip per-maker prior-post-count lookups (faster, avoids extra API calls)",
    )
    args = parser.parse_args()

    try:
        records = ingest(
            f"{args.after}T00:00:00Z",
            f"{args.before}T00:00:00Z",
            fetch_maker_history=not args.no_maker_history,
        )
    except ProductHuntError as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    no_domain = sum(1 for r in records if not r["domain"])
    print(f"Wrote {len(records)} AI-topic launches to {out_path}")
    if no_domain:
        print(f"  {no_domain} records had no resolvable domain (logged, not dropped)")


if __name__ == "__main__":
    main()
