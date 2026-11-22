from app.orchestrator.config import OrchestratorConfig
from app.orchestrator.generator import GeneratorError, StubGenerator
from app.orchestrator.pipeline import Orchestrator
from app.orchestrator.retrieval import RetrievalOutcome
from app.rag_governance.evidence import build_hybrid_context

SEC_ROW = {
    "id": 101,
    "title": "Understanding Exchange-Traded Funds",
    "source_url": "https://www.sec.gov/example-etf",
    "chunk_text": "An ETF is an investment fund whose shares trade on a securities exchange. It holds a basket of assets.",
    "publisher": "U.S. Securities and Exchange Commission",
    "source_domain": "sec.gov",
    "published_at": "2025-01-15",
    "fetched_at": "2026-11-08T12:00:00+00:00",
    "similarity": 0.91,
    "metadata": {"source": "search_results", "search_result_id": 1},
}

NEWS_ROW = {
    "id": 202,
    "title": "Nvidia Earnings Are Coming Next Month",
    "source_url": "https://www.fool.com/investing/2026/10/22/nvidia-earnings/",
    "chunk_text": "Nvidia reports quarterly earnings next month and analysts expect record data center revenue.",
    "publisher": "fool.com",
    "source_domain": "fool.com",
    "published_at": "2026-10-22T10:00:00+00:00",
    "fetched_at": "2026-10-25T18:00:00+00:00",
    "similarity": 0.72,
    "metadata": {"source": "search_results", "search_result_id": 2},
}


class FakeRetriever:
    def __init__(self, rows=None, error=None):
        self.rows = list(rows or [])
        self.error = error
        self.calls = []

    def retrieve(self, query, *, top_k=None, fetch_on_miss=None, with_prices=True, leading_rows=None):
        self.calls.append(
            {"query": query, "top_k": top_k, "fetch_on_miss": fetch_on_miss,
             "with_prices": with_prices, "leading": len(leading_rows or [])}
        )
        if self.error:
            raise self.error
        results = list(leading_rows or []) + self.rows
        hybrid = {
            "query": query,
            "expanded_query": query,
            "matched_concepts": [{"id": 1, "name": "ETFs", "description": "", "category": "Investing"}] if self.rows else [],
            "relationships": [],
            "results": results,
        }
        return RetrievalOutcome(context=build_hybrid_context(query, hybrid), hybrid=hybrid, notes=["fake"])


class FakeGenerator:
    name = "fake"

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate(self, messages, *, context=None, glossary=None):
        self.calls.append(messages)
        item = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(item, Exception):
            raise item
        return item


def build(retriever=None, generator=None, history=None):
    return Orchestrator(
        OrchestratorConfig(provider="stub"),
        retriever=retriever or FakeRetriever(),
        generator=generator or StubGenerator(),
        history=history,
    )


def test_educational_question_with_authoritative_evidence_passes():
    retriever = FakeRetriever([SEC_ROW])
    response = build(retriever).ask("What is an ETF?")

    assert response.governance.intent == "EDUCATIONAL"
    assert response.governance.mode == "STANDARD"
    assert response.governance.status == "PASS", response.governance.reasons
    assert response.generated and response.generator == "stub"
    # glossary entry is prepended as numbered evidence, then the retrieved row
    assert [c.n for c in response.citations] == [1, 2]
    assert response.citations[0].url.startswith("https://www.investor.gov/")
    assert response.citations[0].tier == "TIER_1" and response.citations[0].cited
    assert response.citations[1].tier == "TIER_1"
    assert [g.term for g in response.glossary] == ["Exchange-Traded Fund (ETF)"]
    assert response.concepts == ["ETFs"]
    assert retriever.calls[0]["top_k"] == 3 and retriever.calls[0]["fetch_on_miss"] is False
    assert retriever.calls[0]["leading"] == 1

def test_retrieved_source_is_not_marked_cited_when_answer_has_no_marker():
    retriever = FakeRetriever([SEC_ROW])
    generator = FakeGenerator(
        "An ETF is an investment fund whose shares trade on an exchange."
    )

    response = build(retriever, generator).ask("What is an ETF?")

    assert response.governance.status == "REVIEW"
    assert response.citations
    assert all(not citation.cited for citation in response.citations)

    # Source reliability is independent of whether it was cited.
    assert all(citation.tier is None for citation in response.citations)

def test_missing_citations_are_repaired_on_retry():
    generator = FakeGenerator(
        "An ETF is an investment fund whose shares trade on an exchange.",
        "An ETF is an investment fund whose shares trade on an exchange [1].",
    )

    response = build(FakeRetriever([SEC_ROW]), generator).ask("What is an ETF?")

    assert len(generator.calls) == 2
    assert "citation" in generator.calls[1][0]["content"].lower()
    assert "[1]" in response.answer
    assert response.citations[0].cited
    assert response.governance.status == "PASS"


