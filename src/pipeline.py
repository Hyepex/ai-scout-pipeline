"""End-to-end orchestrator: ingest -> enrich -> score -> ranked output.

Usage:
    python -m src.pipeline --after 2026-06-01 --before 2026-09-01 --run-id weekly
Writes to data/raw/<run-id>.jsonl, data/enriched/<run-id>.jsonl,
data/scored/<run-id>.jsonl, and data/output/<run-id>.{csv,json}.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.enrich import enrich_file
from src.ingest import ingest
from src.rank_output import write_outputs
from src.scoring import score_batch


def run(after: str, before: str, run_id: str) -> Path:
    raw_path = Path(f"data/raw/{run_id}.jsonl")
    enriched_path = Path(f"data/enriched/{run_id}.jsonl")
    scored_path = Path(f"data/scored/{run_id}.jsonl")
    out_prefix = Path(f"data/output/{run_id}")

    print("[1/4] Ingesting from Product Hunt...")
    records = ingest(f"{after}T00:00:00Z", f"{before}T00:00:00Z")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    print(f"  {len(records)} AI-topic launches")

    print("[2/4] Enriching websites...")
    enrich_file(raw_path, enriched_path)

    print("[3/4] Scoring...")
    enriched = [json.loads(l) for l in enriched_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    scored = score_batch(enriched)
    scored_path.parent.mkdir(parents=True, exist_ok=True)
    scored_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in scored), encoding="utf-8")

    print("[4/4] Writing ranked output...")
    write_outputs(scored, out_prefix)

    return out_prefix


def main():
    parser = argparse.ArgumentParser(description="Run the full AI scout pipeline end to end.")
    parser.add_argument("--after", required=True, help="ISO date, e.g. 2026-06-01")
    parser.add_argument("--before", required=True, help="ISO date, e.g. 2026-09-01")
    parser.add_argument("--run-id", default="latest")
    args = parser.parse_args()
    run(args.after, args.before, args.run_id)


if __name__ == "__main__":
    main()
