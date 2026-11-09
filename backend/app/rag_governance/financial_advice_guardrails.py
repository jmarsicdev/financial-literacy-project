
import re
from dataclasses import dataclass, field
from enum import Enum


class GuardrailStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass
class GuardrailResult:
    status: GuardrailStatus
    violations: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)


# These rules inspect generated responses, not user queries.
BLOCK_RULES = {
    "direct_investment_recommendation": [
        r"\b(you should|you ought to|i recommend you)\s+"
        r"(buy|sell|hold|purchase|invest in)\b",
        r"\bmy recommendation is to\s+"
        r"(buy|sell|hold|purchase|invest in)\b",
    ],
    "personalized_portfolio_allocation": [
        r"\b(allocate|put|invest)\s+\d+(?:\.\d+)?\s*%\s+"
        r"of your\s+(portfolio|savings|retirement account)\b",
    ],
    "guaranteed_or_risk_free_returns": [
        r"\bguaranteed\s+(returns?|profits?|gains?)\b",
        r"\brisk[- ]free\s+(investment|returns?|profits?)\b",
        r"\b(cannot|can't|will not)\s+lose\s+(money|principal)\b",
    ],
}

REVIEW_RULES = {
    "personalized_suitability_claim": [
        r"\b(this|that|the)\s+(stock|fund|investment|etf)\s+"
        r"is\s+(right|perfect|ideal|suitable|appropriate)\s+for you\b",
        r"\b(suitable|appropriate|right)\s+for your\s+"
        r"(risk tolerance|financial goals|situation|needs)\b",
    ],
}


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def validate_generated_response(response: str) -> GuardrailResult:
    """
    Inspect generated financial responses for potentially prohibited
    investment recommendations and unsupported financial claims.

    This is a rule-based first-pass validator, not a complete compliance
    or legal review.
    """

    if not isinstance(response, str) or not response.strip():
        return GuardrailResult(
            status=GuardrailStatus.BLOCK,
            violations=["empty_or_invalid_response"],
            matched_rules=["invalid_response"],
        )

    text = re.sub(r"\s+", " ", response.lower()).strip()

    blocked = [
        rule
        for rule, patterns in BLOCK_RULES.items()
        if _matches_any(text, patterns)
    ]

    requires_review = [
        rule
        for rule, patterns in REVIEW_RULES.items()
        if _matches_any(text, patterns)
    ]

    if blocked:
        return GuardrailResult(
            status=GuardrailStatus.BLOCK,
            violations=blocked,
            matched_rules=blocked + requires_review,
        )

    if requires_review:
        return GuardrailResult(
            status=GuardrailStatus.REVIEW,
            violations=requires_review,
            matched_rules=requires_review,
        )

    return GuardrailResult(
        status=GuardrailStatus.PASS,
    )
