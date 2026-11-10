
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    definition: str
    category: str
    aliases: tuple[str, ...]
    source_title: str
    source_publisher: str
    source_url: str


SEC_PUBLISHER = "U.S. Securities and Exchange Commission (SEC)"
SEC_GLOSSARY_URL = (
    "https://www.investor.gov/introduction-investing/"
    "investing-basics/glossary"
)

GLOSSARY = {
    "stock": GlossaryEntry(
        term="Stock",
        definition=(
            "A share of stock represents an ownership interest "
            "in a corporation. Its value can rise or fall."
        ),
        category="investment_products",
        aliases=("stocks", "share", "shares", "equity", "equities"),
        source_title="Investor.gov Glossary",
        source_publisher=SEC_PUBLISHER,
        source_url=SEC_GLOSSARY_URL,
    ),

    "bond": GlossaryEntry(
        term="Bond",
        definition=(
            "A bond is a debt security in which an investor lends "
            "money to an issuer for a specified period. The issuer "
            "agrees to repay principal and make payments according "
            "to the bond's terms."
        ),
        category="investment_products",
        aliases=("bonds", "debt security", "debt securities"),
        source_title="Investor.gov Glossary",
        source_publisher=SEC_PUBLISHER,
        source_url=SEC_GLOSSARY_URL,
    ),

    "etf": GlossaryEntry(
        term="Exchange-Traded Fund (ETF)",
        definition=(
            "An ETF pools money from investors and holds a portfolio "
            "of assets. ETF shares trade on securities exchanges "
            "at market prices during trading hours."
        ),
        category="investment_products",
        aliases=(
            "ETF",
            "ETFs",
            "exchange traded fund",
            "exchange traded funds",
        ),
        source_title="Exchange-Traded Funds (ETFs)",
        source_publisher=SEC_PUBLISHER,
        source_url=(
            "https://www.investor.gov/introduction-investing/"
            "investing-basics/investment-products/"
            "mutual-funds-and-exchange-traded-2"
        ),
    ),

    "mutual_fund": GlossaryEntry(
        term="Mutual Fund",
        definition=(
            "A mutual fund pools money from many investors and "
            "invests it in stocks, bonds, money-market instruments, "
            "or other assets. Each share represents part ownership "
            "of the fund's portfolio."
        ),
        category="investment_products",
        aliases=("mutual funds", "mutual fund shares"),
        source_title="Mutual Funds",
        source_publisher=SEC_PUBLISHER,
        source_url=(
            "https://www.investor.gov/introduction-investing/"
            "investing-basics/glossary/mutual-funds"
        ),
    ),

    "diversification": GlossaryEntry(
        term="Diversification",
        definition=(
            "Diversification means spreading investments across "
            "different assets, companies, or sectors rather than "
            "depending on a single investment. It can help reduce "
            "concentration risk, but does not eliminate investment risk."
        ),
        category="risk_management",
        aliases=("diversified", "portfolio diversification"),
        source_title="Diversification",
        source_publisher=SEC_PUBLISHER,
        source_url=(
            "https://www.investor.gov/introduction-investing/"
            "investing-basics/glossary/diversification"
        ),
    ),

    "expense_ratio": GlossaryEntry(
        term="Expense Ratio",
        definition=(
            "The expense ratio is the percentage of a fund's "
            "average net assets used each year to pay its operating "
            "expenses."
        ),
        category="fund_costs",
        aliases=(
            "expense ratios",
            "fund expense ratio",
            "fund expenses",
            "annual fund operating expenses",
        ),
        source_title="Expense Ratio",
        source_publisher=SEC_PUBLISHER,
        source_url=(
            "https://www.investor.gov/introduction-investing/"
            "investing-basics/glossary/expense-ratio"
        ),
    ),

    "dividend": GlossaryEntry(
        term="Dividend",
        definition=(
            "A dividend is a portion of a company's profit "
            "distributed to its shareholders. Not all companies "
            "pay dividends, and payment amounts or schedules can change."
        ),
        category="investment_returns",
        aliases=("dividends", "dividend payment", "dividend payments"),
        source_title="Investor.gov Glossary",
        source_publisher=SEC_PUBLISHER,
        source_url=SEC_GLOSSARY_URL,
    ),

    "capital_gain": GlossaryEntry(
        term="Capital Gain",
        definition=(
            "A capital gain is the profit that results when an "
            "investment is sold for more than the price paid for it."
        ),
        category="investment_returns",
        aliases=("capital gains", "investment gain", "realized gain"),
        source_title="Investor.gov Glossary",
        source_publisher=SEC_PUBLISHER,
        source_url=SEC_GLOSSARY_URL,
    ),

    "asset_allocation": GlossaryEntry(
        term="Asset Allocation",
        definition=(
            "Asset allocation means dividing investments among "
            "different asset classes, such as stocks, bonds, and cash."
        ),
        category="risk_management",
        aliases=("asset allocations", "allocation of assets"),
        source_title="Asset Allocation and Diversification",
        source_publisher=SEC_PUBLISHER,
        source_url=(
            "https://www.investor.gov/introduction-investing/"
            "getting-started/asset-allocation"
        ),
    ),

    "risk_tolerance": GlossaryEntry(
        term="Risk Tolerance",
        definition=(
            "Risk tolerance is an investor's ability and willingness "
            "to lose some or all of an investment in exchange for "
            "the possibility of greater returns."
        ),
        category="risk_management",
        aliases=("risk tolerances", "tolerance for risk"),
        source_title="Asset Allocation and Diversification",
        source_publisher=SEC_PUBLISHER,
        source_url=(
            "https://www.investor.gov/introduction-investing/"
            "getting-started/asset-allocation"
        ),
    ),

    "time_horizon": GlossaryEntry(
        term="Investment Time Horizon",
        definition=(
            "An investment time horizon is the length of time "
            "an investor expects to keep money invested before "
            "needing it for a financial goal."
        ),
        category="investment_planning",
        aliases=(
            "time horizon",
            "investment horizon",
            "investing timeframe",
            "investment timeframe",
        ),
        source_title="Asset Allocation and Diversification",
        source_publisher=SEC_PUBLISHER,
        source_url=(
            "https://www.investor.gov/introduction-investing/"
            "getting-started/asset-allocation"
        ),
    ),
}


