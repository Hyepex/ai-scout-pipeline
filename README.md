# AI Scout Pipeline — Phase 1 (Product Hunt MVP)

Automated AI-startup discovery and scoring pipeline. Phase 1 scope: Product
Hunt as the sole data source, to prove a signal-scoring rubric before taking
on the cost or ToS risk of paid sources (Crunchbase, Wellfound, etc).

## What it does

1. **Ingest** (`src/ingest.py`) — pulls launches tagged `artificial-intelligence`
   or `developer-tools` from Product Hunt's official v2 GraphQL API, keeps the
   ones that are genuinely AI-related (topic match, or a keyword match on the
   tagline/description), and resolves each tracking-redirect website link to
   its real domain.
2. **Enrich** (`src/enrich.py`) — visits each resolved domain with Playwright
   and extracts about/pricing/docs page presence, social links (LinkedIn,
   Twitter/X), and a GitHub repo link with its star count.
3. **Score** (`src/scoring.py`) — a four-category weighted rubric, composite
   0-100: Traction (0-30), Team (0-25), Market/Product (0-25), Momentum
   (0-20). See the module docstring for the exact weights and for the
   weight-sweep finding that shaped the design (below).
4. **Backtest** (`src/backtest.py`) — runs the rubric against a 6-12-month-old
   launch window, builds a top-decile sample and a random sample of the same
   size, and reports the good-outcome rate once a human fills in each
   company's current status.
5. **Ranked output** (`src/rank_output.py`) — CSV/JSON export sorted by
   composite score, with every sub-score visible.

`src/pipeline.py` runs steps 1-3 end to end for a given date range.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # then paste in your Product Hunt developer token
```

Get a token: log into producthunt.com → account settings → Applications →
create an application → copy the **Developer Token**. Product Hunt does not
expose maker email addresses through the API — this pipeline never tries to;
derive contact info from the resolved website domain if you need it later.

## Usage

```bash
# Full pipeline for a date range
python -m src.pipeline --after 2026-06-01 --before 2026-09-01 --run-id weekly

# Individual steps
python -m src.ingest --after 2026-06-01 --before 2026-09-01 --out data/raw/launches.jsonl
python -m src.enrich --in data/raw/launches.jsonl --out data/enriched/launches.jsonl
python -m src.rank_output --in data/scored/launches.jsonl --out-prefix data/output/ranked

# Backtest
python -m src.backtest build --after 2025-09-01 --before 2026-03-01 --out-dir data/scored/backtest
# ... fill in the `outcome` column (funded / active / dead) in the generated review.csv ...
python -m src.backtest summarize --review data/scored/backtest/review.csv
```

## Scoring methodology and the weight-sweep finding

The rubric's four categories are meant to be explainable, not a black box —
every sub-score is stored alongside the composite, and every term is
continuous **except when enrichment simply can't produce a continuous signal**.

Three terms started out as plain yes/no flags: LinkedIn found, pricing page
found, docs/demo page found. Before shipping, each was weight-swept per
`kb:lesson:weighted_composite_binary_term_saturates_partition` (a lesson from
a prior ranking build showing binary terms in a weighted composite don't tune
smoothly — they saturate into a hard partition). The sweep confirmed exactly
that: on a synthetic 200-record test set, moving any of the three from weight
0 to weight 0.25 flipped 45-60% of the top-20 immediately — there was no safe
nonzero weight to document. So instead of shipping a small-but-broken weight,
each flag was folded into a fractional signal:

- `team_social_presence` — fraction of {LinkedIn, Twitter/X} company links
  found (0, 0.5, or 1), not a single LinkedIn flag.
- `market_site_maturity` — fraction of {pricing page, docs/demo page} found
  (0, 0.5, or 1), not two separate page-presence flags.

The shipped rubric (`src/scoring.py`) has no standalone binary term left. If
a new yes/no signal is ever added, re-run `sweep_binary_weight` before
finalizing its weight — see the module docstring for the exact numbers.

## Backtest status

**Not yet run.** Ingestion needs a live `PRODUCTHUNT_TOKEN`, which this
environment didn't have when the pipeline was built. Everything above is
built, unit-tested (`python -m unittest discover tests`), and smoke-tested
against synthetic data. Once a token is supplied, run `src.backtest build`
against a 6-12-month-old window, fill in the outcome column, run
`src.backtest summarize`, and paste the result here — the rubric isn't
considered validated until the top-decile sample shows a visibly higher
good-outcome rate than the random sample, per the acceptance criteria this
project was scoped against.

## Scope

**In:** Product Hunt ingestion, website enrichment, the scoring rubric,
historical backtest, ranked CSV/JSON output.
**Out (deferred):** Crunchbase, Wellfound, and all outreach automation
(email/WhatsApp/Telegram/LinkedIn) — until this rubric is proven.
