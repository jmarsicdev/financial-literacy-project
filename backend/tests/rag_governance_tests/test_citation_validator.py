import unittest

from app.rag_governance.citation_validator import (
    Citation,
    CitationStatus,
    validate_citations,
)


class TestCitationValidator(unittest.TestCase):

    def setUp(self):
        self.valid_citation = Citation(
            citation_id="1",
            title="ETF Investor Bulletin",
            publisher="SEC",
            url="https://www.sec.gov/example",
            supporting_text="ETFs are investment funds traded on exchanges.",
            retrieved_at="2026-11-08",
            publication_date="2025-01-15",
        )

    def test_valid_citation_passes(self):
        response = "ETFs are investment funds traded on exchanges. [1]"

        result = validate_citations(
            response,
            [self.valid_citation]
        )

        self.assertEqual(result.status, CitationStatus.PASS)

    def test_financial_information_without_citation_requires_review(self):
        response = "Stocks represent ownership in a company."

        result = validate_citations(response, [])

        self.assertEqual(result.status, CitationStatus.REVIEW)
        self.assertIn(
            "financial_information_without_citations",
            result.missing_citations
        )

    def test_unresolved_citation_id_requires_review(self):
        response = "ETFs are investment funds. [2]"

        result = validate_citations(
            response,
            [self.valid_citation]
        )

        self.assertEqual(result.status, CitationStatus.REVIEW)
        self.assertIn("2", result.unresolved_citation_ids)

    def test_invalid_url_requires_review(self):
        citation = Citation(
            citation_id="1",
            title="ETF Investor Bulletin",
            publisher="SEC",
            url="not-a-valid-url",
            supporting_text="ETFs are investment funds.",
            retrieved_at="2026-11-08",
        )

        result = validate_citations(
            "ETFs are investment funds. [1]",
            [citation]
        )

        self.assertEqual(result.status, CitationStatus.REVIEW)
        self.assertIn("invalid_url:1", result.invalid_citations)

    def test_missing_metadata_requires_review(self):
        citation = Citation(
            citation_id="1",
            title="",
            publisher="",
            url="https://example.com",
            supporting_text="Supporting information.",
            retrieved_at="",
        )

        result = validate_citations(
            "ETFs are investment funds. [1]",
            [citation]
        )

        self.assertEqual(result.status, CitationStatus.REVIEW)
        self.assertIn("missing_title:1", result.invalid_citations)
        self.assertIn("missing_publisher:1", result.invalid_citations)
        self.assertIn("missing_retrieval_date:1", result.invalid_citations)

    def test_empty_response_is_blocked(self):
        result = validate_citations("", [])

        self.assertEqual(result.status, CitationStatus.BLOCK)
        self.assertIn(
            "empty_or_invalid_response",
            result.invalid_citations
        )

    def test_nonfinancial_response_does_not_require_citation(self):
        response = "Hello! How can I help you today?"

        result = validate_citations(response, [])

        self.assertEqual(result.status, CitationStatus.PASS)
    
    def test_each_financial_claim_sentence_needs_its_own_citation(self):
        response = (
            "ETFs are investment funds traded on exchanges. [1] "
            "Stocks represent ownership in a corporation."
        )

        result = validate_citations(
            response,
            [self.valid_citation]
        )

        self.assertEqual(result.status, CitationStatus.REVIEW)


if __name__ == "__main__":
    unittest.main()