def _normalize(text: str) -> str:
    """Normalize text for case-insensitive term matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", text.casefold())).strip()


def _build_alias_index() -> dict[str, str]:
    """Map each normalized term and alias to its glossary key."""
    index = {}

    for key, entry in GLOSSARY.items():
        names = (entry.term, *entry.aliases)

        for name in names:
            normalized = _normalize(name)

            existing = index.get(normalized)

            if existing is not None and existing != key:
                raise ValueError(
                    f"Duplicate glossary alias '{name}' "
                    f"used by '{existing}' and '{key}'."
                )

            index[normalized] = key

    return index


ALIAS_INDEX = _build_alias_index()


def get_term(query: str) -> GlossaryEntry | None:
    """
    Retrieve an exact glossary entry using its canonical term or alias.
    Example: get_term("ETFs")
    """
    if not isinstance(query, str) or not query.strip():
        return None

    key = ALIAS_INDEX.get(_normalize(query))

    return GLOSSARY.get(key) if key else None


def search_terms(
    query: str,
    limit: int = 10,
) -> list[GlossaryEntry]:
    """
    Find glossary entries mentioned in a natural-language query.

    Example: search_terms("Explain ETFs and mutual funds")
    """
    if not isinstance(query, str) or not query.strip():
        return []

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer.")

    normalized_query = _normalize(query)
    matches = []

    for key, entry in GLOSSARY.items():
        names = (entry.term, *entry.aliases)
        positions = []

        for name in names:
            normalized_name = _normalize(name)

            pattern = (
                r"(?<!\w)"
                + re.escape(normalized_name)
                + r"(?!\w)"
            )

            match = re.search(pattern, normalized_query)

            if match:
                positions.append(match.start())

        if positions:
            matches.append((min(positions), entry.term, entry))

    matches.sort(key=lambda item: (item[0], item[1]))

    return [entry for _, _, entry in matches[:limit]]


def list_terms(category: str | None = None) -> list[GlossaryEntry]:
    """
    Return all glossary entries, optionally filtered by category.
    """
    entries = list(GLOSSARY.values())

    if category is not None:
        if not isinstance(category, str):
            return []

        entries = [
            entry
            for entry in entries
            if entry.category.casefold() == category.casefold()
        ]

    return sorted(entries, key=lambda entry: entry.term.casefold())
