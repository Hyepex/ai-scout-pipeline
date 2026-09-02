"""Website enrichment via Playwright (task rec:01M1H5HS38AVJ8JCHWZFNE1R56).

For each resolved domain from ingest.py, visit the homepage and extract:
  - about/team page presence
  - pricing page presence
  - docs/demo presence
  - social links (X/Twitter, LinkedIn company page)
  - GitHub link, and star count if found (via the public GitHub API)

Failures are logged with an `enrichment_error` field and the record is kept
(not dropped), per the task's acceptance criteria.

Usage:
    python -m src.enrich --in data/raw/launches.jsonl --out data/enriched/launches.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ABOUT_RE = re.compile(r"\b(about|team|company)\b", re.IGNORECASE)
PRICING_RE = re.compile(r"\bpricing|plans\b", re.IGNORECASE)
DOCS_RE = re.compile(r"\bdocs|documentation|demo\b", re.IGNORECASE)

GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")
LINKEDIN_RE = re.compile(r"linkedin\.com/company/[A-Za-z0-9_.\-]+")
TWITTER_RE = re.compile(r"(?:twitter|x)\.com/[A-Za-z0-9_]+")


def classify_links(links: list[str]) -> dict:
    has_about = any(ABOUT_RE.search(l) for l in links)
    has_pricing = any(PRICING_RE.search(l) for l in links)
    has_docs = any(DOCS_RE.search(l) for l in links)
    github_match = next((GITHUB_RE.search(l) for l in links if GITHUB_RE.search(l)), None)
    linkedin_match = next((LINKEDIN_RE.search(l) for l in links if LINKEDIN_RE.search(l)), None)
    twitter_match = next((TWITTER_RE.search(l) for l in links if TWITTER_RE.search(l)), None)
    return {
        "has_about_page": has_about,
        "has_pricing_page": has_pricing,
        "has_docs_or_demo": has_docs,
        "github_repo": github_match.group(1) if github_match else None,
        "linkedin_company_url": ("https://" + linkedin_match.group(0)) if linkedin_match else None,
        "twitter_url": ("https://" + twitter_match.group(0)) if twitter_match else None,
    }


def github_star_count(repo_slug: str | None, session: requests.Session) -> int | None:
    if not repo_slug:
        return None
    try:
        resp = session.get(f"https://api.github.com/repos/{repo_slug}", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("stargazers_count")
    except requests.RequestException:
        pass
    return None


def enrich_domain(page, domain: str) -> dict:
    url = f"https://{domain}"
    try:
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
    except PWTimeout:
        try:
            page.goto(f"http://{domain}", timeout=15000, wait_until="domcontentloaded")
        except Exception as exc:
            return {"enrichment_error": f"navigation failed: {exc}"}
    except Exception as exc:
        return {"enrichment_error": f"navigation failed: {exc}"}

    try:
        links = page.eval_on_selector_all("a", "els => els.map(e => e.href).filter(Boolean)")
    except Exception as exc:
        return {"enrichment_error": f"link extraction failed: {exc}"}

    result = classify_links(links)
    result["enrichment_error"] = None
    return result


def enrich_file(in_path: Path, out_path: Path) -> None:
    records = [json.loads(line) for line in in_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    gh_session = requests.Session()
    gh_session.headers.update({"User-Agent": "ai-scout-pipeline/1.0"})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok, failed = 0, 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        with out_path.open("w", encoding="utf-8") as out_f:
            for rec in records:
                domain = rec.get("domain")
                if not domain:
                    rec["enrichment"] = {"enrichment_error": "no domain resolved during ingestion"}
                    failed += 1
                    out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    continue
                enrichment = enrich_domain(page, domain)
                if enrichment.get("github_repo"):
                    enrichment["github_stars"] = github_star_count(enrichment["github_repo"], gh_session)
                    time.sleep(1)  # be polite to unauthenticated GitHub API rate limit
                else:
                    enrichment["github_stars"] = None
                rec["enrichment"] = enrichment
                if enrichment.get("enrichment_error"):
                    failed += 1
                else:
                    ok += 1
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        browser.close()

    print(f"Enriched {ok} domains, {failed} failed (kept with enrichment_error set) -> {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Enrich ingested launches with website signals.")
    parser.add_argument("--in", dest="in_path", required=True)
    parser.add_argument("--out", dest="out_path", required=True)
    args = parser.parse_args()
    enrich_file(Path(args.in_path), Path(args.out_path))


if __name__ == "__main__":
    main()
