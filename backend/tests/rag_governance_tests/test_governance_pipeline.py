
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


if __name__ == "__main__":
    unittest.main()
