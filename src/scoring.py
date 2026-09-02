"""Weighted scoring rubric v1 (task rec:01M1H5J8610955Q2Y1R6WSQV8W).

Four categories, composite 0-100:
  Traction      0-30  votes + comments, log-scaled
  Team          0-25  maker count + prior-post history + social-presence breadth
  Market/Prod   0-25  GitHub stars + category crowding + site-maturity breadth
  Momentum      0-20  votes-per-day-since-launch velocity

All ten terms are continuous. Every term started this way except three:
linkedin_presence, pricing_page_present, docs_or_demo_present, which
enrichment can only observe as yes/no.

Per kb:lesson:weighted_composite_binary_term_saturates_partition, those were
weight-swept before finalizing (see `sweep_binary_weight`, run against 200
synthetic records, top_n=20):

    team_linkedin_presence   weight 0 -> 0.25: dominance share 0.0 -> 0.55
    market_pricing_page      weight 0 -> 0.25: dominance share 0.0 -> 0.60
    market_docs_demo         weight 0 -> 0.25: dominance share 0.0 -> 0.45

Every one of them saturates the instant the weight leaves zero — there is no
safe nonzero range to document, because continuous scores cluster densely
near the top and even a tiny binary bonus reorders that whole neighborhood.
Per the lesson's fallback ("replace it with a continuous proxy"), each was
folded into a fractional signal instead of scored standalone:

  - team_social_presence: fraction of {LinkedIn, Twitter/X} company links
    found (0, 0.5, or 1), replacing the standalone LinkedIn flag.
  - market_site_maturity: fraction of {pricing page, docs/demo page} found
    (0, 0.5, or 1), replacing the two standalone page-presence flags.

Re-run `sweep_binary_weight` (or an equivalent continuous-term check) if a
new yes/no signal is ever added to this rubric — do not skip the sweep step.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

DEFAULT_WEIGHTS = {
    # Traction (sums to 30)
    "traction_votes": 20,
    "traction_comments": 10,
    # Team (sums to 25)
    "team_maker_count": 8,
    "team_repeat_founder": 10,
    "team_social_presence": 7,  # continuous: fraction of {LinkedIn, Twitter/X} found
    # Market/Product (sums to 25)
    "market_github_stars": 10,
    "market_category_crowding": 5,
    "market_site_maturity": 10,  # continuous: fraction of {pricing, docs/demo} found
    # Momentum (sums to 20)
    "momentum_velocity": 20,
}

# Kept only for the historical record + the sweep_binary_weight helper's own
# tests/docs; the shipped rubric above has no standalone binary terms left.
BINARY_TERMS = ["team_linkedin_presence", "market_pricing_page", "market_docs_demo"]

VOTES_CAP = 1000
COMMENTS_CAP = 200
STARS_CAP = 5000
MAKER_COUNT_CAP = 4
PRIOR_POSTS_CAP = 5
CROWDING_CAP = 15  # same-topic launches in the surrounding window; more = more crowded
VELOCITY_CAP = 100.0  # votes per day


def _log_scaled(value: float, cap: float) -> float:
    """0..1, log-scaled so early votes/stars matter more than later ones."""
    value = max(0.0, value or 0.0)
    return min(math.log1p(value) / math.log1p(cap), 1.0)


def _linear_scaled(value: float, cap: float) -> float:
    value = max(0.0, value or 0.0)
    return min(value / cap, 1.0)


def score_traction(rec: dict, weights: dict) -> dict:
    votes = _log_scaled(rec.get("votes_count", 0), VOTES_CAP) * weights["traction_votes"]
    comments = _log_scaled(rec.get("comments_count", 0), COMMENTS_CAP) * weights["traction_comments"]
    return {"traction_votes": round(votes, 2), "traction_comments": round(comments, 2)}


def score_team(rec: dict, weights: dict) -> dict:
    makers = rec.get("makers") or []
    maker_count = _linear_scaled(len(makers), MAKER_COUNT_CAP) * weights["team_maker_count"]

    prior_counts = [m.get("prior_post_count") for m in makers if m.get("prior_post_count") is not None]
    repeat_founder_signal = 0.0
    if prior_counts:
        repeat_founder_signal = _linear_scaled(max(prior_counts), PRIOR_POSTS_CAP) * weights["team_repeat_founder"]

    enrichment = rec.get("enrichment") or {}
    channels_found = sum(
        1 for present in (enrichment.get("linkedin_company_url"), enrichment.get("twitter_url")) if present
    )
    social_presence = (channels_found / 2) * weights["team_social_presence"]

    return {
        "team_maker_count": round(maker_count, 2),
        "team_repeat_founder": round(repeat_founder_signal, 2),
        "team_social_presence": round(social_presence, 2),
    }


def score_market_product(rec: dict, weights: dict, crowding_count: int = 0) -> dict:
    enrichment = rec.get("enrichment") or {}
    stars = enrichment.get("github_stars")
    github_component = _log_scaled(stars, STARS_CAP) * weights["market_github_stars"] if stars else 0.0

    # more crowding -> lower score, so invert the linear scale
    crowding_component = (1 - _linear_scaled(crowding_count, CROWDING_CAP)) * weights["market_category_crowding"]

    pages_found = sum(
        1 for present in (enrichment.get("has_pricing_page"), enrichment.get("has_docs_or_demo")) if present
    )
    site_maturity_component = (pages_found / 2) * weights["market_site_maturity"]

    return {
        "market_github_stars": round(github_component, 2),
        "market_category_crowding": round(crowding_component, 2),
        "market_site_maturity": round(site_maturity_component, 2),
    }


def score_momentum(rec: dict, weights: dict, as_of: datetime | None = None) -> dict:
    created_at = rec.get("created_at")
    if not created_at:
        return {"momentum_velocity": 0.0}
    try:
        launched = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return {"momentum_velocity": 0.0}
    reference = as_of or datetime.now(timezone.utc)
    days_since = max((reference - launched).total_seconds() / 86400, 1.0)
    velocity = (rec.get("votes_count", 0) or 0) / days_since
    return {"momentum_velocity": round(_linear_scaled(velocity, VELOCITY_CAP) * weights["momentum_velocity"], 2)}


def score_record(rec: dict, weights: dict | None = None, crowding_count: int = 0, as_of: datetime | None = None) -> dict:
    weights = weights or DEFAULT_WEIGHTS
    sub = {}
    sub.update(score_traction(rec, weights))
    sub.update(score_team(rec, weights))
    sub.update(score_market_product(rec, weights, crowding_count=crowding_count))
    sub.update(score_momentum(rec, weights, as_of=as_of))

    traction = sub["traction_votes"] + sub["traction_comments"]
    team = sub["team_maker_count"] + sub["team_repeat_founder"] + sub["team_social_presence"]
    market = sub["market_github_stars"] + sub["market_category_crowding"] + sub["market_site_maturity"]
    momentum = sub["momentum_velocity"]
    composite = round(traction + team + market + momentum, 2)

    return {
        "sub_scores": sub,
        "traction_score": round(traction, 2),
        "team_score": round(team, 2),
        "market_product_score": round(market, 2),
        "momentum_score": round(momentum, 2),
        "composite_score": composite,
    }


def compute_crowding(records: list[dict]) -> dict[str, int]:
    """Count same-topic launches per record's topic set, for the crowding term.

    Simple v1: for each record, count how many other records in the same
    batch share at least one topic slug with it.
    """
    from collections import defaultdict

    topic_index: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        for topic in rec.get("topics", []):
            topic_index[topic].append(rec["ph_id"])

    crowding: dict[str, int] = {}
    for rec in records:
        peers = set()
        for topic in rec.get("topics", []):
            peers.update(topic_index[topic])
        peers.discard(rec["ph_id"])
        crowding[rec["ph_id"]] = len(peers)
    return crowding


def score_batch(records: list[dict], weights: dict | None = None, as_of: datetime | None = None) -> list[dict]:
    weights = weights or DEFAULT_WEIGHTS
    crowding = compute_crowding(records)
    scored = []
    for rec in records:
        result = score_record(rec, weights=weights, crowding_count=crowding.get(rec["ph_id"], 0), as_of=as_of)
        scored.append({**rec, **result})
    return scored


def sweep_binary_weight(records: list[dict], term: str, weight_grid: list[float], top_n: int = 20) -> list[dict]:
    """Historical diagnostic: for a *binary* term, recompute the composite at
    each weight in the grid and report what fraction of the top-N has that
    flag set. Kept so the saturation finding documented above is reproducible
    and so a future binary term (should one get added) can be checked the
    same way before it ships. The shipped DEFAULT_WEIGHTS has no standalone
    binary term to sweep — see the module docstring for why.
    """
    if term not in BINARY_TERMS:
        raise ValueError(f"{term} is not a registered binary term: {BINARY_TERMS}")

    legacy_weights = dict(DEFAULT_WEIGHTS)
    legacy_weights.pop("team_social_presence", None)
    legacy_weights.pop("market_site_maturity", None)
    legacy_weights.update(
        {"team_linkedin_presence": 0.0, "market_pricing_page": 0.0, "market_docs_demo": 0.0}
    )

    def _score_with_legacy_term(rec, weights):
        enrichment = rec.get("enrichment") or {}
        sub = {}
        sub.update(score_traction(rec, weights))
        maker_count = _linear_scaled(len(rec.get("makers") or []), MAKER_COUNT_CAP) * weights["team_maker_count"]
        prior_counts = [m.get("prior_post_count") for m in (rec.get("makers") or []) if m.get("prior_post_count") is not None]
        repeat_founder = _linear_scaled(max(prior_counts), PRIOR_POSTS_CAP) * weights["team_repeat_founder"] if prior_counts else 0.0
        linkedin = weights["team_linkedin_presence"] if enrichment.get("linkedin_company_url") else 0.0
        sub.update({"team_maker_count": maker_count, "team_repeat_founder": repeat_founder, "team_linkedin_presence": linkedin})
        stars = enrichment.get("github_stars")
        github = _log_scaled(stars, STARS_CAP) * weights["market_github_stars"] if stars else 0.0
        pricing = weights["market_pricing_page"] if enrichment.get("has_pricing_page") else 0.0
        docs = weights["market_docs_demo"] if enrichment.get("has_docs_or_demo") else 0.0
        sub.update({"market_github_stars": github, "market_pricing_page": pricing, "market_docs_demo": docs, "market_category_crowding": 0.0})
        sub.update(score_momentum(rec, weights))
        composite = sum(sub.values())
        return sub, composite

    rows = []
    for w in weight_grid:
        weights = dict(legacy_weights)
        weights[term] = w
        computed = [_score_with_legacy_term(rec, weights) for rec in records]
        ranked = sorted(computed, key=lambda t: t[1], reverse=True)[:top_n]
        flagged = sum(1 for sub, _ in ranked if sub.get(term, 0) > 0)
        rows.append({"weight": w, "top_n_dominance_share": round(flagged / max(len(ranked), 1), 3)})
    return rows