def test_citation_retry_preserves_review_when_citations_are_still_missing():
    generator = FakeGenerator(
        "An ETF is an investment fund whose shares trade on an exchange.",
        "An ETF is a fund traded on an exchange.",
    )

    response = build(FakeRetriever([SEC_ROW]), generator).ask("What is an ETF?")

    assert len(generator.calls) == 2
    assert response.governance.status == "REVIEW"
    assert not any(citation.cited for citation in response.citations)
    assert "[1]" not in response.answer


def test_market_information_uses_cited_mode_and_marks_news_only_answers_for_review():
    retriever = FakeRetriever([NEWS_ROW])
    response = build(retriever).ask("What is the latest stock price news for NVDA?")

    assert response.governance.intent == "MARKET_INFORMATION"
    assert response.governance.mode == "CITED_INFORMATION"
    assert response.governance.status == "REVIEW"
    assert any(reason.endswith("corroboration_recommended") for reason in response.governance.reasons)
    call = retriever.calls[0]
    assert call["top_k"] == 4 and call["fetch_on_miss"] is True and call["with_prices"] is True
    assert response.citations[-1].tier == "TIER_3"


def test_unregistered_news_domain_still_requires_review():
    row = {**NEWS_ROW, "source_url": "https://www.some-unknown-blog.net/nvda", "publisher": "some-unknown-blog.net",
           "source_domain": "some-unknown-blog.net"}
    response = build(FakeRetriever([row])).ask("What is the latest stock price news for NVDA?")

    assert response.governance.status == "REVIEW"
    assert any(reason.endswith("source_requires_review") for reason in response.governance.reasons)
    assert response.citations[-1].tier == "UNCLASSIFIED"


def test_news_anchored_by_price_and_risk_rows_passes():
    """The demo path: stored prices + Spark risk profile + an indexed article -> PASS with every row cited."""
    price_row = {
        "id": "price-NVDA",
        "title": "NVDA daily price history",
        "source_url": "https://finance.yahoo.com/quote/NVDA/history/",
        "chunk_text": "NVDA daily closing prices from stored market data, newest first. 2026-11-20: adjusted close 180.12.",
        "publisher": "yfinance",
        "source_domain": "finance.yahoo.com",
        "published_at": "2026-11-20",
        "fetched_at": "2026-11-21T01:00:00+00:00",
        "similarity": None,
        "metadata": {"source": "price_bars", "symbol": "NVDA", "bars": 5},
    }
    risk_row = {
        "id": "risk-profile-NVDA",
        "title": "NVDA historical risk profile (2026 Q3)",
        "source_url": "http://localhost:8000/risk-profiles/NVDA",
        "chunk_text": "Historical risk profile for NVDA. In 2026 Q3 NVDA was in the 'high volatility' group.",
        "publisher": "Team 5 Spark risk model",
        "source_domain": "team5-financial-literacy",
        "published_at": "2026-07-01",
        "fetched_at": "2026-11-21T01:00:00+00:00",
        "similarity": None,
        "metadata": {"source": "risk_profiles", "symbol": "NVDA"},
    }
    response = build(FakeRetriever([NEWS_ROW, price_row, risk_row])).ask("What is the current stock price trend for NVDA?")

    assert response.governance.status == "PASS", response.governance.reasons
    assert response.governance.reasons == []
    tiers = {c.title: c.tier for c in response.citations}
    assert tiers[NEWS_ROW["title"]] == "TIER_3"
    assert tiers[price_row["title"]] == "TIER_2" and tiers[risk_row["title"]] == "TIER_2"
    assert all(c.cited for c in response.citations)


def test_glossary_plus_news_alone_is_still_review():
    """A term definition is not corroboration for a market claim; only data or regulator sources anchor news."""
    response = build(FakeRetriever([NEWS_ROW])).ask("What is the latest stock price news for NVDA?")

    titles = {c.title: c.tier for c in response.citations}
    assert any(tier == "TIER_1" for tier in titles.values()), "glossary row should be present as Tier 1"
    assert response.governance.status == "REVIEW"
    assert response.governance.reasons == ["citation_2:corroboration_recommended"]


def test_personalized_advice_is_redirected_not_refused():
    generator = FakeGenerator("Factors people commonly consider include time horizon and risk tolerance [1].")
    response = build(FakeRetriever([SEC_ROW]), generator).ask("Should I invest in NVDA for my retirement?")

    assert response.governance.intent == "PERSONALIZED_ADVICE"
    assert response.governance.mode == "SAFE_REDIRECT"
    assert response.generated
    # planning definitions are always offered as SEC evidence in safe-redirect mode
    terms = [g.term for g in response.glossary]
    assert "Risk Tolerance" in terms and "Investment Time Horizon" in terms and "Diversification" in terms
    assert all(c.url.startswith("https://www.investor.gov/") for c in response.citations[: len(terms)])
    system_prompt = generator.calls[0][0]["content"]
    assert "safe redirect" in system_prompt.lower()
    assert "Do not give one" in system_prompt


