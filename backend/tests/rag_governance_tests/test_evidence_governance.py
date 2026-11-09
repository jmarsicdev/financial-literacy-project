
import unittest

from app.rag_governance.evidence import (
    build_semantic_context,
    build_hybrid_context,
)
from app.rag_governance.governance_pipeline import (
    PipelineStatus,
    evaluate_response_with_context,
)


class TestEvidenceGovernance(unittest.TestCase):

    def setUp(self):
        self.evidence = [
            {
                "id": 101,
                "title": "Understanding Exchange-Traded Funds",
                "source_url": "https://www.sec.gov/example-etf",
                "chunk_text": (
                    "An ETF is an investment fund whose shares "
                    "trade on a securities exchange."
                ),
                "publisher": "U.S. Securities and Exchange Commission",
                "source_domain": "sec.gov",
                "published_at": "2025-01-15",
                "fetched_at": "2026-11-08",
                "similarity": 0.91,
            }
        ]

        self.response = (
            "An ETF is an investment fund whose shares "
            "trade on a securities exchange. [1]"
        )

    def test_semantic_evidence_passes_governance(self):
        context = build_semantic_context(
            "What is an ETF?",
            self.evidence,
        )

        result = evaluate_response_with_context(
            self.response,
            context,
        )

        self.assertEqual(result.status, PipelineStatus.PASS)
        self.assertEqual(result.retrieval_mode, "SEMANTIC")
        self.assertEqual(len(result.source_checks), 1)

    def test_hybrid_evidence_preserves_ontology_context(self):
        hybrid_result = {
            "expanded_query": (
                "What is an ETF? Related financial concepts: ETFs"
            ),
            "matched_concepts": [
                {
                    "id": 1,
                    "name": "ETFs",
                    "description": "Exchange-traded funds.",
                    "category": "Investing",
                }
            ],
            "relationships": [
                {
                    "source_name": "ETFs",
                    "target_name": "Portfolio",
                    "relationship_type": "can_be_held_in",
                    "description": "ETFs can be held in portfolios.",
                }
            ],
            "results": self.evidence,
        }

        context = build_hybrid_context(
            "What is an ETF?",
            hybrid_result,
        )

        result = evaluate_response_with_context(
            self.response,
            context,
        )

        self.assertEqual(result.status, PipelineStatus.PASS)
        self.assertEqual(result.retrieval_mode, "HYBRID")
        self.assertIn("ETFs", result.ontology_concepts)

    def test_missing_source_metadata_requires_review(self):
        incomplete_evidence = [
            {
                "id": 101,
                "title": "Understanding ETFs",
                "source_url": "https://www.sec.gov/example-etf",
                "chunk_text": "ETFs are investment funds.",
                "similarity": 0.91,
            }
        ]

        context = build_semantic_context(
            "What is an ETF?",
            incomplete_evidence,
        )

        result = evaluate_response_with_context(
            "ETFs are investment funds. [1]",
            context,
        )

        self.assertEqual(result.status, PipelineStatus.REVIEW)
        self.assertIn(
            "retrieval_metadata_incomplete",
            result.reasons,
        )

    def test_ontology_without_document_evidence_requires_citation_review(self):
        hybrid_result = {
            "expanded_query": "Explain ETFs",
            "matched_concepts": [
                {
                    "id": 1,
                    "name": "ETFs",
                    "description": "Exchange-traded funds.",
                    "category": "Investing",
                }
            ],
            "relationships": [],
            "results": [],
        }

        context = build_hybrid_context(
            "Explain ETFs",
            hybrid_result,
        )

        result = evaluate_response_with_context(
            "ETFs are investment funds that trade on exchanges.",
            context,
        )

        self.assertEqual(result.status, PipelineStatus.REVIEW)
        self.assertIn("ETFs", result.ontology_concepts)
        self.assertEqual(len(result.source_checks), 0)

    def test_proposed_pr1_result_requires_metadata_review(self):
        actual_pr1_result = [
            {
                "id": 101,
                "title": "Understanding ETFs",
                "source_url": "https://www.sec.gov/example-etf",
                "chunk_text": "ETFs are investment funds.",
                "metadata": {
                    "source": "search_results",
                    "search_result_id": 55,
                },
                "similarity": 0.91,
            }
        ]

        context = build_semantic_context(
            "What is an ETF?",
            actual_pr1_result,
        )

        result = evaluate_response_with_context(
            "ETFs are investment funds. [1]",
            context,
        )

        self.assertEqual(result.status, PipelineStatus.REVIEW)

        self.assertIn(
            "result_1:missing_publisher",
            context.warnings,
        )

        self.assertIn(
            "result_1:missing_retrieval_date",
            context.warnings,
        )

        self.assertIn(
            "retrieval_metadata_incomplete",
            result.reasons,
        )


if __name__ == "__main__":
    unittest.main()
