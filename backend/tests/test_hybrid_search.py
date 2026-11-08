
from app.ontology import hybrid_search as hybrid


def test_hybrid_search_with_ontology(monkeypatch):
    concepts = [
        {"id": 1, "name": "Inflation", "category": "Macroeconomics"}
    ]

    relationships = [
        {
            "source_name": "Inflation",
            "target_name": "Interest Rates",
            "relationship_type": "influences",
            "description": "Inflation can affect interest rates.",
        }
    ]

    queries = []

    def fake_semantic_search(query, top_k):
        queries.append(query)
        return [
            {"id": 1, "title": "Financial Article", "similarity": 0.8}
        ]

    monkeypatch.setattr(
        hybrid, "find_matching_concepts", lambda query: concepts
    )
    monkeypatch.setattr(
        hybrid, "get_related_concepts", lambda ids: relationships
    )
    monkeypatch.setattr(
        hybrid, "semantic_search", fake_semantic_search
    )

    result = hybrid.hybrid_search(
        "How does inflation affect investments?"
    )

    assert len(result["matched_concepts"]) == 1
    assert len(result["relationships"]) == 1
    assert "Interest Rates" in result["expanded_query"]
    assert len(result["results"]) == 1

    # Baseline search and expanded search both executed.
    assert len(queries) == 2
    assert queries[0] == "How does inflation affect investments?"


def test_hybrid_search_without_ontology(monkeypatch):
    queries = []

    monkeypatch.setattr(
        hybrid, "find_matching_concepts", lambda query: []
    )
    monkeypatch.setattr(
        hybrid, "get_related_concepts", lambda ids: []
    )

    def fake_search(query, top_k):
        queries.append(query)
        return [{"id": 2, "title": "General Financial Article"}]

    monkeypatch.setattr(
        hybrid, "semantic_search", fake_search
    )

    result = hybrid.hybrid_search(
        "What is happening in the stock market?"
    )

    assert result["matched_concepts"] == []
    assert result["relationships"] == []
    assert result["expanded_query"] == result["query"]
    assert result["results"] == result["baseline_results"]
    assert len(queries) == 1
