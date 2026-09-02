"""Ranked CSV/JSON output (task rec:01M1H5KP00HTRMNSEJ4YG2BEFH).

Usage:
    python -m src.rank_output --in data/scored/launches.jsonl --out-prefix data/output/ranked
Produces data/output/ranked.csv and data/output/ranked.json, sorted by
composite_score descending, with all four sub-scores visible per row.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

COLUMNS = [
    "ph_id",
    "name",
    "domain",
    "ph_url",
    "composite_score",
    "traction_score",
    "team_score",
    "market_product_score",
    "momentum_score",
    "votes_count",
    "comments_count",
    "created_at",
    "tagline",
]


def load_scored(in_path: Path) -> list[dict]:
    return [json.loads(line) for line in in_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rank(records: list[dict]) -> list[dict]:
    return sorted(records, key=lambda r: r.get("composite_score", 0), reverse=True)


def write_outputs(records: list[dict], out_prefix: Path) -> None:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    ranked = rank(records)

    json_path = out_prefix.with_suffix(".json")
    json_path.write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = out_prefix.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in ranked:
            writer.writerow(row)

    print(f"Wrote {len(ranked)} ranked records to {csv_path} and {json_path}")


def main():
    parser = argparse.ArgumentParser(description="Produce ranked CSV/JSON output from scored launches.")
    parser.add_argument("--in", dest="in_path", required=True)
    parser.add_argument("--out-prefix", dest="out_prefix", required=True)
    args = parser.parse_args()
    records = load_scored(Path(args.in_path))
    write_outputs(records, Path(args.out_prefix))


if __name__ == "__main__":
    main()
