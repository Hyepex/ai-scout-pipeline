import unittest
from datetime import datetime, timezone

from src.scoring import DEFAULT_WEIGHTS, score_batch, score_record, sweep_binary_weight


def make_record(**overrides):
    base = {
        "ph_id": "1",
        "name": "TestCo",
        "votes_count": 100,
        "comments_count": 10,
        "created_at": "2026-08-01T00:00:00Z",
        "topics": ["artificial-intelligence"],
        "makers": [{"id": "m1", "prior_post_count": 2}],
        "enrichment": {
            "has_pricing_page": True,
            "has_docs_or_demo": True,
            "linkedin_company_url": "https://linkedin.com/company/testco",
            "github_stars": 500,
        },
    }
    base.update(overrides)
    return base


class TestScoring(unittest.TestCase):
    def test_deterministic(self):
        rec = make_record()
        as_of = datetime(2026, 9, 2, tzinfo=timezone.utc)
        r1 = score_record(rec, as_of=as_of)
        r2 = score_record(rec, as_of=as_of)
        self.assertEqual(r1["composite_score"], r2["composite_score"])

    def test_composite_within_bounds(self):
        rec = make_record(votes_count=100000, comments_count=10000)
        rec["enrichment"]["github_stars"] = 1_000_000
        result = score_record(rec)
        self.assertLessEqual(result["composite_score"], 100.0)
        self.assertGreaterEqual(result["composite_score"], 0.0)

    def test_zero_signal_scores_zero(self):
        rec = make_record(
            votes_count=0,
            comments_count=0,
            makers=[],
            enrichment={
                "has_pricing_page": False,
                "has_docs_or_demo": False,
                "linkedin_company_url": None,
                "github_stars": None,
            },
        )
        result = score_record(rec, as_of=datetime(2026, 8, 1, tzinfo=timezone.utc))
        # market_category_crowding measures market condition (competitor count), not
        # company effort, so it's non-zero here (crowding_count defaults to 0 = no
        # competitors = a genuine positive signal). Every effort-based term is zero.
        self.assertEqual(result["sub_scores"]["traction_votes"], 0.0)
        self.assertEqual(result["sub_scores"]["traction_comments"], 0.0)
        self.assertEqual(result["sub_scores"]["team_maker_count"], 0.0)
        self.assertEqual(result["sub_scores"]["team_repeat_founder"], 0.0)
        self.assertEqual(result["sub_scores"]["team_social_presence"], 0.0)
        self.assertEqual(result["sub_scores"]["market_github_stars"], 0.0)
        self.assertEqual(result["sub_scores"]["market_site_maturity"], 0.0)
        self.assertEqual(result["sub_scores"]["momentum_velocity"], 0.0)

    def test_more_votes_scores_higher(self):
        low = score_record(make_record(votes_count=5))
        high = score_record(make_record(votes_count=500))
        self.assertGreater(high["composite_score"], low["composite_score"])

    def test_weight_sweep_shape(self):
        records = [make_record(ph_id=str(i), votes_count=10 * i) for i in range(1, 30)]
        rows = sweep_binary_weight(records, "team_linkedin_presence", [0, 5, 10, 15, 20], top_n=10)
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertIn("top_n_dominance_share", row)
            self.assertGreaterEqual(row["top_n_dominance_share"], 0.0)
            self.assertLessEqual(row["top_n_dominance_share"], 1.0)

    def test_weights_sum_matches_category_caps(self):
        self.assertEqual(DEFAULT_WEIGHTS["traction_votes"] + DEFAULT_WEIGHTS["traction_comments"], 30)
        self.assertEqual(
            DEFAULT_WEIGHTS["team_maker_count"]
            + DEFAULT_WEIGHTS["team_repeat_founder"]
            + DEFAULT_WEIGHTS["team_social_presence"],
            25,
        )
        self.assertEqual(
            DEFAULT_WEIGHTS["market_github_stars"]
            + DEFAULT_WEIGHTS["market_category_crowding"]
            + DEFAULT_WEIGHTS["market_site_maturity"],
            25,
        )
        self.assertEqual(DEFAULT_WEIGHTS["momentum_velocity"], 20)

    def test_social_presence_is_fractional_not_binary(self):
        """Both LinkedIn and Twitter/X found should score higher than just one."""
        one_channel = score_record(
            make_record(enrichment={"linkedin_company_url": "https://linkedin.com/company/x", "has_pricing_page": False, "has_docs_or_demo": False})
        )
        two_channels = score_record(
            make_record(
                enrichment={
                    "linkedin_company_url": "https://linkedin.com/company/x",
                    "twitter_url": "https://x.com/x",
                    "has_pricing_page": False,
                    "has_docs_or_demo": False,
                }
            )
        )
        self.assertGreater(two_channels["sub_scores"]["team_social_presence"], one_channel["sub_scores"]["team_social_presence"])


if __name__ == "__main__":
    unittest.main()
