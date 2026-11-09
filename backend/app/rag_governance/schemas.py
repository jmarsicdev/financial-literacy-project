
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Intent(str, Enum):
    EDUCATIONAL = "EDUCATIONAL"
    RESEARCH = "RESEARCH"
    MARKET_INFORMATION = "MARKET_INFORMATION"
    PERSONALIZED_ADVICE = "PERSONALIZED_ADVICE"
    TRANSACTIONAL = "TRANSACTIONAL"
    UNSUPPORTED_OR_UNCLEAR = "UNSUPPORTED_OR_UNCLEAR"


class RecommendedAction(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_WITH_CAUTION = "ALLOW_WITH_CAUTION"
    RESTRICT_AND_REDIRECT = "RESTRICT_AND_REDIRECT"
    REJECT = "REJECT"
    CLARIFY = "CLARIFY"


@dataclass
class IntentClassification:
    intent: Intent
    confidence: float
    recommended_action: RecommendedAction
    risk_indicators: List[str] = field(default_factory=list)
    matched_rules: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
