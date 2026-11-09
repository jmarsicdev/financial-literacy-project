
import re
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse


class CitationStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass
class Citation:
    citation_id: str
    title: str
    publisher: str
    url: str
    supporting_text: str
    retrieved_at: str = ""
    publication_date: str = ""


@dataclass
class CitationValidationResult:
    status: CitationStatus
    missing_citations: list[str] = field(default_factory=list)
    unresolved_citation_ids: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Financial topics that require citations in generated responses.
CITATION_REQUIRED_PATTERNS = [
    r"\b(stock|stocks|shares?|etfs?|mutual funds?)\b",
    r"\b(bonds?|securities|investments?|portfolios?)\b",
    r"\b(stock prices?|market prices?|returns?|yields?)\b",
    r"\b(interest rates?|inflation|market performance)\b",
    r"\b(revenue|earnings|profits?|market capitalization)\b",
    r"\b(financial statements?|dividends?|valuation)\b",
]


def _extract_citation_ids(response: str) -> list[str]:
    """Extract numeric citation markers such as [1] and [2]."""
    return re.findall(r"\[(\d+)\]", response)

def _split_sentences(response: str) -> list[str]:
    """
    Split sentences while keeping citations attached
    to the sentence they support.
    """

    # Move citation markers before sentence-ending punctuation,
    # without consuming the whitespace after the citation.
    normalized = re.sub(
        r"([.!?])((?:\s*\[\d+\])+)",
        lambda match: f" {match.group(2).strip()}{match.group(1)}",
        response,
    )

    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized)
        if sentence.strip()
    ]


def _requires_citations(response: str) -> bool:
    text = response.lower()

    return any(
        re.search(pattern, text)
        for pattern in CITATION_REQUIRED_PATTERNS
    )


def _valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
        )
    except (TypeError, ValueError):
        return False


def validate_citations(
    response: str,
    citations: list[Citation],
) -> CitationValidationResult:
    """
    Perform structural citation validation.

    This checks citation presence, source references, metadata,
    and URL structure. It does not semantically verify whether
    a source actually supports a generated claim.
    """

    if not isinstance(response, str) or not response.strip():
        return CitationValidationResult(
            status=CitationStatus.BLOCK,
            invalid_citations=["empty_or_invalid_response"],
        )

    if not isinstance(citations, list):
        return CitationValidationResult(
            status=CitationStatus.BLOCK,
            invalid_citations=["invalid_citation_collection"],
        )

    citation_ids = _extract_citation_ids(response)
    
    uncovered_claims = []

    if _requires_citations(response) and not citation_ids:
        return CitationValidationResult(
            status=CitationStatus.REVIEW,
            missing_citations=["financial_information_without_citations"],
        )
        
    

    if citation_ids:
        sentences = _split_sentences(response)

        for index, sentence in enumerate(sentences, start=1):
            if (
                _requires_citations(sentence)
                and not _extract_citation_ids(sentence)
            ):
                uncovered_claims.append(
                    f"financial_claim_without_citation:sentence_{index}"
                )

    citation_map = {}
    invalid = []

    for citation in citations:
        if not isinstance(citation, Citation):
            invalid.append("invalid_citation_object")
            continue

        if not citation.citation_id:
            invalid.append("missing_citation_id")
            continue

        if citation.citation_id in citation_map:
            invalid.append(
                f"duplicate_citation_id:{citation.citation_id}"
            )
            continue

        citation_map[citation.citation_id] = citation

    unresolved = []
    for citation_id in sorted(set(citation_ids)):
        if citation_id not in citation_map:
            unresolved.append(citation_id)

    for citation_id in sorted(set(citation_ids)):
        citation = citation_map.get(citation_id)

        if citation is None:
            continue

        if not citation.title.strip():
            invalid.append(f"missing_title:{citation_id}")

        if not citation.publisher.strip():
            invalid.append(f"missing_publisher:{citation_id}")

        if not _valid_url(citation.url):
            invalid.append(f"invalid_url:{citation_id}")

        if not citation.supporting_text.strip():
            invalid.append(f"missing_supporting_text:{citation_id}")

        if not citation.retrieved_at.strip():
            invalid.append(f"missing_retrieval_date:{citation_id}")

    warnings = []

    if citation_ids:
        warnings.append("citation_support_not_semantically_verified")

    if unresolved or invalid or uncovered_claims:
        return CitationValidationResult(
            status=CitationStatus.REVIEW,
            missing_citations=uncovered_claims,
            unresolved_citation_ids=unresolved,
            invalid_citations=sorted(set(invalid)),
            warnings=warnings,
        )

    return CitationValidationResult(
        status=CitationStatus.PASS,
        warnings=warnings,
    )

    return CitationValidationResult(
        status=CitationStatus.REVIEW,
        missing_citations=uncovered_claims,
        unresolved_citation_ids=unresolved,
        invalid_citations=sorted(set(invalid)),
        warnings=warnings,
    )