def test_transactional_request_is_scripted_without_retrieval_or_generation():
    retriever = FakeRetriever([SEC_ROW])
    generator = FakeGenerator("should not be called")
    response = build(retriever, generator).ask("Buy 10 shares of NVDA for me")

    assert response.governance.intent == "TRANSACTIONAL"
    assert response.governance.status == "SKIPPED"
    assert not response.generated and response.generator == "none"
    assert "can't place" in response.answer
    assert retriever.calls == [] and generator.calls == []


def test_out_of_scope_request_asks_to_stay_in_scope():
    response = build().ask("What's the weather tomorrow in Charlotte?")
    assert response.governance.status == "SKIPPED"
    assert response.governance.action == "CLARIFY"
    assert "outside what this assistant covers" in response.answer


def test_generator_failure_falls_back_to_glossary():
    response = build(FakeRetriever([SEC_ROW]), FakeGenerator(GeneratorError("quota"))).ask("What is an ETF?")

    assert not response.generated and response.generator == "fallback"
    assert "generation_unavailable" in response.governance.reasons
    assert response.governance.status == "REVIEW"
    assert "Exchange-Traded Fund (ETF)" in response.answer


def test_blocked_draft_is_regenerated_once():
    generator = FakeGenerator(
        "You should buy NVDA now.",
        "An ETF is an investment fund whose shares trade on a securities exchange [1].",
    )
    response = build(FakeRetriever([SEC_ROW]), generator).ask("What is an ETF?", debug=True)

    assert response.governance.status != "BLOCK"
    assert len(generator.calls) == 2
    assert "previous draft was rejected" in generator.calls[1][0]["content"]
    assert any(step.step == "regenerate" for step in response.trace)
    assert response.answer.startswith("An ETF is an investment fund")


def test_blocked_twice_returns_fallback_with_block_status():
    generator = FakeGenerator("You should buy NVDA now.")
    response = build(FakeRetriever([SEC_ROW]), generator).ask("What is an ETF?")

    assert response.governance.status == "BLOCK"
    assert "generation_blocked_twice" in response.governance.reasons
    assert not response.generated
    assert "you should buy" not in response.answer.lower()


def test_retrieval_failure_is_reported_and_answer_still_returned():
    response = build(FakeRetriever(error=RuntimeError("db down"))).ask("What is an ETF?")

    assert "retrieval_failed" in response.governance.reasons
    assert response.governance.status in ("REVIEW", "BLOCK")
    assert response.citations == []
    assert response.answer


def test_glossary_only_evidence_is_still_evidence():
    response = build(FakeRetriever([])).ask("What is an ETF?")
    assert "no_evidence" not in response.governance.reasons
    assert [c.n for c in response.citations] == [1]   # the SEC glossary entry
    assert response.citations[0].tier == "TIER_1"


def test_no_evidence_at_all_is_flagged():
    response = build(FakeRetriever([])).ask("Explain how markets react to news")
    assert response.glossary == []
    assert response.citations == []
    assert "no_evidence" in response.governance.reasons
    assert response.governance.status in ("REVIEW", "BLOCK")


def test_trace_only_when_debug():
    plain = build(FakeRetriever([SEC_ROW])).ask("What is an ETF?")
    assert plain.trace is None
    traced = build(FakeRetriever([SEC_ROW])).ask("What is an ETF?", debug=True)
    assert [step.step for step in traced.trace] == ["govern_request", "retrieve", "generate", "govern_response"]


def test_history_hook_receives_normalized_query():
    seen = []
    build(FakeRetriever([SEC_ROW]), history=seen.append).ask("  What   is an ETF? ")
    assert seen == ["What is an ETF?"]


def test_history_failure_does_not_break_the_answer():
    def boom(query):
        raise RuntimeError("no db")

    response = build(FakeRetriever([SEC_ROW]), history=boom).ask("What is an ETF?")
    assert response.answer


def test_citation_repair_can_be_switched_off():
    generator = FakeGenerator("An ETF is an investment fund whose shares trade on an exchange.")
    orchestrator = Orchestrator(
        OrchestratorConfig(provider="stub", citation_repair=False),
        retriever=FakeRetriever([SEC_ROW]),
        generator=generator,
        history=None,
    )

    response = orchestrator.ask("What is an ETF?")

    assert len(generator.calls) == 1
    assert response.governance.status == "REVIEW"
