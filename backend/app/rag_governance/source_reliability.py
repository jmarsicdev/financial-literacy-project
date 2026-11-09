
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse


class SourceTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"
    UNCLASSIFIED = "UNCLASSIFIED"
    INVALID = "INVALID"


@dataclass
class SourceMetadata:
    source_id: str
    title: str
    publisher: str
    url: str


@dataclass
class SourceReliabilityResult:
    tier: SourceTier
    domain: str = ""
    matched_registry_domain: str = ""
    can_support_important_claims: bool = False
    guidance: str = ""
    warnings: list[str] = field(default_factory=list)


# Tier 1: Regulators and authoritative government sources.
TIER_1_DOMAINS = {
    "sec.gov",
    "investor.gov",
    "finra.org",
    "federalreserve.gov",
    "consumerfinance.gov",
    "cftc.gov",
    "occ.gov",
    "fdic.gov",
    "treasury.gov",
    "ftc.gov",
    "fincen.gov",
    "nasaa.org",
    "fred.stlouisfed.org",
}

# Tier 2: Official exchanges and government data providers.
TIER_2_DOMAINS = {
    "nasdaq.com",
    "nyse.com",
    "cboe.com",
    "bls.gov",
    "bea.gov",
    "data.gov",
    "worldbank.org",
    "imf.org",
}

# Tier 3: Established financial journalism and education.
TIER_3_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "marketwatch.com",
    "investopedia.com",
    "barrons.com",
    "apnews.com",
    "morningstar.com",
    "forbes.com",
}

# Tier 4: User-generated content and social platforms.
TIER_4_DOMAINS = {
    "reddit.com",
    "x.com",
    "twitter.com",
    "stocktwits.com",
    "medium.com",
    "substack.com",
    "facebook.com",
    "tiktok.com",
    "youtube.com",
    "quora.com",
}


def _matches_domain(host: str, trusted_domain: str) -> bool:
    """
    Match the exact domain or a legitimate subdomain.
    Avoid matching lookalike domains such as sec.gov.example.com.
    """
    return host == trusted_domain or host.endswith("." + trusted_domain)


def _classify_domain(host: str):
    registries = [
        (SourceTier.TIER_1, TIER_1_DOMAINS),
        (SourceTier.TIER_2, TIER_2_DOMAINS),
        (SourceTier.TIER_3, TIER_3_DOMAINS),
        (SourceTier.TIER_4, TIER_4_DOMAINS),
    ]

    for tier, domains in registries:
        for trusted_domain in domains:
            if _matches_domain(host, trusted_domain):
                return tier, trusted_domain

    # Academic domains are a broad category, not a guarantee
    # of the quality of an individual publication.
    if host.endswith(".edu"):
        return SourceTier.TIER_3, ".edu"

    return SourceTier.UNCLASSIFIED, ""


def evaluate_source_reliability(
    source: SourceMetadata,
) -> SourceReliabilityResult:
    """
    Classify a source using a maintained domain registry.

    Domain classification is an initial reliability signal.
    It does not verify the content, authorship, accuracy,
    independence, or relevance of an individual source.
    """

    if not isinstance(source, SourceMetadata):
        return SourceReliabilityResult(
            tier=SourceTier.INVALID,
            guidance="Invalid source metadata object.",
            warnings=["invalid_source_metadata"],
        )

    try:
        parsed = urlparse(source.url)
        host = parsed.hostname
    except (TypeError, ValueError):
        host = None
        parsed = None

    if (
        parsed is None
        or parsed.scheme.lower() not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
    ):
        return SourceReliabilityResult(
            tier=SourceTier.INVALID,
            guidance="Source URL must be a valid HTTP or HTTPS URL.",
            warnings=["invalid_or_unsafe_url"],
        )

    host = host.lower().rstrip(".")

    tier, matched_domain = _classify_domain(host)

    warnings = []

    if not source.title.strip():
        warnings.append("missing_source_title")

    if not source.publisher.strip():
        warnings.append("missing_publisher")

    if tier == SourceTier.TIER_1:
        guidance = (
            "Authoritative regulatory or government source. "
            "Suitable for supporting important factual claims "
            "within its subject area."
        )
        can_support = True

    elif tier == SourceTier.TIER_2:
        guidance = (
            "Official exchange or data source. "
            "Check the source's relevance and publication date "
            "before supporting important claims."
        )
        can_support = True

    elif tier == SourceTier.TIER_3:
        guidance = (
            "Established journalism, education, or academic source. "
            "Useful for context; corroborate important financial "
            "claims with primary or authoritative sources."
        )
        can_support = False
        warnings.append("corroboration_recommended")

    elif tier == SourceTier.TIER_4:
        guidance = (
            "User-generated or social content. "
            "Use for discovery or sentiment context only; "
            "do not rely on it as the sole support for important claims."
        )
        can_support = False
        warnings.append("user_generated_content")

    else:
        guidance = (
            "Source domain is not in the maintained reliability registry. "
            "Manual review is required before relying on it."
        )
        can_support = False
        warnings.append("unclassified_source_domain")

    return SourceReliabilityResult(
        tier=tier,
        domain=host,
        matched_registry_domain=matched_domain,
        can_support_important_claims=can_support,
        guidance=guidance,
        warnings=warnings,
    )
