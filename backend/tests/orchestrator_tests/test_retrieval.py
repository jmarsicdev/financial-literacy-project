from types import SimpleNamespace

from app.orchestrator.config import OrchestratorConfig
from app.orchestrator.retrieval import (
    Retriever,
    best_similarity,
    dedup_results,
    find_tickers,
    price_context_row,
)


def _row(title, url, similarity=0.7):
    return {
        "id": url,
        "title": title,
        "source_url": url,
        "chunk_text": f"{title}. Body text.",
        "publisher": "example.com",
        "source_domain": "example.com",
        "published_at": "2026-10-22T10:00:00+00:00",
        "fetched_at": "2026-10-25T18:00:00+00:00",
        "similarity": similarity,
        "metadata": {},
    }


def test_dedup_drops_syndicated_copies_and_repeated_urls():
    rows = [
        _row("Nvidia Earnings Are Coming Next Month", "https://fool.com/a"),
        _row("Nvidia Earnings Are Coming Next Month | The Motley Fool", "https://finance.yahoo.com/b"),
        _row("A different story", "https://fool.com/a"),
        _row("A different story", "https://cnbc.com/c"),
    ]
    kept = dedup_results(rows)
    assert [r["source_url"] for r in kept] == ["https://fool.com/a", "https://cnbc.com/c"]


def test_best_similarity_ignores_missing_scores():
    assert best_similarity([{"similarity": None}, {"similarity": "0.4"}, {"similarity": 0.6}]) == 0.6
    assert best_similarity([]) == 0.0


def test_find_tickers_explicit_known_and_company_name():
    no_db = {"known_symbols": lambda c: set(), "by_company": lambda w: []}
    assert find_tickers("Compare $nvda and AMD against an ETF", **no_db) == ["NVDA", "AMD"]
    assert find_tickers("What is an ETF?", **no_db) == []
    assert find_tickers("Tell me about XYZQ", known_symbols=lambda c: {"XYZQ"}, by_company=lambda w: []) == ["XYZQ"]

    def by_company(words):
        return ["NVDA"] if any(w.lower() == "nvidia" for w in words) else []

    assert find_tickers("How is Nvidia doing this quarter?", known_symbols=lambda c: set(), by_company=by_company) == ["NVDA"]
    assert find_tickers("$A $B $C", **no_db) == ["A", "B"]   # capped at two


def test_price_context_row_summarizes_recent_bars():
    bars = [
        {"symbol": "NVDA", "bar_date": "2026-10-23", "adjusted_close": 110.0, "provider": "yfinance", "updated_at": "2026-10-25T18:00:00+00:00"},
        {"symbol": "NVDA", "bar_date": "2026-10-22", "adjusted_close": 105.0, "provider": "yfinance", "updated_at": "2026-10-25T18:00:00+00:00"},
        {"symbol": "NVDA", "bar_date": "2026-10-21", "adjusted_close": 100.0, "provider": "yfinance", "updated_at": "2026-10-25T18:00:00+00:00"},
    ]
    row = price_context_row("NVDA", bars)
    assert row["title"] == "NVDA daily price history"
    assert row["publisher"] == "yfinance"
    assert "2026-10-23: adjusted close 110.00" in row["chunk_text"]
    assert "+10.00%" in row["chunk_text"]
    assert row["published_at"] == "2026-10-23" and row["fetched_at"].startswith("2026-10-25")
    assert price_context_row("NVDA", []) is None


class FakeSearch:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, query, top_k):
        self.calls.append((query, top_k))
        rows = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return {"query": query, "expanded_query": query, "matched_concepts": [], "relationships": [], "results": rows}


def _retriever(search, **overrides):
    defaults = dict(
        ingest_news=lambda q, d: SimpleNamespace(status="ok"),
        index_news=lambda: 3,
        ingest_prices=lambda s: SimpleNamespace(status="ok", source="cache"),
        load_bars=lambda s, n: [],
        find_tickers=lambda q: [],
    )
    defaults.update(overrides)
    return Retriever(OrchestratorConfig(provider="stub", min_similarity=0.45), search=search, **defaults)


def test_fetch_on_miss_triggers_when_results_are_thin():
    thin = [_row("Only one", "https://x.test/1", similarity=0.3)]
    rich = [_row(f"Story {i}", f"https://x.test/{i}", similarity=0.7) for i in range(4)]
    search = FakeSearch(thin, rich)
    ingested = []
    retriever = _retriever(search, ingest_news=lambda q, d: ingested.append((q, d)) or SimpleNamespace(status="ok"))

    outcome = retriever.retrieve("Nvidia earnings", fetch_on_miss=True, with_prices=False)

    assert outcome.fetched_on_miss is True
    assert len(search.calls) == 2
    assert ingested == [("Nvidia earnings", 30)]
    assert "fetch_on_miss:ok" in outcome.notes and "indexed:3" in outcome.notes
    assert len(outcome.context.evidence_chunks) == 4


def test_fetch_on_miss_respects_flag_and_skipped_ingest():
    thin = [_row("Only one", "https://x.test/1", similarity=0.3)]
    search = FakeSearch(thin)
    outcome = _retriever(search).retrieve("Nvidia earnings", fetch_on_miss=False, with_prices=False)
    assert outcome.fetched_on_miss is False and len(search.calls) == 1

    search = FakeSearch(thin)
    outcome = _retriever(search, ingest_news=lambda q, d: SimpleNamespace(status="skipped")).retrieve(
        "Nvidia earnings", fetch_on_miss=True, with_prices=False
    )
    assert outcome.fetched_on_miss is False and len(search.calls) == 1
    assert "fetch_on_miss:skipped" in outcome.notes


def test_fetch_on_miss_error_is_contained():
    def boom(q, d):
        raise RuntimeError("tavily down")

    search = FakeSearch([_row("Only one", "https://x.test/1", similarity=0.3)])
    outcome = _retriever(search, ingest_news=boom).retrieve("Nvidia earnings", fetch_on_miss=True, with_prices=False)
    assert "fetch_on_miss:error" in outcome.notes
    assert len(outcome.context.evidence_chunks) == 1


def test_leading_rows_come_first_and_price_context_last():
    rich = [_row(f"Story {i}", f"https://x.test/{i}", similarity=0.7) for i in range(3)]
    bars = [{"symbol": "NVDA", "bar_date": "2026-10-23", "adjusted_close": 110.0, "provider": "yfinance", "updated_at": "2026-10-25"}]
    retriever = _retriever(FakeSearch(rich), find_tickers=lambda q: ["NVDA"], load_bars=lambda s, n: bars)
    glossary = [_row("Stock (Investor.gov Glossary)", "https://www.investor.gov/glossary")]

    outcome = retriever.retrieve("How is NVDA stock doing?", fetch_on_miss=False, with_prices=True, leading_rows=glossary)

    titles = [c.title for c in outcome.context.evidence_chunks]
    assert titles[0] == "Stock (Investor.gov Glossary)"
    assert titles[-1] == "NVDA daily price history"
    assert outcome.tickers == ["NVDA"]
    assert "price_context:NVDA" in outcome.notes
    assert [c.citation_id for c in outcome.context.evidence_chunks] == ["1", "2", "3", "4", "5"]
