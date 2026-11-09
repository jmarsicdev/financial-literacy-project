
import unittest
from pydantic import ValidationError

from app.main import app
from app.rag_governance.router import (
    GovernanceRequestIn,
    evaluate_request_endpoint,
)


class TestGovernanceRouter(unittest.TestCase):

    def test_educational_request_api_response(self):
        request = GovernanceRequestIn(query="What is an ETF?")

        result = evaluate_request_endpoint(request)

        self.assertEqual(result.classification.intent, "EDUCATIONAL")
        self.assertEqual(
            result.classification.recommended_action,
            "ALLOW",
        )
        self.assertTrue(result.should_generate)

        terms = [entry.term for entry in result.glossary_terms]
        self.assertIn("Exchange-Traded Fund (ETF)", terms)

    def test_personalized_advice_api_response(self):
        request = GovernanceRequestIn(
            query="Should I invest in Tesla?"
        )

        result = evaluate_request_endpoint(request)

        self.assertEqual(
            result.classification.intent,
            "PERSONALIZED_ADVICE",
        )
        self.assertEqual(result.generation_mode, "SAFE_REDIRECT")

    def test_transactional_request_api_response(self):
        request = GovernanceRequestIn(
            query="Buy 10 shares of Tesla for me"
        )

        result = evaluate_request_endpoint(request)

        self.assertEqual(
            result.classification.intent,
            "TRANSACTIONAL",
        )
        self.assertFalse(result.should_generate)
        self.assertEqual(result.generation_mode, "NO_GENERATION")

    def test_empty_query_is_rejected(self):
        with self.assertRaises(ValidationError):
            GovernanceRequestIn(query="")

    def test_governance_route_is_registered(self):
        paths = {route.path for route in app.routes}

        self.assertIn(
            "/governance/evaluate-request",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
