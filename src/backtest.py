"""Historical backtest of the scoring rubric (task rec:01M1H5K1YTXP74T6D5RV95TG0D).

Runs ingest -> enrich -> score against a 6-12-month-old Product Hunt window,
then builds two review samples:
  - top-decile: the highest-scored launches from that window
  - random: a random sample of the same size from the remaining pool

Per kb:lesson:campaign_small_sample_anomaly_rate_overstates_before_full_population_check,
each sample uses n>=50 where the launch pool allows it; if the pool is smaller,
the CSV/report says so explicitly rather than presenting the rate as settled.

Outcome (funded / active-and-growing / dead) is NOT something this script can
determine on its own — that requires a human (or a follow-up research pass) to
check each company's current status. This script's job is to build the two
correctly-sized, correctly-blinded samples and hand back a review CSV with an
empty `outcome` column; a second pass (`summarize`) computes the good-outcome
rate once that column is filled in.

Usage:
    python -m src.backtest build --after 2025-09-01 --before 2026-03-01 \\
        --out-dir data/scored/backtest
    # ... fill in the outcome column in data/scored/backtest/review.csv ...
    python -m src.backtest summarize --review data/scored/backtest/review.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from src.enrich import enrich_file
from src.ingest import ingest
from src.scoring import score_batch

MIN_SAMPLE = 50
REVIEW_COLUMNS = [
    "sample_group",
    "ph_id",
    "name",
    "domain",
    "ph_url",
    "composite_score",
    "created_at",
    "outcome",  # fill in: funded | active | dead
    "notes",
]


def build(after: str, before: str, out_dir: Path, seed: int = 42) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = out_dir / "raw.jsonl"
    records = ingest(f"{after}T00:00:00Z", f"{before}T00:00:00Z")
    raw_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")

    enriched_path = out_dir / "enriched.jsonl"
    enrich_file(raw_path, enriched_path)
    enriched = [json.loads(l) for l in enriched_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    scored = score_batch(enriched)
    scored_path = out_dir / "scored.jsonl"
    scored_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in scored), encoding="utf-8")

    pool_size = len(scored)
    sample_size = min(MIN_SAMPLE, pool_size // 2) if pool_size < MIN_SAMPLE * 2 else MIN_SAMPLE
    provisional = sample_size < MIN_SAMPLE

    ranked = sorted(scored, key=lambda r: r["composite_score"], reverse=True)
    top_decile_cut = max(1, pool_size // 10)
    top_pool = ranked[:top_decile_cut]
    top_sample = top_pool[:sample_size] if len(top_pool) >= sample_size else top_pool

    remaining = ranked[top_decile_cut:]
    random.Random(seed).shuffle(remaining)
    random_sample = remaining[:sample_size]

    review_path = out_dir / "review.csv"
    with review_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for group, sample in (("top_decile", top_sample), ("random", random_sample)):
            for rec in sample:
                writer.writerow(
                    {
                        "sample_group": group,
                        "ph_id": rec["ph_id"],
                        "name": rec["name"],
                        "domain": rec.get("domain"),
                        "ph_url": rec.get("ph_url"),
                        "composite_score": rec["composite_score"],
                        "created_at": rec.get("created_at"),
                        "outcome": "",
                        "notes": "",
                    }
                )

    print(f"Launch pool: {pool_size} (top-decile cut: {top_decile_cut})")
    print(f"Samples built: top_decile={len(top_sample)}, random={len(random_sample)}")
    if provisional:
        print(
            f"WARNING: pool too small for n>={MIN_SAMPLE} per group. "
            f"Results from this window must be reported as PROVISIONAL, not settled."
        )
    print(f"Fill in the 'outcome' column (funded/active/dead) in {review_path}, then run `summarize`.")


def summarize(review_path: Path) -> None:
    rows = list(csv.DictReader(review_path.open(encoding="utf-8")))
    if any(not r["outcome"] for r in rows):
        missing = sum(1 for r in rows if not r["outcome"])
        print(f"WARNING: {missing}/{len(rows)} rows have no outcome filled in yet — summary will exclude them.")

    good = {"funded", "active"}
    by_group: dict[str, list[str]] = {}
    for r in rows:
        if not r["outcome"]:
            continue
        by_group.setdefault(r["sample_group"], []).append(r["outcome"].strip().lower())

    for group, outcomes in by_group.items():
        n = len(outcomes)
        good_count = sum(1 for o in outcomes if o in good)
        rate = good_count / n if n else 0.0
        provisional_note = " (PROVISIONAL: n<50)" if n < MIN_SAMPLE else ""
        print(f"{group}: n={n}, good-outcome rate={rate:.1%}{provisional_note}")

    if "top_decile" in by_group and "random" in by_group:
        top_rate = sum(1 for o in by_group["top_decile"] if o in good) / max(len(by_group["top_decile"]), 1)
        rand_rate = sum(1 for o in by_group["random"] if o in good) / max(len(by_group["random"]), 1)
        verdict = "RUBRIC VALIDATED (top-decile clearly outperforms random)" if top_rate > rand_rate else (
            "RUBRIC NOT VALIDATED — revisit weights (see scoring.py weight-sweep step) before building further"
        )
        print(f"\n{verdict}")


def main():
    parser = argparse.ArgumentParser(description="Backtest the scoring rubric against a historical PH window.")
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser("build")
    build_p.add_argument("--after", required=True)
    build_p.add_argument("--before", required=True)
    build_p.add_argument("--out-dir", required=True)
    build_p.add_argument("--seed", type=int, default=42)

    summarize_p = sub.add_parser("summarize")
    summarize_p.add_argument("--review", required=True)

    args = parser.parse_args()
    if args.command == "build":
        build(args.after, args.before, Path(args.out_dir), seed=args.seed)
    elif args.command == "summarize":
        summarize(Path(args.review))


if __name__ == "__main__":
    main()
