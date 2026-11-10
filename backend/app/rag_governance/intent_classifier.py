
import re

from .schemas import (
    Intent,
    IntentClassification,
    RecommendedAction,
)


# Each rule contains phrases or patterns that indicate a particular intent.
RULES = {
    "transactional": [
    r"^\s*(please\s+)?(buy|purchase|sell)\b.{0,50}\b(shares?|stocks?|etfs?|securities)\b",
    r"\b(buy|purchase|sell)\b.{0,50}\b(for me|on my behalf)\b",
    r"\b(can|could|would)\s+you\s+(please\s+)?(buy|purchase|sell)\b",
    r"\b(execute|place|submit)\b.{0,30}\b(trade|order|transaction)\b",
    r"\btrade\s+for\s+me\b",
    ],
    "personalized_advice": [
        r"\bshould\s+i\b.{0,60}\b(invest|buy|sell|hold|purchase)\b",
        r"\bshould\s+i\s+(buy|sell|hold)\b",
        r"\bwhat\s+should\s+i\s+invest\s+in\b",
        r"\bwhich\s+(stock|etf|fund|bond|crypto)\s+should\s+i\b",
        r"\bbest\s+investment\s+for\s+me\b",
        r"\bfor\s+my\s+(portfolio|retirement|savings)\b",
        r"\bhow\s+should\s+i\s+allocate\b",
        r"\binvest\s+\$?\d[\d,]*(?:\.\d+)?\b",
        r"\bguaranteed\s+(return|profit|investment)\b",
        r"\bwhich\s+one\b.{0,40}\bshould\s+i\s+(buy|sell|hold)\b",
        r"\b(which|what)\b.{0,50}\bshould\s+i\b.{0,30}\b(buy|sell|hold|invest)\b",
        r"\bwhich\s+one\s+i\s+should\s+(buy|sell|hold|invest)\b",
        r"\b(whether|if)\s+i\s+should\s+(buy|sell|hold|invest)\b",
        r"\b(good|right|suitable|appropriate)\s+investment\s+for\s+my\s+(situation|needs|goals|circumstances)\b",
        r"\b(fit|align with|match)\s+my\b.{0,50}\b(goals|needs|situation|circumstances)\b",
        r"\b(suitable|appropriate)\s+for\s+my\s+(risk\s+tolerance|financial\s+goals|investment\s+horizon|needs|situation|circumstances)\b",
    ],
    "market_information": [
        r"\b(stock|share|market)\s+price\b",
        r"\b(current|latest|today'?s?)\s+(stock|market|share)\b",
        r"\bmarket\s+(news|performance|update|trend)\b",
        r"\bhistorical\s+(stock|share|market)\s+performance\b",
        r"\bhow\s+did\b.{0,40}\b(stock|market|shares?)\b.{0,30}\b(today|yesterday)\b",
    ],
    "research": [
        r"\bcompare\b",
        r"\banaly[sz]e\b",
        r"\bresearch\b",
        r"\bpros\s+and\s+cons\b",
        r"\bperformance\s+of\b",
        r"\brisk\s+factors\b",
        r"\bfinancial\s+statements\b",
        r"\bvaluation\b",
    ],
    "educational": [
        r"\bwhat\s+is\b",
        r"\bwhat\s+are\b",
        r"\bexplain\b",
        r"\bdefine\b",
        r"\bmeaning\s+of\b",
        r"\bhow\s+does\b",
        r"\bhow\s+do\b",
        r"\bteach\s+me\b",
        r"\bhelp\s+me\s+understand\b",
        r"\bwhat\s+does\b",
    ],
}


def _matches(text: str, patterns: list[str]) -> bool:
    """Return True if any pattern matches the normalized query."""
    return any(re.search(pattern, text) for pattern in patterns)

def _is_negated_advice_request(text: str) -> bool:
    negation_patterns = [
        r"\bnot\s+asking\s+(whether|if)\b",
        r"\bnot\s+asking\s+you\s+to\b",
        r"\bdon't\s+ask\s+me\s+whether\b",
    ]

    return _matches(text, negation_patterns)

