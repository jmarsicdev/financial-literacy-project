
import unittest

from app.rag_governance.source_reliability import (
    SourceMetadata,
    SourceTier,
    classify_url,
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

    def test_yahoo_finance_pages_are_journalism_by_domain(self):
        # a Yahoo Finance article is syndicated journalism; only this service's own
        # stored price rows (kind="price_bars") are treated as data
        for url in (
            "https://finance.yahoo.com/news/nvidia-stock-rises-120000000.html",
            "https://finance.yahoo.com/quote/NVDA/history/",
        ):
            with self.subTest(url=url):
                result = evaluate_source_reliability(self.make_source(url))

                self.assertEqual(result.tier, SourceTier.TIER_3)
                self.assertEqual(result.matched_registry_domain, "yahoo.com")
                self.assertFalse(result.can_support_important_claims)

    def test_financial_news_and_analysis_sites_are_tier_3(self):
        for domain in (
            "fool.com",
            "seekingalpha.com",
            "benzinga.com",
            "investors.com",
            "zacks.com",
            "businessinsider.com",
            "thestreet.com",
            "investing.com",
            "barchart.com",
        ):
            with self.subTest(domain=domain):
                source = self.make_source(f"https://www.{domain}/article")

                result = evaluate_source_reliability(source)

                self.assertEqual(result.tier, SourceTier.TIER_3)
                self.assertFalse(result.can_support_important_claims)
                self.assertIn("corroboration_recommended", result.warnings)

    def test_social_platforms_stay_tier_4(self):
        for domain in ("reddit.com", "stocktwits.com", "x.com"):
            with self.subTest(domain=domain):
                result = evaluate_source_reliability(self.make_source(f"https://{domain}/thread"))

                self.assertEqual(result.tier, SourceTier.TIER_4)

    def test_first_party_computed_evidence_is_official_data(self):
        for kind in ("price_bars", "risk_profiles"):
            with self.subTest(kind=kind):
                source = SourceMetadata(
                    source_id=f"{kind}-NVDA",
                    title="NVDA historical risk profile (2026 Q3)",
                    publisher="Team 5 Spark risk model",
                    url="http://localhost:8000/risk-profiles/NVDA",
                    kind=kind,
                )

                result = evaluate_source_reliability(source)

                self.assertEqual(result.tier, SourceTier.TIER_2)
                self.assertEqual(result.matched_registry_domain, f"first_party:{kind}")
                self.assertTrue(result.can_support_important_claims)
                self.assertIn("computed by this service", result.guidance)

    def test_first_party_kind_does_not_bypass_url_validation(self):
        source = SourceMetadata(
            source_id="price-NVDA",
            title="NVDA daily price history",
            publisher="yfinance",
            url="not a url",
            kind="price_bars",
        )

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.INVALID)

    def test_unknown_kind_falls_back_to_the_domain_registry(self):
        source = SourceMetadata(
            source_id="x",
            title="t",
            publisher="p",
            url="https://example.org/article",
            kind="search_results",
        )

        result = evaluate_source_reliability(source)

        self.assertEqual(result.tier, SourceTier.UNCLASSIFIED)

    def test_classify_url_gives_the_registry_tier_or_unclassified(self):
        self.assertEqual(classify_url("https://www.sec.gov/x"), SourceTier.TIER_1)
        self.assertEqual(classify_url("https://www.reuters.com/x"), SourceTier.TIER_3)
        self.assertEqual(classify_url("https://www.reddit.com/x"), SourceTier.TIER_4)
        self.assertEqual(classify_url("https://unknown.example.net/x"), SourceTier.UNCLASSIFIED)
        self.assertEqual(classify_url(""), SourceTier.UNCLASSIFIED)
        self.assertEqual(classify_url(None), SourceTier.UNCLASSIFIED)


if __name__ == "__main__":
    unittest.main()
