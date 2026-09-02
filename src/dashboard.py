"""Generate the Scout Deck HTML dashboard from a scored/ranked pipeline run.

Reads data/output/<run-id>.json (written by src/rank_output.py) and
data/raw/<run-id>.jsonl (to compute the funnel's "scanned" count, when
available), and produces a single self-contained HTML file you can open
directly in a browser or publish as a Claude Artifact.

Usage:
    python -m src.dashboard --run-id weekly --out dashboard.html
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "dashboard_assets" / "template.html"


def build_embed_records(scored: list[dict]) -> list[dict]:
    records = sorted(scored, key=lambda r: r["composite_score"], reverse=True)
    trimmed = []
    for r in records:
        e = r.get("enrichment") or {}
        trimmed.append(
            {
                "id": r.get("ph_id"),
                "name": r.get("name"),
                "tagline": r.get("tagline"),
                "domain": r.get("domain"),
                "url": r.get("ph_url"),
                "created": r.get("created_at"),
                "topics": r.get("topics", []),
                "makers": [m.get("username") or m.get("name") for m in (r.get("makers") or []) if m.get("username") or m.get("name")],
                "gh": e.get("github_repo"),
                "stars": e.get("github_stars"),
                "li": bool(e.get("linkedin_company_url")),
                "tw": bool(e.get("twitter_url")),
                "pricing": bool(e.get("has_pricing_page")),
                "docs": bool(e.get("has_docs_or_demo")),
                "sub": r.get("sub_scores", {}),
                "traction": r.get("traction_score", 0),
                "team": r.get("team_score", 0),
                "market": r.get("market_product_score", 0),
                "momentum": r.get("momentum_score", 0),
                "composite": r.get("composite_score", 0),
            }
        )
    return trimmed


def generate(run_id: str, out_path: Path) -> None:
    scored_path = Path(f"data/output/{run_id}.json")
    if not scored_path.exists():
        raise SystemExit(f"{scored_path} not found. Run src.pipeline or src.rank_output for run-id '{run_id}' first.")
    scored = json.loads(scored_path.read_text(encoding="utf-8"))

    raw_path = Path(f"data/raw/{run_id}.jsonl")
    scanned = None
    if raw_path.exists():
        scanned = len(raw_path.read_text(encoding="utf-8").splitlines())

    enriched_path = Path(f"data/enriched/{run_id}.jsonl")
    enrich_failed = 0
    enriched_count = len(scored)
    if enriched_path.exists():
        lines = [json.loads(l) for l in enriched_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        enriched_count = len(lines)
        enrich_failed = sum(1 for l in lines if (l.get("enrichment") or {}).get("enrichment_error"))

    embed = build_embed_records(scored)
    meta = {
        "scanned": scanned if scanned is not None else len(scored),
        "aiConfirmed": len(scored),
        "enriched": enriched_count,
        "enrichFailed": enrich_failed,
        "runId": run_id,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = html.replace(
        "const DATA = /*__RUN_DATA__*/;\nconst META = /*__RUN_META__*/;",
        f"const DATA = {json.dumps(embed, ensure_ascii=False, separators=(',', ':'))};\n"
        f"const META = {json.dumps(meta)};",
    )
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(scored)} companies, run-id '{run_id}')")


def main():
    parser = argparse.ArgumentParser(description="Generate the Scout Deck HTML dashboard.")
    parser.add_argument("--run-id", default="latest")
    parser.add_argument("--out", default="dashboard.html")
    args = parser.parse_args()
    generate(args.run_id, Path(args.out))


if __name__ == "__main__":
    main()