def _is_negated_transactional_request(text: str) -> bool:
    negation_patterns = [
        r"\bnot\s+asking\s+you\s+to\b.{0,40}\b(place|submit|execute)\b.{0,30}\b(order|trade|transaction)\b",
        r"\bnot\s+requesting\s+you\s+to\b.{0,40}\b(place|submit|execute)\b.{0,30}\b(order|trade|transaction)\b",
    ]

    return _matches(text, negation_patterns)

OUT_OF_SCOPE_RULES = [
    r"\b(weather|forecast|temperature|rain|snow)\b",
    r"\b(recipe|cooking|football|soccer|basketball)\b",
]

def classify_intent(query: str) -> IntentClassification:
    """
    Classify a financial-literacy query using transparent rules.

    The classifier returns one primary intent. When multiple intents
    are detected, the higher-risk intent takes priority.

    Confidence is a rule-based heuristic, not a calibrated probability.
    """

    if not isinstance(query, str) or not query.strip():
        return IntentClassification(
            intent=Intent.UNSUPPORTED_OR_UNCLEAR,
            confidence=1.0,
            recommended_action=RecommendedAction.CLARIFY,
            risk_indicators=["empty_or_invalid_query"],
            matched_rules=["empty_query"],
        )

    text = re.sub(r"\s+", " ", query.lower()).strip()
    
    if _matches(text, OUT_OF_SCOPE_RULES):
        return IntentClassification(
            intent=Intent.UNSUPPORTED_OR_UNCLEAR,
            confidence=0.95,
            recommended_action=RecommendedAction.CLARIFY,
            risk_indicators=["out_of_scope_request"],
            matched_rules=["out_of_scope"],
        )

    matched = {
        name
        for name, patterns in RULES.items()
        if _matches(text, patterns)
    }
    if "personalized_advice" in matched and _is_negated_advice_request(text):
        matched.remove("personalized_advice")
        
    if "transactional" in matched and _is_negated_transactional_request(text):
        matched.remove("transactional")

    risk_indicators = []

    if "transactional" in matched:
        risk_indicators.append("financial_transaction_request")

    if "personalized_advice" in matched:
        risk_indicators.append("personalized_financial_decision")

    if re.search(r"\$\s?\d| \d[\d,]*\s*(dollars?|usd)", text):
        risk_indicators.append("specific_monetary_amount")

    if re.search(r"\b(my|me|i am|i have|my family's)\b", text):
        risk_indicators.append("personal_context")

    if re.search(r"\b(guaranteed|risk[- ]?free|double|triple)\b", text):
        risk_indicators.append("unrealistic_return_expectation")

    # Higher-risk intents take precedence over lower-risk intents.
    if "transactional" in matched:
        intent = Intent.TRANSACTIONAL
        action = RecommendedAction.REJECT
        confidence = 0.95

    elif "personalized_advice" in matched:
        intent = Intent.PERSONALIZED_ADVICE
        action = RecommendedAction.RESTRICT_AND_REDIRECT
        confidence = 0.90

    elif "market_information" in matched:
        intent = Intent.MARKET_INFORMATION
        action = RecommendedAction.ALLOW_WITH_CAUTION
        confidence = 0.85

    elif "research" in matched:
        intent = Intent.RESEARCH
        action = RecommendedAction.ALLOW_WITH_CAUTION
        confidence = 0.85

    elif "educational" in matched:
        intent = Intent.EDUCATIONAL
        action = RecommendedAction.ALLOW
        confidence = 0.85

    else:
        intent = Intent.UNSUPPORTED_OR_UNCLEAR
        action = RecommendedAction.CLARIFY
        confidence = 0.50
        risk_indicators.append("no_supported_intent_detected")

    return IntentClassification(
        intent=intent,
        confidence=confidence,
        recommended_action=action,
        risk_indicators=sorted(set(risk_indicators)),
        matched_rules=sorted(matched),
    )
