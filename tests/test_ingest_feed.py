import unittest
from unittest.mock import patch

from src.ingest_feed import is_ai_related_feed, scrape_product_page


class TestIngestFeed(unittest.TestCase):
    def test_ai_topic_confirmed(self):
        self.assertTrue(is_ai_related_feed({"topics": ["artificial-intelligence"], "tagline": "", "name": ""}))

    def test_ai_keyword_confirmed(self):
        self.assertTrue(is_ai_related_feed({"topics": ["productivity"], "tagline": "An LLM copilot for docs", "name": "X"}))

    def test_non_ai_rejected(self):
        self.assertFalse(is_ai_related_feed({"topics": ["design-tools"], "tagline": "Wait for it to finish", "name": "Y"}))

    def test_scrape_product_page_parses_website_and_github(self):
        html = """
        <html><body>
        <a href="/topics/artificial-intelligence">AI</a>
        <a href="/topics/productivity">Productivity</a>
        <a href="/@jane_doe">Jane</a>
        <a href="/@john_smith">John</a>
        <a href="https://realproduct.ai/?ref=producthunt">Visit</a>
        <a href="https://github.com/janedoe/realproduct?ref=producthunt">GitHub</a>
        <a href="https://x.com/ProductHunt">Twitter</a>
        </body></html>
        """

        class FakeResponse:
            text = html

            def raise_for_status(self):
                pass

        class FakeSession:
            def get(self, url, timeout):
                return FakeResponse()

        result = scrape_product_page("https://www.producthunt.com/products/realproduct", FakeSession())
        self.assertEqual(result["domain"], "realproduct.ai")
        self.assertEqual(result["github_repo_hint"], "janedoe/realproduct")
        self.assertIn("artificial-intelligence", result["topics"])
        self.assertEqual(len(result["makers"]), 2)


if __name__ == "__main__":
    unittest.main()
