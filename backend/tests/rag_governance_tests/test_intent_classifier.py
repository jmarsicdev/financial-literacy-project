
import unittest

from app.rag_governance.schemas import Intent, RecommendedAction
from app.rag_governance.intent_classifier import classify_intent


class TestIntentClassifier(unittest.TestCase):

    def test_educational_query(self):
        result = classify_intent("What is an ETF?")

        self.assertEqual(result.intent, Intent.EDUCATIONAL)
        self.assertEqual(result.recommended_action, RecommendedAction.ALLOW)

    def test_research_query(self):
        result = classify_intent("Compare VOO and SPY")

        self.assertEqual(result.intent, Intent.RESEARCH)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.ALLOW_WITH_CAUTION
        )

    def test_market_information_query(self):
        result = classify_intent(
            "What is NVIDIA's stock price today?"
        )

        self.assertEqual(result.intent, Intent.MARKET_INFORMATION)

    def test_personalized_advice_query(self):
        result = classify_intent(
            "Should I invest in Tesla?"
        )

        self.assertEqual(result.intent, Intent.PERSONALIZED_ADVICE)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.RESTRICT_AND_REDIRECT
        )

    def test_transactional_query(self):
        result = classify_intent(
            "Buy 10 shares of Tesla for me"
        )

        self.assertEqual(result.intent, Intent.TRANSACTIONAL)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.REJECT
        )

    def test_mixed_educational_and_advice_query(self):
        result = classify_intent(
            "Explain ETFs and tell me which one I should buy"
        )

        self.assertEqual(result.intent, Intent.PERSONALIZED_ADVICE)

    def test_empty_query(self):
        result = classify_intent("")

        self.assertEqual(
            result.intent,
            Intent.UNSUPPORTED_OR_UNCLEAR
        )
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.CLARIFY
        )

    def test_unsupported_query(self):
        result = classify_intent(
            "What is the weather tomorrow?"
        )

        self.assertEqual(
            result.intent,
            Intent.UNSUPPORTED_OR_UNCLEAR
        )

    def test_confidence_range(self):
        result = classify_intent("What is a mutual fund?")

        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_mixed_research_and_advice_query(self):
        query = "Compare Apple and Microsoft stocks and tell me which one I should buy"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.PERSONALIZED_ADVICE)
        self.assertIn("research", result.matched_rules)
        self.assertIn("personalized_advice", result.matched_rules)
        self.assertEqual(
        result.recommended_action,
        RecommendedAction.RESTRICT_AND_REDIRECT
    )
    
    def test_mixed_market_information_and_advice_query(self):
        query = "What is Tesla's current stock price, and should I buy it?"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.PERSONALIZED_ADVICE)
        self.assertIn("market_information", result.matched_rules)
        self.assertIn("personalized_advice", result.matched_rules)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.RESTRICT_AND_REDIRECT
        )

    def test_mixed_educational_and_transactional_query(self):
        query = "Explain stock orders and buy 10 shares of Tesla for me"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.TRANSACTIONAL)
        self.assertIn("educational", result.matched_rules)
        self.assertIn("transactional", result.matched_rules)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.REJECT
        )
    def test_mixed_research_and_transactional_query(self):
        query = "Compare Tesla and Ford stocks, then place an order for 10 Tesla shares"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.TRANSACTIONAL)
        self.assertIn("research", result.matched_rules)
        self.assertIn("transactional", result.matched_rules)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.REJECT
        )
    def test_mixed_market_information_and_transactional_query(self):
        query = "What is Tesla's current stock price, and place an order for 10 shares"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.TRANSACTIONAL)
        self.assertIn("market_information", result.matched_rules)
        self.assertIn("transactional", result.matched_rules)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.REJECT
        )
    def test_multiple_intents_detected(self):
        query = "Explain ETFs, compare VOO and SPY, and tell me which one I should buy"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.PERSONALIZED_ADVICE)
        self.assertIn("educational", result.matched_rules)
        self.assertIn("research", result.matched_rules)
        self.assertIn("personalized_advice", result.matched_rules)
    
    def test_negated_advice_query(self):
        query = "I am not asking whether I should buy Tesla"

        result = classify_intent(query)

        self.assertNotEqual(
            result.intent,
            Intent.PERSONALIZED_ADVICE
        )
        
    def test_uncertainty_is_not_negation(self):
        query = "I am not sure whether I should buy Tesla"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.PERSONALIZED_ADVICE)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.RESTRICT_AND_REDIRECT
        )
        
    def test_hypothetical_investment_question(self):
        query = "Explain why someone might buy Tesla stock"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.EDUCATIONAL)
        self.assertIn("educational", result.matched_rules)
        self.assertNotIn("personalized_advice", result.matched_rules)
        
    def test_implied_personalized_advice(self):
        query = "Would Tesla be a good investment for my situation?"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.PERSONALIZED_ADVICE)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.RESTRICT_AND_REDIRECT
        )
        
    def test_investment_suitability_for_financial_goals(self):
        query = "Would Tesla fit my long-term financial goals?"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.PERSONALIZED_ADVICE)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.RESTRICT_AND_REDIRECT
        )
        
    def test_investment_suitability_for_risk_tolerance(self):
        query = "Would Tesla be suitable for my risk tolerance?"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.PERSONALIZED_ADVICE)
        self.assertEqual(
            result.recommended_action,
            RecommendedAction.RESTRICT_AND_REDIRECT
        )
        
    def test_general_risk_tolerance_question(self):
        query = "Explain what risk tolerance means for investors"

        result = classify_intent(query)

        self.assertEqual(result.intent, Intent.EDUCATIONAL)
        self.assertNotIn("personalized_advice", result.matched_rules)
        
    def test_negated_transactional_request(self):
        query = "I am not asking you to place an order for Tesla"

        result = classify_intent(query)

        self.assertNotEqual(result.intent, Intent.TRANSACTIONAL)
        self.assertNotIn("transactional", result.matched_rules)
if __name__ == "__main__":
    unittest.main()
