
import unittest

from app.rag_governance.governance_pipeline import (
    GenerationMode,
    PipelineStatus,
    evaluate_request,
    evaluate_generated_response,
)

from app.rag_governance.schemas import Intent, RecommendedAction

from app.rag_governance.citation_validator import Citation
from app.rag_governance.source_reliability import SourceTier


class TestGovernancePipeline(unittest.TestCase):

    def make_citation(
        self,
        citation_id="1",
        url="https://www.sec.gov/",
    ):
        return Citation(
            citation_id=citation_id,
            title="Investor Information",
            publisher="U.S. Securities and Exchange Commission",
            url=url,
            supporting_text=(
                "An ETF is an investment fund that trades on an exchange."
            ),
            retrieved_at="2026-11-08",
            publication_date="2025-01-15",
        )

    # Pre-generation tests

    def test_educational_request_allows_standard_generation(self):
        result = evaluate_request("What is an ETF?")

        self.assertEqual(result.classification.intent, Intent.EDUCATIONAL)
        self.assertTrue(result.should_generate)
        self.assertEqual(
            result.generation_mode,
            GenerationMode.STANDARD,
        )
        self.assertGreater(len(result.glossary_terms), 0)

    def test_research_request_requires_cited_information(self):
        result = evaluate_request("Compare VOO and SPY")

        self.assertEqual(result.classification.intent, Intent.RESEARCH)
        self.assertTrue(result.should_generate)
        self.assertEqual(
            result.generation_mode,
            GenerationMode.CITED_INFORMATION,
        )

    def test_personalized_advice_uses_safe_redirect(self):
        result = evaluate_request("Should I invest in Tesla?")

        self.assertEqual(
            result.classification.intent,
            Intent.PERSONALIZED_ADVICE,
        )
        self.assertTrue(result.should_generate)
        self.assertEqual(
            result.generation_mode,
            GenerationMode.SAFE_REDIRECT,
        )

    def test_transactional_request_does_not_generate(self):
        result = evaluate_request("Buy 10 shares of Tesla for me")

        self.assertEqual(
            result.classification.intent,
            Intent.TRANSACTIONAL,
        )
        self.assertFalse(result.should_generate)
        self.assertEqual(
            result.generation_mode,
            GenerationMode.NO_GENERATION,
        )
        self.assertIn(
            "Do not place, submit, or execute financial transactions.",
            result.guidance
        )

    # Post-generation tests

    def test_valid_response_and_tier_1_citation_pass(self):
        response = (
            "An ETF is an investment fund that trades on an exchange. [1]"
        )

        result = evaluate_generated_response(
            response,
            [self.make_citation()],
        )

        self.assertEqual(result.status, PipelineStatus.PASS)
        self.assertEqual(len(result.source_checks), 1)
        self.assertEqual(
            result.source_checks[0].reliability.tier,
            SourceTier.TIER_1,
        )

    def test_direct_investment_recommendation_is_blocked(self):
        response = "You should buy Tesla stock."

        result = evaluate_generated_response(response, [])

        self.assertEqual(result.status, PipelineStatus.BLOCK)
        self.assertIn("response_guardrail_block", result.reasons)

    def test_missing_financial_citation_requires_review(self):
        response = "ETFs are investment funds that trade on exchanges."

        result = evaluate_generated_response(response, [])

        self.assertEqual(result.status, PipelineStatus.REVIEW)
        self.assertEqual(
            result.citation_validation.status.value,
            "REVIEW",
        )

    def test_tier_4_source_requires_review(self):
        response = "An ETF is an investment fund. [1]"

        citation = self.make_citation(
            url="https://www.reddit.com/",
        )

        result = evaluate_generated_response(
            response,
            [citation],
        )

        self.assertEqual(result.status, PipelineStatus.REVIEW)
        self.assertEqual(
            result.source_checks[0].reliability.tier,
            SourceTier.TIER_4,
        )
        self.assertIn(
            "citation_1:user_generated_source",
            result.reasons,
        )

    def test_journalism_alone_requires_review(self):
        response = "Nvidia reports earnings next month. [1]"

        result = evaluate_generated_response(
            response,
            [self.make_citation(url="https://www.reuters.com/markets/nvidia")],
        )

        self.assertEqual(result.status, PipelineStatus.REVIEW)
        self.assertIn("citation_1:corroboration_recommended", result.reasons)

    def test_journalism_anchored_by_official_data_passes(self):
        response = (
            "NVDA closed at 180.12 on 2026-11-20 [1]. "
            "Reuters reported strong data-center demand this quarter [2]."
        )
        price_row = Citation(
            citation_id="1",
            title="NVDA daily price history",
            publisher="yfinance",
            url="https://finance.yahoo.com/quote/NVDA/history/",
            supporting_text="NVDA daily closing prices from stored market data.",
            retrieved_at="2026-11-21T00:00:00+00:00",
            kind="price_bars",
        )
        news = self.make_citation(citation_id="2", url="https://www.reuters.com/markets/nvidia")

        result = evaluate_generated_response(response, [price_row, news])

        self.assertEqual(result.status, PipelineStatus.PASS)
        self.assertEqual(result.reasons, [])
        tiers = {c.citation_id: c.reliability.tier for c in result.source_checks}
        self.assertEqual(tiers, {"1": SourceTier.TIER_2, "2": SourceTier.TIER_3})
        # the journalism source still carries its own caveat for the UI
        self.assertIn("corroboration_recommended", result.source_checks[1].reliability.warnings)

    def test_official_anchor_does_not_excuse_unclassified_or_social_sources(self):
        response = "An ETF is an investment fund. [1] People on forums disagree. [2] A blog says otherwise. [3]"
        citations = [
            self.make_citation(citation_id="1"),
            self.make_citation(citation_id="2", url="https://www.reddit.com/r/investing/"),
            self.make_citation(citation_id="3", url="https://random-blog.example.net/post"),
        ]

        result = evaluate_generated_response(response, citations)

        self.assertEqual(result.status, PipelineStatus.REVIEW)
        self.assertIn("citation_2:user_generated_source", result.reasons)
        self.assertIn("citation_3:source_requires_review", result.reasons)

    def test_uncited_journalism_does_not_count_as_an_anchor_or_a_reason(self):
        # only sources actually referenced in the answer are evaluated
        response = "An ETF is an investment fund that trades on an exchange. [1]"
        citations = [
            self.make_citation(citation_id="1", url="https://www.cnbc.com/etfs"),
            self.make_citation(citation_id="2"),
        ]

        result = evaluate_generated_response(response, citations)

        self.assertEqual(result.status, PipelineStatus.REVIEW)
        self.assertEqual(result.reasons, ["citation_1:corroboration_recommended"])

    def test_glossary_definition_does_not_anchor_journalism(self):
        response = "A stock is a share of ownership in a company [1]. Nvidia shares rose after earnings [2]."
        glossary = Citation(
            citation_id="1",
            title="Stock (SEC glossary)",
            publisher="U.S. Securities and Exchange Commission",
            url="https://www.investor.gov/introduction-investing/investing-basics/glossary/stocks",
            supporting_text="A stock is a share of ownership in a company.",
            retrieved_at="2026-11-21T00:00:00+00:00",
            kind="glossary",
        )
        news = self.make_citation(citation_id="2", url="https://www.cnbc.com/nvidia-earnings")

        result = evaluate_generated_response(response, [glossary, news])

        self.assertEqual(result.status, PipelineStatus.REVIEW)
        self.assertEqual(result.reasons, ["citation_2:corroboration_recommended"])


if __name__ == "__main__":
    unittest.main()
