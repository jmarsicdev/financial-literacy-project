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


def test_market_information_uses_cited_mode_and_marks_news_for_review():
    retriever = FakeRetriever([NEWS_ROW])
    response = build(retriever).ask("What is the latest stock price news for NVDA?")

    assert response.governance.intent == "MARKET_INFORMATION"
    assert response.governance.mode == "CITED_INFORMATION"
    assert response.governance.status == "REVIEW"
    assert any(reason.endswith("source_requires_review") for reason in response.governance.reasons)
    call = retriever.calls[0]
    assert call["top_k"] == 5 and call["fetch_on_miss"] is True and call["with_prices"] is True
    assert response.citations[-1].tier == "UNCLASSIFIED"


def test_personalized_advice_is_redirected_not_refused():
    generator = FakeGenerator("Factors people commonly consider include time horizon and risk tolerance [1].")
    response = build(FakeRetriever([SEC_ROW]), generator).ask("Should I invest in NVDA for my retirement?")

    assert response.governance.intent == "PERSONALIZED_ADVICE"
    assert response.governance.mode == "SAFE_REDIRECT"
    assert response.generated
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


def test_no_document_evidence_is_flagged():
    response = build(FakeRetriever([])).ask("What is an ETF?")
    assert "no_evidence" in response.governance.reasons
    assert response.governance.status == "REVIEW"
    assert [c.n for c in response.citations] == [1]   # glossary only


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
