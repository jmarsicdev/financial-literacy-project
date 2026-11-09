
import unittest

from app.rag_governance.evidence import (
    RetrievalMode,
    build_semantic_context,
    build_hybrid_context,
)


class TestEvidence(unittest.TestCase):

    def setUp(self):
        # Shape returned by PR #1 semantic_search.service
        self.semantic_results = [
            {
                "id": 101,
                "title": "Understanding Exchange-Traded Funds",
                "source_url": "https://www.sec.gov/example-etf",
                "chunk_text": (
                    "An ETF is an investment fund whose shares "
                    "trade on an exchange."
                ),
                "metadata": {
                    "source": "search_results",
                    "search_result_id": 55,
                },
                "similarity": 0.91,
            }
        ]

        # Shape returned by PR #2 hybrid_search.hybrid_search
        self.hybrid_results = {
            "query": "How does inflation affect investments?",
            "expanded_query": (
                "How does inflation affect investments? "
                "Related financial concepts: Inflation, Interest Rates"
            ),
            "matched_concepts": [
                {
                    "id": 1,
                    "name": "Inflation",
                    "description": "A general increase in prices.",
                    "category": "Macroeconomics",
                }
            ],
            "relationships": [
                {
                    "source_name": "Inflation",
                    "target_name": "Interest Rates",
                    "relationship_type": "influences",
                    "description": (
                        "Inflation can influence central bank "
                        "interest rate decisions."
                    ),
                }
            ],
            "results": self.semantic_results,
            "count": 1,
        }

    def test_semantic_context_creation(self):
        result = build_semantic_context(
            "What is an ETF?",
            self.semantic_results,
        )

        self.assertEqual(result.mode, RetrievalMode.SEMANTIC)
        self.assertEqual(len(result.evidence_chunks), 1)
        self.assertEqual(
            result.evidence_chunks[0].title,
            "Understanding Exchange-Traded Funds",
        )

    def test_evidence_identifier_is_preserved(self):
        result = build_semantic_context(
            "What is an ETF?",
            self.semantic_results,
        )

        self.assertEqual(
            result.evidence_chunks[0].chunk_id,
            "101",
        )

    def test_similarity_score_is_preserved(self):
        result = build_semantic_context(
            "What is an ETF?",
            self.semantic_results,
        )

        self.assertEqual(
            result.evidence_chunks[0].similarity,
            0.91,
        )

    def test_semantic_metadata_gaps_generate_warnings(self):
        result = build_semantic_context(
            "What is an ETF?",
            self.semantic_results,
        )

        # PR #1's current semantic-search result does not
        # provide publisher or retrieval date.
        self.assertIn(
            "result_1:missing_publisher",
            result.warnings,
        )
        self.assertIn(
            "result_1:missing_retrieval_date",
            result.warnings,
        )

    def test_evidence_converts_to_citation(self):
        result = build_semantic_context(
            "What is an ETF?",
            self.semantic_results,
        )

        citations = result.to_citations()

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].citation_id, "1")
        self.assertEqual(
            citations[0].supporting_text,
            self.semantic_results[0]["chunk_text"],
        )
        self.assertEqual(
            citations[0].url,
            self.semantic_results[0]["source_url"],
        )

    def test_hybrid_context_creation(self):
        result = build_hybrid_context(
            "How does inflation affect investments?",
            self.hybrid_results,
        )

        self.assertEqual(result.mode, RetrievalMode.HYBRID)
        self.assertEqual(len(result.evidence_chunks), 1)
        self.assertEqual(
            result.expanded_query,
            self.hybrid_results["expanded_query"],
        )

    def test_hybrid_ontology_context_is_preserved(self):
        result = build_hybrid_context(
            "How does inflation affect investments?",
            self.hybrid_results,
        )

        self.assertEqual(len(result.ontology.concepts), 1)
        self.assertEqual(
            result.ontology.concepts[0].name,
            "Inflation",
        )

        self.assertEqual(len(result.ontology.relationships), 1)
        self.assertEqual(
            result.ontology.relationships[0].target_name,
            "Interest Rates",
        )

    def test_missing_supporting_text_is_skipped(self):
        results = [
            {
                "id": 1,
                "title": "Article without content",
                "source_url": "https://example.com/article",
                "chunk_text": "",
            }
        ]

        result = build_semantic_context("test query", results)

        self.assertEqual(len(result.evidence_chunks), 0)
        self.assertIn(
            "result_1:missing_supporting_text",
            result.warnings,
        )

    def test_invalid_query_is_rejected(self):
        with self.assertRaises(ValueError):
            build_semantic_context("", [])

        with self.assertRaises(ValueError):
            build_hybrid_context("   ", {})

    def test_invalid_similarity_is_not_preserved(self):
        results = [
            {
                "id": 1,
                "title": "Example",
                "source_url": "https://example.com/article",
                "chunk_text": "Example supporting text.",
                "similarity": 1.5,
            }
        ]

        result = build_semantic_context("test query", results)

        self.assertIsNone(result.evidence_chunks[0].similarity)


if __name__ == "__main__":
    unittest.main()
