
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .citation_validator import Citation


class RetrievalMode(str, Enum):
    SEMANTIC = "SEMANTIC"
    HYBRID = "HYBRID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EvidenceChunk:
    """A document passage returned by semantic or hybrid retrieval."""

    citation_id: str
    chunk_id: str
    title: str
    source_url: str
    supporting_text: str
    source_domain: str = ""
    publisher: str = ""
    publication_date: str = ""
    retrieved_at: str = ""
    similarity: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_citation(self) -> Citation:
        """Convert retrieved evidence into the existing citation schema."""
        return Citation(
            citation_id=self.citation_id,
            title=self.title,
            publisher=self.publisher,
            url=self.source_url,
            supporting_text=self.supporting_text,
            retrieved_at=self.retrieved_at,
            publication_date=self.publication_date,
        )


@dataclass(frozen=True)
class OntologyConcept:
    concept_id: str
    name: str
    description: str = ""
    category: str = ""


@dataclass(frozen=True)
class OntologyRelationship:
    source_name: str
    target_name: str
    relationship_type: str
    description: str = ""


@dataclass(frozen=True)
class OntologyContext:
    concepts: tuple[OntologyConcept, ...] = ()
    relationships: tuple[OntologyRelationship, ...] = ()


@dataclass(frozen=True)
class RetrievalContext:
    """Normalized retrieval output consumed by governance."""

    query: str
    mode: RetrievalMode
    evidence_chunks: tuple[EvidenceChunk, ...] = ()
    ontology: OntologyContext = field(default_factory=OntologyContext)
    expanded_query: str = ""
    warnings: tuple[str, ...] = ()

    def to_citations(self) -> list[Citation]:
        """Produce citations while preserving the evidence identifiers."""
        return [
            chunk.to_citation()
            for chunk in self.evidence_chunks
        ]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _source_domain(url: str) -> str:
    """Extract the hosting domain; this does not verify the publisher."""
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return ""


def _similarity(value: Any) -> float | None:
    if value is None:
        return None

    try:
        score = float(value)
    except (TypeError, ValueError):
        return None

    if not 0.0 <= score <= 1.0:
        return None

    return score


def _build_evidence_chunks(
    results: Sequence[Mapping[str, Any]],
) -> tuple[tuple[EvidenceChunk, ...], list[str]]:
    chunks = []
    warnings = []

    for index, raw_result in enumerate(results, start=1):
        row = _mapping(raw_result)
        metadata = dict(_mapping(row.get("metadata")))

        title = _text(row.get("title") or metadata.get("title"))
        source_url = _text(
            row.get("source_url")
            or row.get("url")
            or metadata.get("source_url")
        )
        supporting_text = _text(
            row.get("chunk_text")
            or row.get("supporting_text")
            or row.get("content")
        )

        if not supporting_text:
            warnings.append(f"result_{index}:missing_supporting_text")
            continue

        chunk_id = _text(
            row.get("id")
            or metadata.get("chunk_id")
            or metadata.get("search_result_id")
        ) or f"result-{index}"

        domain = _text(
            row.get("source_domain")
            or metadata.get("source_domain")
        ) or _source_domain(source_url)

        publisher = _text(
            row.get("publisher")
            or metadata.get("publisher")
        )

        publication_date = _text(
            row.get("published_at")
            or row.get("publication_date")
            or metadata.get("published_at")
            or metadata.get("publication_date")
        )

        retrieved_at = _text(
            row.get("retrieved_at")
            or row.get("fetched_at")
            or metadata.get("retrieved_at")
            or metadata.get("fetched_at")
        )

        if not title:
            warnings.append(f"result_{index}:missing_title")

        if not source_url:
            warnings.append(f"result_{index}:missing_source_url")

        if not publisher:
            warnings.append(f"result_{index}:missing_publisher")

        if not retrieved_at:
            warnings.append(f"result_{index}:missing_retrieval_date")

        chunks.append(
            EvidenceChunk(
                citation_id=str(len(chunks) + 1),
                chunk_id=chunk_id,
                title=title,
                source_url=source_url,
                supporting_text=supporting_text,
                source_domain=domain,
                publisher=publisher,
                publication_date=publication_date,
                retrieved_at=retrieved_at,
                similarity=_similarity(row.get("similarity")),
                metadata=metadata,
            )
        )

    return tuple(chunks), warnings


def _build_ontology_context(
    concepts: Sequence[Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
) -> OntologyContext:
    normalized_concepts = tuple(
        OntologyConcept(
            concept_id=_text(item.get("id")),
            name=_text(item.get("name")),
            description=_text(item.get("description")),
            category=_text(item.get("category")),
        )
        for raw in concepts
        if (item := _mapping(raw)).get("name")
    )

    normalized_relationships = tuple(
        OntologyRelationship(
            source_name=_text(item.get("source_name")),
            target_name=_text(item.get("target_name")),
            relationship_type=_text(item.get("relationship_type")),
            description=_text(item.get("description")),
        )
        for raw in relationships
        if (
            (item := _mapping(raw)).get("source_name")
            and item.get("target_name")
            and item.get("relationship_type")
        )
    )

    return OntologyContext(
        concepts=normalized_concepts,
        relationships=normalized_relationships,
    )


def build_semantic_context(
    query: str,
    results: Sequence[Mapping[str, Any]],
) -> RetrievalContext:
    """Adapt the team's semantic-search results into the evidence contract."""

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        raise ValueError("results must be a sequence of result objects")

    chunks, warnings = _build_evidence_chunks(results)

    return RetrievalContext(
        query=query.strip(),
        mode=RetrievalMode.SEMANTIC,
        evidence_chunks=chunks,
        warnings=tuple(warnings),
    )


def build_hybrid_context(
    query: str,
    hybrid_result: Mapping[str, Any],
) -> RetrievalContext:
    """
    Adapt the team's hybrid-search response.

    Expected keys:
      results, matched_concepts, relationships, expanded_query
    """

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    if not isinstance(hybrid_result, Mapping):
        raise ValueError("hybrid_result must be a mapping")

    results = hybrid_result.get("results", [])
    concepts = hybrid_result.get("matched_concepts", [])
    relationships = hybrid_result.get("relationships", [])

    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        raise ValueError("hybrid results must be a sequence")

    if not isinstance(concepts, Sequence) or isinstance(concepts, (str, bytes)):
        raise ValueError("matched_concepts must be a sequence")

    if not isinstance(relationships, Sequence) or isinstance(relationships, (str, bytes)):
        raise ValueError("relationships must be a sequence")

    chunks, warnings = _build_evidence_chunks(results)

    ontology = _build_ontology_context(concepts, relationships)

    return RetrievalContext(
        query=query.strip(),
        mode=RetrievalMode.HYBRID,
        evidence_chunks=chunks,
        ontology=ontology,
        expanded_query=_text(hybrid_result.get("expanded_query")),
        warnings=tuple(warnings),
    )
