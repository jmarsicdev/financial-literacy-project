
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .governance_pipeline import (
    evaluate_request as evaluate_governance_request,
)


router = APIRouter(
    prefix="/governance",
    tags=["RAG Governance"],
)


class GovernanceRequestIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class SourceInfoOut(BaseModel):
    title: str
    publisher: str
    url: str


class GlossaryTermOut(BaseModel):
    term: str
    definition: str
    category: str
    aliases: list[str]
    source: SourceInfoOut


class IntentClassificationOut(BaseModel):
    intent: str
    confidence: float
    recommended_action: str
    risk_indicators: list[str]
    matched_rules: list[str]


class GovernanceRequestOut(BaseModel):
    classification: IntentClassificationOut
    glossary_terms: list[GlossaryTermOut]
    should_generate: bool
    generation_mode: str
    guidance: list[str]


@router.post(
    "/evaluate-request",
    response_model=GovernanceRequestOut,
)
def evaluate_request_endpoint(
    request: GovernanceRequestIn,
):
    result = evaluate_governance_request(request.query)

    classification = result.classification

    return GovernanceRequestOut(
        classification=IntentClassificationOut(
            intent=classification.intent.value,
            confidence=classification.confidence,
            recommended_action=classification.recommended_action.value,
            risk_indicators=classification.risk_indicators,
            matched_rules=classification.matched_rules,
        ),
        glossary_terms=[
            GlossaryTermOut(
                term=entry.term,
                definition=entry.definition,
                category=entry.category,
                aliases=list(entry.aliases),
                source=SourceInfoOut(
                    title=entry.source_title,
                    publisher=entry.source_publisher,
                    url=entry.source_url,
                ),
            )
            for entry in result.glossary_terms
        ],
        should_generate=result.should_generate,
        generation_mode=result.generation_mode.value,
        guidance=result.guidance,
    )
