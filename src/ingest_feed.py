"""Token-free fallback ingestion via Product Hunt's public Atom feed + product pages.

No PRODUCTHUNT_TOKEN needed. Use this when you don't have a developer token
yet; use src/ingest.py (needs a token) once you do, especially for the
backtest (see the hard limitation below).

WHAT THIS CAN GET, without any auth, using only plain HTTP GET requests to
pages Product Hunt serves publicly (the Atom feed is explicitly published
for third-party consumption, and product pages returned normal 200s across
repeated polite requests when tested):
  - title, tagline, product page URL, published date (from the Atom feed)
  - real website domain and GitHub link, if present (embedded directly in
    each product page's static HTML, already resolved past any tracking
    redirect)
  - topics, and full maker list (profile-link count) (also static HTML)

WHAT THIS CANNOT GET, and why:
  - votes_count / comments_count: Product Hunt only renders these client-side
    via JS after the page loads. Rendering the page with Playwright to read
    them triggers Product Hunt's Cloudflare bot challenge ("Just a moment...").
    This module does not attempt to defeat that challenge -- that would be
    bot-detection evasion against a platform actively signaling it doesn't
    want automated rendering, which is out of scope for this project no
    matter which data source is involved. Traction (0-30 of the composite)
    and the votes-based half of Momentum (0-20) are structurally zero in
    this mode -- every record ties there. The composite in feed-fallback
    mode is really a Team+Market/Product+recency scorer, not the full
    traction-aware rubric the project set out to build.
  - a historical window: the public feed exposes only the ~50 most recently
    touched launches with no date-range parameter. There's no responsible
    tokenless way to pull a clean 6-12-month-old population from it, so the
    backtest (src/backtest.py) cannot run against this source. Get a token
    (2 minutes, free, personal use, no app review -- producthunt.com ->
    account settings -> Applications) when you're ready to validate the
    rubric; there's no way around that step.

Usage:
    python -m src.ingest_feed --out data/raw/launches_feed.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

from src.ingest import AI_KEYWORDS

FEED_URL = "https://www.producthunt.com/feed"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

HEADERS = {"User-Agent": "ai-scout-pipeline/1.0 (personal research project; plain HTTP, no automation)"}

TOPIC_LINK_RE = re.compile(r'href="/topics/([a-z0-9-]+)"')
MAKER_LINK_RE = re.compile(r'href="(/@[a-zA-Z0-9_-]+)"')
OUTBOUND_LINK_RE = re.compile(r'href="(https?://[^"]+)"')
GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")

SKIP_DOMAINS = {
    "producthunt.com",
    "www.producthunt.com",
    "ph-files.imgix.net",
    "ph-static.imgix.net",
    "googletagmanager.com",
    "www.googletagmanager.com",
    "producthunt.app.link",
    "linkedin.com",
    "www.linkedin.com",
    "x.com",
    "twitter.com",
    "lu.ma",
}


def fetch_feed_entries() -> list[dict]:
    resp = requests.get(FEED_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)
    entries = []
    for entry in root.findall("a:entry", ATOM_NS):
        entry_id = entry.findtext("a:id", default="", namespaces=ATOM_NS)
        title = entry.findtext("a:title", default="", namespaces=ATOM_NS)
        published = entry.findtext("a:published", default="", namespaces=ATOM_NS)
        link_el = entry.find("a:link", ATOM_NS)
        product_url = link_el.get("href") if link_el is not None else None
        content = entry.findtext("a:content", default="", namespaces=ATOM_NS)
        author = entry.findtext("a:author/a:name", default="", namespaces=ATOM_NS)

        tagline = re.sub(r"<[^>]+>", "", content).strip().split("\n")[0].strip() if content else ""
        entries.append(
            {
                "ph_id": entry_id.rsplit("/", 1)[-1] if entry_id else None,
                "name": title,
                "tagline": tagline,
                "ph_url": product_url,
                "created_at": published,
                "feed_author": author,
            }
        )
    return entries


def scrape_product_page(product_url: str, session: requests.Session) -> dict:
    resp = session.get(product_url, timeout=15)
    resp.raise_for_status()
    html = resp.text

    topics = sorted(set(TOPIC_LINK_RE.findall(html)))
    maker_handles = sorted(set(MAKER_LINK_RE.findall(html)))

    website = None
    github_repo = None
    for match in OUTBOUND_LINK_RE.finditer(html):
        url = match.group(1)
        domain = urlparse(url).netloc
        if domain in SKIP_DOMAINS or "imgix.net" in domain:
            continue
        gh = GITHUB_RE.search(url)
        if gh and not github_repo:
            github_repo = gh.group(1)
            continue
        if not website:
            # strip Product Hunt's ?ref=producthunt tracking param
            website = url.split("?ref=producthunt")[0].rstrip("?")
            website = urlparse(website).netloc

    return {
        "topics": topics,
        "domain": website,
        "github_repo_hint": github_repo,
        "makers": [{"id": None, "username": h.lstrip("/@"), "prior_post_count": None} for h in maker_handles],
    }


def is_ai_related_feed(entry: dict) -> bool:
    if "artificial-intelligence" in entry.get("topics", []):
        return True
    text = f"{entry.get('tagline', '')} {entry.get('name', '')}"
    return bool(AI_KEYWORDS.search(text))


def ingest_feed(delay_seconds: float = 1.0) -> list[dict]:
    entries = fetch_feed_entries()
    session = requests.Session()
    session.headers.update(HEADERS)

    records = []
    for entry in entries:
        if not entry.get("ph_url"):
            continue
        try:
            page_data = scrape_product_page(entry["ph_url"], session)
        except requests.RequestException as exc:
            entry["scrape_error"] = str(exc)
            page_data = {"topics": [], "domain": None, "github_repo_hint": None, "makers": []}
        entry.update(page_data)
        if not is_ai_related_feed(entry):
            time.sleep(delay_seconds)
            continue

        entry["votes_count"] = None
        entry["comments_count"] = None
        entry["website_raw"] = entry.get("ph_url")
        entry["slug"] = entry["ph_url"].rstrip("/").rsplit("/", 1)[-1] if entry.get("ph_url") else None
        entry["data_source"] = "feed_fallback"
        entry["votes_unavailable"] = True
        records.append(entry)
        time.sleep(delay_seconds)

    return records


def main():
    parser = argparse.ArgumentParser(description="Token-free fallback ingestion via the public PH feed.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between product-page requests (politeness)")
    args = parser.parse_args()

    records = ingest_feed(delay_seconds=args.delay)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Wrote {len(records)} AI-topic launches (feed-fallback mode) to {out_path}")
    print("NOTE: votes_count/comments_count are unavailable in this mode -- Traction and")
    print("the votes-based half of Momentum score as 0 for every record. See module docstring.")


if __name__ == "__main__":
    main()
