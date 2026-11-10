from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    debug: bool = False


class CitationOut(BaseModel):
    n: int
    title: str
    url: str
    publisher: str
    published_at: str = ""
    retrieved_at: str = ""
    tier: str | None = None
    cited: bool = False


class GlossaryOut(BaseModel):
    term: str
    definition: str
    source_title: str
    source_url: str


class GovernanceOut(BaseModel):
    intent: str
    action: str
    mode: str
    confidence: float
    status: str                      # PASS | REVIEW | BLOCK | SKIPPED
    reasons: list[str] = Field(default_factory=list)
    risk_indicators: list[str] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)


class TraceStep(BaseModel):
    step: str
    ms: float
    note: str = ""


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut] = Field(default_factory=list)
    governance: GovernanceOut
    concepts: list[str] = Field(default_factory=list)
    glossary: list[GlossaryOut] = Field(default_factory=list)
    generated: bool = False
    generator: str = "none"
    trace: list[TraceStep] | None = None
