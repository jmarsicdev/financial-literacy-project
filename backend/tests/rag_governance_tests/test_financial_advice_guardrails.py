import unittest

from app.rag_governance.financial_advice_guardrails import (
    GuardrailStatus,
    validate_generated_response,
)


class TestFinancialAdviceGuardrails(unittest.TestCase):

    def test_educational_response_passes(self):
        response = (
            "An ETF is an investment fund that holds a basket "
            "of securities and trades on an exchange."
        )

        result = validate_generated_response(response)

        self.assertEqual(result.status, GuardrailStatus.PASS)

    def test_direct_investment_recommendation_is_blocked(self):
        response = "You should buy Tesla stock."

        result = validate_generated_response(response)

        self.assertEqual(result.status, GuardrailStatus.BLOCK)
        self.assertIn(
            "direct_investment_recommendation",
            result.violations
        )

    def test_personalized_portfolio_allocation_is_blocked(self):
        response = "Allocate 20% of your portfolio to technology stocks."

        result = validate_generated_response(response)

        self.assertEqual(result.status, GuardrailStatus.BLOCK)
        self.assertIn(
            "personalized_portfolio_allocation",
            result.violations
        )

    def test_guaranteed_returns_are_blocked(self):
        response = "This investment offers guaranteed returns."

        result = validate_generated_response(response)

        self.assertEqual(result.status, GuardrailStatus.BLOCK)
        self.assertIn(
            "guaranteed_or_risk_free_returns",
            result.violations
        )

    def test_personalized_suitability_claim_requires_review(self):
        response = "This fund is suitable for your risk tolerance."

        result = validate_generated_response(response)

        self.assertEqual(result.status, GuardrailStatus.REVIEW)
        self.assertIn(
            "personalized_suitability_claim",
            result.violations
        )

    def test_empty_response_is_blocked(self):
        result = validate_generated_response("")

        self.assertEqual(result.status, GuardrailStatus.BLOCK)
        self.assertIn("empty_or_invalid_response", result.violations)


if __name__ == "__main__":
    unittest.main()