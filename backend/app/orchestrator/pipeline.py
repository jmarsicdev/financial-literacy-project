# govern request -> retrieve -> prompt -> generate -> govern response -> respond
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from ..rag_governance.evidence import RetrievalContext, RetrievalMode
from ..rag_governance.governance_pipeline import (
    GenerationMode,
    PipelineStatus,
    RequestGovernanceResult,
    ResponseGovernanceResult,
    evaluate_request,
    evaluate_response_with_context,
)
from ..rag_governance.schemas import Intent
from ..rag_governance.terminology import GlossaryEntry
from .config import OrchestratorConfig, load_config
from .generator import Generator, GeneratorError, StubGenerator, build_generator
from .prompting import build_messages
from .retrieval import RetrievalOutcome, Retriever
from .schemas import AskResponse, CitationOut, GlossaryOut, GovernanceOut, TraceStep

log = logging.getLogger("orchestrator")

TOP_K_BY_MODE = {
    GenerationMode.STANDARD: 3,
    GenerationMode.CITED_INFORMATION: 5,
    GenerationMode.SAFE_REDIRECT: 3,
}
FETCH_ON_MISS_MODES = {GenerationMode.CITED_INFORMATION}

SCRIPTED_TRANSACTIONAL = (
    "I can't place, submit, or execute trades or any other financial transaction. "
    "I can explain how buying or selling a security works, what order types mean, "
    "or what people commonly consider before trading. What would you like to understand?"
)
SCRIPTED_OUT_OF_SCOPE = (
    "That question is outside what this assistant covers. I can help with financial terms, "
    "how investment products work, market history, company information, and recent financial news."
)
SCRIPTED_CLARIFY = (
    "I'm not sure what you're asking. Could you rephrase it? For example: 'What is an ETF?', "
    "'How did NVDA perform this week?', or 'Compare index funds and ETFs.'"
)
FALLBACK_UNAVAILABLE = (
    "I couldn't generate a full answer right now. Here is what the SEC glossary says about the terms in your question."
)


class _Trace:
    def __init__(self) -> None:
        self.steps: list[TraceStep] = []

    def add(self, step: str, started: float, note: str = "") -> None:
        self.steps.append(TraceStep(step=step, ms=round((time.perf_counter() - started) * 1000, 1), note=note))


def glossary_rows(entries: list[GlossaryEntry]) -> list[dict[str, Any]]:
    """SEC glossary entries as numbered evidence, so definitional sentences can carry a citation."""
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for entry in entries:
        rows.append(
            {
                "id": f"glossary-{entry.term}",
                "title": f"{entry.term} ({entry.source_title})",
                "source_url": entry.source_url,
                "chunk_text": entry.definition,
                "publisher": entry.source_publisher,
                "source_domain": "investor.gov",
                "published_at": "",
                "fetched_at": now,
                "similarity": None,
                "metadata": {"source": "glossary", "category": entry.category},
            }
        )
    return rows


def record_search_history(query: str) -> None:
    from ..db import get_connection

    with get_connection() as conn:
        conn.execute("INSERT INTO search_history (query_text) VALUES (%s)", (query,))


