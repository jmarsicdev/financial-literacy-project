from unittest.mock import MagicMock

from app.semantic_search import service


def _fake_connection(rows):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = rows
    return conn


def test_semantic_search_joins_source_metadata(monkeypatch):
    rows = [
        {
            "id": 7,
            "title": "Understanding ETFs",
            "source_url": "https://www.sec.gov/example-etf",
            "chunk_text": "An ETF is an investment fund.",
            "metadata": {"source": "search_results", "search_result_id": 55},
            "source_domain": "sec.gov",
            "publisher": "sec.gov",
            "published_at": "2026-01-15T00:00:00+00:00",
            "fetched_at": "2026-11-08T12:00:00+00:00",
            "similarity": 0.91,
        }
    ]
    conn = _fake_connection(rows)
    monkeypatch.setattr(service, "get_connection", lambda: conn)
    monkeypatch.setattr(service, "embed_text", lambda text: [0.1, 0.2, 0.3])

    result = service.semantic_search("What is an ETF?", top_k=3)

    assert result == rows
    sql = conn.execute.call_args.args[0]
    assert "LEFT JOIN search_results" in sql
    assert "search_result_id" in sql
    for column in ("source_domain", "publisher", "published_at", "fetched_at"):
        assert column in sql
    assert conn.execute.call_args.args[1][2] == 3


def test_semantic_results_satisfy_governance_evidence_contract(monkeypatch):
    """A joined row produces an evidence chunk with no metadata warnings."""
    from app.rag_governance.evidence import build_semantic_context

    rows = [
        {
            "id": 7,
            "title": "Understanding ETFs",
            "source_url": "https://www.sec.gov/example-etf",
            "chunk_text": "An ETF is an investment fund.",
            "metadata": {"source": "search_results", "search_result_id": 55},
            "source_domain": "sec.gov",
            "publisher": "sec.gov",
            "published_at": "2026-01-15T00:00:00+00:00",
            "fetched_at": "2026-11-08T12:00:00+00:00",
            "similarity": 0.91,
        }
    ]
    monkeypatch.setattr(service, "get_connection", lambda: _fake_connection(rows))
    monkeypatch.setattr(service, "embed_text", lambda text: [0.1])

    context = build_semantic_context("What is an ETF?", service.semantic_search("What is an ETF?"))

    assert context.warnings == ()
    chunk = context.evidence_chunks[0]
    assert chunk.publisher == "sec.gov"
    assert chunk.retrieved_at.startswith("2026-11-08")
    assert chunk.publication_date.startswith("2026-01-15")
