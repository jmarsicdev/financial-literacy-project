
import re
from dataclasses import dataclass, field
from enum import Enum

from .evidence import RetrievalContext
from .schemas import IntentClassification, RecommendedAction
from .intent_classifier import classify_intent

from .financial_advice_guardrails import (
    GuardrailResult,
    GuardrailStatus,
    validate_generated_response,
)

from .citation_validator import (
    Citation,
    CitationValidationResult,
    CitationStatus,
    validate_citations,
)

from .source_reliability import (
    SourceMetadata,
    SourceReliabilityResult,
    SourceTier,
    evaluate_source_reliability,
)

from .terminology import GlossaryEntry, search_terms


class GenerationMode(str, Enum):
    STANDARD = "STANDARD"
    CITED_INFORMATION = "CITED_INFORMATION"
    SAFE_REDIRECT = "SAFE_REDIRECT"
    NO_GENERATION = "NO_GENERATION"


class PipelineStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass
class RequestGovernanceResult:
    classification: IntentClassification
    glossary_terms: list[GlossaryEntry] = field(default_factory=list)
    should_generate: bool = False
    generation_mode: GenerationMode = GenerationMode.NO_GENERATION
    guidance: list[str] = field(default_factory=list)


@dataclass
class SourceCheck:
    citation_id: str
    reliability: SourceReliabilityResult


@dataclass
class ResponseGovernanceResult:
    status: PipelineStatus
    guardrails: GuardrailResult
    citation_validation: CitationValidationResult
    source_checks: list[SourceCheck] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    retrieval_mode: str = "UNKNOWN"
    retrieval_warnings: list[str] = field(default_factory=list)
    ontology_concepts: list[str] = field(default_factory=list)


def evaluate_request(query: str) -> RequestGovernanceResult:
    """
    Perform pre-generation governance.

    Classify the request and identify relevant glossary terms.
    This function does not generate an answer.
    """

    classification = classify_intent(query)
    action = classification.recommended_action

    terms = search_terms(query) if isinstance(query, str) else []

    if action == RecommendedAction.ALLOW:
        return RequestGovernanceResult(
            classification=classification,
            glossary_terms=terms,
            should_generate=True,
            generation_mode=GenerationMode.STANDARD,
            guidance=[
                "Provide a clear, educational explanation.",
                "Avoid unsupported financial claims.",
            ],
        )

    if action == RecommendedAction.ALLOW_WITH_CAUTION:
        return RequestGovernanceResult(
            classification=classification,
            glossary_terms=terms,
            should_generate=True,
            generation_mode=GenerationMode.CITED_INFORMATION,
            guidance=[
                "Use reliable and relevant sources.",
                "Cite factual financial claims.",
                "Identify dates and data freshness where relevant.",
            ],
        )

    if action == RecommendedAction.RESTRICT_AND_REDIRECT:
        return RequestGovernanceResult(
            classification=classification,
            glossary_terms=terms,
            should_generate=True,
            generation_mode=GenerationMode.SAFE_REDIRECT,
            guidance=[
                "Do not provide a personalized buy, sell, or hold recommendation.",
                "Redirect to general educational information.",
                "Explain relevant risks and factors without deciding for the user.",
            ],
        )
    
    if action == RecommendedAction.REJECT:
        return RequestGovernanceResult(
            classification=classification,
            glossary_terms=terms,
            should_generate=False,
            generation_mode=GenerationMode.NO_GENERATION,
            guidance=[
                "Do not place, submit, or execute financial transactions.",
                "Clearly explain that the service cannot perform trades.",
                "Offer general financial education as an alternative.",
            ],
        )

    return RequestGovernanceResult(
        classification=classification,
        glossary_terms=terms,
        should_generate=False,
        generation_mode=GenerationMode.NO_GENERATION,
        guidance=[
            "Do not generate a financial answer for this request.",
            "Ask for clarification or explain the service's scope.",
        ],
    )


def evaluate_generated_response(
    response: str,
    citations: list[Citation],
) -> ResponseGovernanceResult:
    """
    Perform post-generation governance.

    Validate the response, its citation structure, and the reliability
    tier of sources referenced in the response.

    This does not prove that cited sources semantically support claims.
    """

    guardrail_result = validate_generated_response(response)

    citation_result = validate_citations(response, citations)

    source_checks = []
    reasons = []

    referenced_ids = (
        set(re.findall(r"\[(\d+)\]", response))
        if isinstance(response, str)
        else set()
    )

    citation_map = {
        citation.citation_id: citation
        for citation in citations
        if isinstance(citation, Citation)
    } if isinstance(citations, list) else {}

    for citation_id in sorted(referenced_ids):
        citation = citation_map.get(citation_id)

        if citation is None:
            continue

        source = SourceMetadata(
            source_id=citation.citation_id,
            title=citation.title or "",
            publisher=citation.publisher or "",
            url=citation.url or "",
        )

        reliability = evaluate_source_reliability(source)

        source_checks.append(
            SourceCheck(
                citation_id=citation_id,
                reliability=reliability,
            )
        )

        if reliability.tier == SourceTier.TIER_3:
            reasons.append(
                f"citation_{citation_id}:corroboration_recommended"
            )

        elif reliability.tier == SourceTier.TIER_4:
            reasons.append(
                f"citation_{citation_id}:user_generated_source"
            )

        elif reliability.tier == SourceTier.UNCLASSIFIED:
            reasons.append(
                f"citation_{citation_id}:source_requires_review"
            )

        elif reliability.tier == SourceTier.INVALID:
            reasons.append(
                f"citation_{citation_id}:invalid_source"
            )

    if guardrail_result.status == GuardrailStatus.BLOCK:
        reasons.append("response_guardrail_block")

    if citation_result.status == CitationStatus.BLOCK:
        reasons.append("citation_validation_block")

    if (
        guardrail_result.status == GuardrailStatus.BLOCK
        or citation_result.status == CitationStatus.BLOCK
    ):
        status = PipelineStatus.BLOCK

    elif (
        guardrail_result.status == GuardrailStatus.REVIEW
        or citation_result.status == CitationStatus.REVIEW
        or reasons
    ):
        status = PipelineStatus.REVIEW

    else:
        status = PipelineStatus.PASS

    return ResponseGovernanceResult(
        status=status,
        guardrails=guardrail_result,
        citation_validation=citation_result,
        source_checks=source_checks,
        reasons=sorted(set(reasons)),
    )


def evaluate_response_with_context(
    response: str,
    retrieval_context: RetrievalContext,
) -> ResponseGovernanceResult:
    """
    Validate a generated response using normalized semantic
    or ontology-enhanced retrieval evidence.
    """

    if not isinstance(retrieval_context, RetrievalContext):
        raise TypeError("retrieval_context must be a RetrievalContext")

    citations = retrieval_context.to_citations()

    result = evaluate_generated_response(
        response,
        citations,
    )

    result.retrieval_mode = retrieval_context.mode.value

    result.retrieval_warnings = list(
        retrieval_context.warnings
    )

    result.ontology_concepts = [
        concept.name
        for concept in retrieval_context.ontology.concepts
    ]

    if retrieval_context.warnings:
        result.reasons = sorted(
            set(result.reasons + ["retrieval_metadata_incomplete"])
        )

        if result.status == PipelineStatus.PASS:
            result.status = PipelineStatus.REVIEW

    return result
