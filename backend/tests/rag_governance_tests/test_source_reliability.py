
import unittest

from app.rag_governance.source_reliability import (
    SourceMetadata,
    SourceTier,
    evaluate_source_reliability,
)


class TestSourceReliability(unittest.TestCase):

    def make_source(self, url, title="Test financial source", publisher="Test Publisher"):
        return SourceMetadata(
            source_id="source-001",
            title=title,
            publisher=publisher,
            url=url,
        )

    def test_tier_1_regulatory_source(self):
        source = self.make_source("https://www.sec.gov/")

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.TIER_1)
        self.assertTrue(result.can_support_important_claims)

    def test_tier_2_official_exchange_source(self):
        source = self.make_source("https://www.nasdaq.com/")

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.TIER_2)
        self.assertTrue(result.can_support_important_claims)

    def test_tier_3_financial_journalism_source(self):
        source = self.make_source("https://www.reuters.com/")

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.TIER_3)
        self.assertFalse(result.can_support_important_claims)
        self.assertIn("corroboration_recommended", result.warnings)

    def test_tier_4_user_generated_source(self):
        source = self.make_source("https://www.reddit.com/")

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.TIER_4)
        self.assertFalse(result.can_support_important_claims)
        self.assertIn("user_generated_content", result.warnings)

    def test_unknown_domain_is_unclassified(self):
        source = self.make_source("https://example.org/article")

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.UNCLASSIFIED)
        self.assertFalse(result.can_support_important_claims)
        self.assertIn("unclassified_source_domain", result.warnings)

    def test_invalid_url_is_rejected(self):
        source = self.make_source("ftp://sec.gov/document")

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.INVALID)
        self.assertIn("invalid_or_unsafe_url", result.warnings)

    def test_lookalike_domain_is_not_trusted(self):
        source = self.make_source("https://sec.gov.example.com/article")

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.UNCLASSIFIED)
        self.assertFalse(result.can_support_important_claims)

    def test_legitimate_regulatory_subdomain_is_recognized(self):
        source = self.make_source("https://www.investor.gov/")

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.TIER_1)
        self.assertEqual(result.matched_registry_domain, "investor.gov")

    def test_missing_title_and_publisher_generate_warnings(self):
        source = self.make_source(
            "https://www.sec.gov/",
            title="",
            publisher="",
        )

        result = evaluate_source_reliability(source)

        self.assertIn("missing_source_title", result.warnings)
        self.assertIn("missing_publisher", result.warnings)


if __name__ == "__main__":
    unittest.main()