class Orchestrator:
    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        *,
        retriever: Retriever | None = None,
        generator: Generator | None = None,
        govern_request: Callable[[str], RequestGovernanceResult] = evaluate_request,
        govern_response: Callable[[str, RetrievalContext], ResponseGovernanceResult] = evaluate_response_with_context,
        history: Callable[[str], None] | None = record_search_history,
    ) -> None:
        self.config = config or load_config()
        self.retriever = retriever or Retriever(self.config)
        self.generator = generator or StubGenerator()
        self._govern_request = govern_request
        self._govern_response = govern_response
        self._history = history

    # --- public ---

    def ask(self, query: str, *, top_k: int | None = None, debug: bool = False) -> AskResponse:
        trace = _Trace()
        query = " ".join(query.split())

        started = time.perf_counter()
        gov = self._govern_request(query)
        trace.add("govern_request", started, f"{gov.classification.intent.value} -> {gov.generation_mode.value}")
        glossary_out = [
            GlossaryOut(term=e.term, definition=e.definition, source_title=e.source_title, source_url=e.source_url)
            for e in gov.glossary_terms
        ]

        if not gov.should_generate:
            answer = self._scripted(gov)
            self._remember(query)
            return AskResponse(
                answer=answer,
                governance=self._governance_out(gov, "SKIPPED", []),
                glossary=glossary_out,
                generated=False,
                generator="none",
                trace=trace.steps if debug else None,
            )

        extra_reasons: list[str] = []
        mode = gov.generation_mode

        started = time.perf_counter()
        outcome = self._retrieve(query, gov, top_k)
        if outcome is None:
            extra_reasons.append("retrieval_failed")
            context = RetrievalContext(query=query, mode=RetrievalMode.UNKNOWN)
            trace.add("retrieve", started, "failed")
        else:
            context = outcome.context
            if not any(c.metadata.get("source") not in ("glossary",) for c in context.evidence_chunks):
                extra_reasons.append("no_evidence")
            trace.add(
                "retrieve", started,
                f"{len(context.evidence_chunks)} evidence rows; " + "; ".join(outcome.notes) if outcome.notes
                else f"{len(context.evidence_chunks)} evidence rows",
            )

        started = time.perf_counter()
        answer, generated, generator_name, gen_reason = self._generate(query, gov, context, strict=False)
        if gen_reason:
            extra_reasons.append(gen_reason)
        trace.add("generate", started, generator_name)

        started = time.perf_counter()
        result = self._govern_response(answer, context)
        note = result.status.value
        if result.status == PipelineStatus.BLOCK and generated:
            retry_started = time.perf_counter()
            retry_answer, retry_ok, _, retry_reason = self._generate(query, gov, context, strict=True)
            if retry_ok:
                retry_result = self._govern_response(retry_answer, context)
                if retry_result.status != PipelineStatus.BLOCK:
                    answer, result = retry_answer, retry_result
                    note = f"BLOCK -> retry {retry_result.status.value}"
                else:
                    answer = self._fallback_answer(gov, FALLBACK_UNAVAILABLE)
                    result = self._govern_response(answer, context)
                    result.status = PipelineStatus.BLOCK
                    extra_reasons.append("generation_blocked_twice")
                    generated = False
                    note = "BLOCK twice -> glossary fallback"
            else:
                extra_reasons.append(retry_reason or "generation_unavailable")
                answer = self._fallback_answer(gov, FALLBACK_UNAVAILABLE)
                result = self._govern_response(answer, context)
                generated = False
                note = "BLOCK -> retry failed -> glossary fallback"
            trace.add("regenerate", retry_started, note)
        trace.add("govern_response", started, note)

        status = result.status
        if extra_reasons and status == PipelineStatus.PASS:
            status = PipelineStatus.REVIEW
        reasons = sorted(set(list(result.reasons) + extra_reasons + self._detail_reasons(result)))

        self._remember(query)
        return AskResponse(
            answer=answer,
            citations=self._citations(context, result),
            governance=self._governance_out(gov, status.value, reasons),
            concepts=[c.name for c in context.ontology.concepts],
            glossary=glossary_out,
            generated=generated,
            generator=generator_name,
            trace=trace.steps if debug else None,
        )

    # --- steps ---

    def _retrieve(self, query: str, gov: RequestGovernanceResult, top_k: int | None) -> RetrievalOutcome | None:
        mode = gov.generation_mode
        try:
            return self.retriever.retrieve(
                query,
                top_k=top_k or TOP_K_BY_MODE.get(mode, self.config.top_k),
                fetch_on_miss=self.config.fetch_on_miss and mode in FETCH_ON_MISS_MODES,
                with_prices=mode in (GenerationMode.CITED_INFORMATION, GenerationMode.SAFE_REDIRECT),
                leading_rows=glossary_rows(gov.glossary_terms),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("retrieval failed: %s", exc)
            return None

    def _generate(
        self, query: str, gov: RequestGovernanceResult, context: RetrievalContext, *, strict: bool
    ) -> tuple[str, bool, str, str | None]:
        messages = build_messages(query, gov, context, strict=strict)
        try:
            text = self.generator.generate(messages, context=context, glossary=gov.glossary_terms)
            return text, True, self.generator.name, None
        except GeneratorError as exc:
            log.warning("generation failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("generator crashed: %s", exc)
        return self._fallback_answer(gov, FALLBACK_UNAVAILABLE), False, "fallback", "generation_unavailable"

    # --- helpers ---

    @staticmethod
    def _scripted(gov: RequestGovernanceResult) -> str:
        cls = gov.classification
        if cls.intent == Intent.TRANSACTIONAL:
            text = SCRIPTED_TRANSACTIONAL
        elif "out_of_scope_request" in cls.risk_indicators:
            text = SCRIPTED_OUT_OF_SCOPE
        else:
            text = SCRIPTED_CLARIFY
        if gov.glossary_terms:
            text += "\n\nTerms from your question:\n" + "\n".join(
                f"- {e.term}: {e.definition}" for e in gov.glossary_terms
            )
        return text

    @staticmethod
    def _fallback_answer(gov: RequestGovernanceResult, lead: str) -> str:
        if not gov.glossary_terms:
            return (
                "I couldn't generate an answer right now, and your question didn't match any glossary terms. "
                "Try asking about a specific financial term or company."
            )
        lines = [lead, ""]
        lines += [f"- {e.term}: {e.definition} (Source: {e.source_title}, {e.source_url})" for e in gov.glossary_terms]
        return "\n".join(lines)

    @staticmethod
    def _detail_reasons(result: ResponseGovernanceResult) -> list[str]:
        """Himaja's validators keep REVIEW details inside their own result objects; expose them."""
        reasons: list[str] = []
        cv = result.citation_validation
        reasons += [f"citation:{item}" for item in cv.missing_citations]
        reasons += [f"citation:unresolved_id:{item}" for item in cv.unresolved_citation_ids]
        reasons += [f"citation:{item}" for item in cv.invalid_citations]
        reasons += [f"guardrail:{item}" for item in result.guardrails.violations]
        return reasons

    @staticmethod
    def _governance_out(gov: RequestGovernanceResult, status: str, reasons: list[str]) -> GovernanceOut:
        cls = gov.classification
        return GovernanceOut(
            intent=cls.intent.value,
            action=cls.recommended_action.value,
            mode=gov.generation_mode.value,
            confidence=cls.confidence,
            status=status,
            reasons=reasons,
            risk_indicators=list(cls.risk_indicators),
            guidance=list(gov.guidance),
        )

    @staticmethod
    def _citations(context: RetrievalContext, result: ResponseGovernanceResult) -> list[CitationOut]:
        tiers = {check.citation_id: check.reliability.tier.value for check in result.source_checks}
        return [
            CitationOut(
                n=int(chunk.citation_id),
                title=chunk.title,
                url=chunk.source_url,
                publisher=chunk.publisher or chunk.source_domain,
                published_at=chunk.publication_date,
                retrieved_at=chunk.retrieved_at,
                tier=tiers.get(chunk.citation_id),
                cited=chunk.citation_id in tiers,
            )
            for chunk in context.evidence_chunks
        ]

    def _remember(self, query: str) -> None:
        if self._history is None:
            return
        try:
            self._history(query)
        except Exception as exc:  # noqa: BLE001
            log.warning("search_history write failed: %s", exc)


def build_orchestrator() -> Orchestrator:
    config = load_config()
    try:
        generator = build_generator(config)
    except GeneratorError as exc:
        log.warning("falling back to stub generator: %s", exc)
        generator = StubGenerator()
    return Orchestrator(config, retriever=Retriever(config), generator=generator)
