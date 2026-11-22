# retrieval step: hybrid search -> dedup -> fetch-on-miss -> price context -> governance evidence contract
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from psycopg.rows import dict_row

from ..db import get_connection
from ..ingestion.dedup import normalize_title
from ..ingestion.tickers import DEFAULT_TICKERS
from ..rag_governance.evidence import RetrievalContext, build_hybrid_context
from ..rag_governance.source_reliability import SourceTier, classify_url
from .config import OrchestratorConfig

log = logging.getLogger("orchestrator.retrieval")

# uppercase tokens that look like tickers but are ordinary finance words
NOT_TICKERS = {
    "A", "I", "AI", "US", "USA", "USD", "ETF", "ETFS", "GDP", "SEC", "IPO", "CEO", "CFO",
    "EPS", "PE", "ROI", "ROE", "APR", "APY", "IRA", "CD", "CDS", "FED", "FOMC", "NYSE",
    "OK", "AND", "OR", "THE", "FOR", "VS", "FAQ", "LLC", "INC", "CPI", "PPI", "YTD", "ATH",
}
TICKER_PATTERN = re.compile(r"\$([A-Za-z]{1,5})\b|\b([A-Z]{2,5})\b")
WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z&.'-]{3,}")


@dataclass
class RetrievalOutcome:
    context: RetrievalContext
    hybrid: dict[str, Any]
    tickers: list[str] = field(default_factory=list)
    fetched_on_miss: bool = False
    notes: list[str] = field(default_factory=list)


def dedup_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop syndicated copies: same normalized title (ignoring a '| Publisher' suffix) or same url."""
    kept: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    for row in rows:
        title = str(row.get("title") or "").split(" | ")[0]
        key = normalize_title(title)
        url = str(row.get("source_url") or row.get("url") or "").strip().lower()
        if (key and key in seen_titles) or (url and url in seen_urls):
            continue
        if key:
            seen_titles.add(key)
        if url:
            seen_urls.add(url)
        kept.append(row)
    return kept


# policy 6.1: evidence comes from approved or reviewed sources first. Rank registered
# domains ahead of unknown ones and social platforms last; within a group keep the
# similarity order. Unregistered rows are still offered when nothing better exists and
# are still flagged by governance if the answer cites them.
TIER_RANK = {
    SourceTier.TIER_1: 0,
    SourceTier.TIER_2: 0,
    SourceTier.TIER_3: 0,
    SourceTier.UNCLASSIFIED: 1,
    SourceTier.TIER_4: 2,
    SourceTier.INVALID: 2,
}
CANDIDATE_MULTIPLIER = 3   # search this many times top_k, then keep the best-ranked top_k


def prefer_registered(rows: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Keep top_k rows, registered sources first, similarity order preserved within each group."""
    ranked = sorted(
        enumerate(rows),
        key=lambda item: (TIER_RANK.get(classify_url(item[1].get("source_url") or item[1].get("url") or ""), 1), item[0]),
    )
    return [row for _, row in ranked][:top_k]


def above_floor(rows: list[dict[str, Any]], floor: float) -> list[dict[str, Any]]:
    """Keep rows whose similarity clears the floor; rows without a score (glossary, prices) are kept."""
    kept = []
    for row in rows:
        score = row.get("similarity")
        if score is None:
            kept.append(row)
            continue
        try:
            if float(score) >= floor:
                kept.append(row)
        except (TypeError, ValueError):
            kept.append(row)
    return kept


def best_similarity(rows: list[dict[str, Any]]) -> float:
    scores = []
    for row in rows:
        try:
            scores.append(float(row.get("similarity")))
        except (TypeError, ValueError):
            continue
    return max(scores) if scores else 0.0


# --- ticker detection ---

def lookup_known_symbols(candidates: list[str]) -> set[str]:
    """Symbols we already hold data for."""
    if not candidates:
        return set()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT symbol FROM ticker_metadata WHERE symbol = ANY(%s) "
            "UNION SELECT DISTINCT symbol FROM price_bars WHERE symbol = ANY(%s)",
            (candidates, candidates),
        ).fetchall()
    return {r[0] for r in rows}


def lookup_symbols_by_company(words: list[str]) -> list[str]:
    """Map company-name words (e.g. 'Nvidia') to symbols via ticker_metadata."""
    if not words:
        return []
    found: list[str] = []
    with get_connection() as conn:
        for word in words:
            rows = conn.execute(
                "SELECT symbol FROM ticker_metadata WHERE company_name ILIKE %s ORDER BY symbol LIMIT 1",
                (f"%{word}%",),
            ).fetchall()
            found.extend(r[0] for r in rows)
    return found


def find_tickers(
    query: str,
    *,
    known_symbols: Callable[[list[str]], set[str]] = lookup_known_symbols,
    by_company: Callable[[list[str]], list[str]] = lookup_symbols_by_company,
    limit: int = 2,
) -> list[str]:
    explicit: list[str] = []      # $NVDA form, always trusted
    bare: list[str] = []          # NVDA form, must be a known symbol
    for dollar, upper in TICKER_PATTERN.findall(query):
        if dollar:
            explicit.append(dollar.upper())
        elif upper and upper not in NOT_TICKERS:
            bare.append(upper)

    ordered: list[str] = []
    for symbol in explicit:
        if symbol not in ordered:
            ordered.append(symbol)

    known = set(DEFAULT_TICKERS)
    try:
        known |= known_symbols(bare)
    except Exception as exc:  # noqa: BLE001
        log.warning("ticker lookup failed: %s", exc)
    for symbol in bare:
        if symbol in known and symbol not in ordered:
            ordered.append(symbol)

    if len(ordered) < limit:
        words = [w for w in WORD_PATTERN.findall(query) if w.upper() not in NOT_TICKERS and not w.isupper()]
        try:
            for symbol in by_company(words):
                if symbol not in ordered:
                    ordered.append(symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("company lookup failed: %s", exc)

    return ordered[:limit]


# --- price context ---

def load_recent_bars(symbol: str, limit: int = 5) -> list[dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = dict_row
        return conn.execute(
            "SELECT symbol, bar_date, close, adjusted_close, volume, provider, updated_at "
            "FROM price_bars WHERE symbol = %s ORDER BY bar_date DESC LIMIT %s",
            (symbol, limit),
        ).fetchall()


def price_context_row(symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One evidence row built from stored daily bars, so prices are cited like any other source."""
    if not bars:
        return None
    newest = bars[0]
    oldest = bars[-1]
    latest_close = float(newest["adjusted_close"])
    text = f"Latest stored close for {symbol}: {latest_close:.2f} on {newest['bar_date']}."
    if len(bars) > 1 and float(bars[1]["adjusted_close"]) > 0:
        day_change = (latest_close / float(bars[1]["adjusted_close"]) - 1) * 100
        text += f" That is {day_change:+.2f}% versus the previous close of {float(bars[1]['adjusted_close']):.2f} on {bars[1]['bar_date']}."
    lines = [f"{b['bar_date']}: adjusted close {float(b['adjusted_close']):.2f}" for b in bars]
    text += " Daily closes, newest first: " + "; ".join(lines) + "."
    if len(bars) > 1 and float(oldest["adjusted_close"]) > 0:
        change = (latest_close / float(oldest["adjusted_close"]) - 1) * 100
        text += f" Change from {oldest['bar_date']} to {newest['bar_date']}: {change:+.2f}%."
    provider = str(newest.get("provider") or "unknown")
    return {
        "id": f"price-{symbol}",
        "title": f"{symbol} daily price history",
        "source_url": f"https://finance.yahoo.com/quote/{symbol}/history/",
        "chunk_text": text,
        "publisher": provider,
        "source_domain": "finance.yahoo.com" if provider == "yfinance" else provider,
        "published_at": str(newest["bar_date"]),
        "fetched_at": str(newest.get("updated_at") or ""),
        "similarity": None,
        "metadata": {"source": "price_bars", "symbol": symbol, "bars": len(bars)},
    }


# --- risk profile context (Spark KMeans output) ---

def load_risk_profile(symbol: str) -> dict[str, Any] | None:
    from ..risk_profiles import get_symbol_profile

    return get_symbol_profile(symbol, history=1)


def quarter_label(quarter_start: Any) -> tuple[str, str]:
    """('2026 Q3', 'July 1 to September 30, 2026') for a quarter's first day."""
    from datetime import date, timedelta

    start = quarter_start if isinstance(quarter_start, date) else date.fromisoformat(str(quarter_start)[:10])
    next_month = start.month + 3
    next_start = date(start.year + (next_month > 12), (next_month - 1) % 12 + 1, 1)
    end = next_start - timedelta(days=1)
    span = f"{start.strftime('%B')} {start.day} to {end.strftime('%B')} {end.day}, {start.year}"
    return f"{start.year} Q{(start.month - 1) // 3 + 1}", span


def risk_profile_row(symbol: str, profile: dict[str, Any] | None, api_url: str) -> dict[str, Any] | None:
    """One evidence row describing a symbol's historical risk profile, phrased as past behavior only."""
    if not profile or not profile.get("latest"):
        return None
    latest = profile["latest"]
    quarter = str(latest["quarter_start"])
    label, span = quarter_label(latest["quarter_start"])
    benchmark = latest.get("benchmark") or "the benchmark"
    text = (
        f"Historical risk profile for {symbol} from this project's Spark clustering of past price behavior. "
        f"In {label} (the three months from {span}), {symbol} was in the '{latest['risk_profile']}' group "
        f"(group {int(latest['profile_rank']) + 1} of {int(latest['profile_count'])}, ordered from calmest): "
        f"annualized volatility {float(latest['annualized_volatility']) * 100:.1f}%, "
        f"largest drop within that quarter {float(latest['max_drawdown']) * 100:.1f}%, "
        f"beta versus {benchmark} {float(latest['beta_vs_benchmark']):.2f}."
    )
    mix = profile.get("profile_mix") or []
    if mix:
        shares = "; ".join(f"{m['pct_of_quarters']:.0f}% of quarters in '{m['risk_profile']}'" for m in mix)
        text += f" Across {profile.get('quarters_total')} quarters since {profile.get('first_quarter')}: {shares}."
    text += " This describes past price behavior only; it is not a forecast or a recommendation."
    return {
        "id": f"risk-profile-{symbol}",
        "title": f"{symbol} historical risk profile ({label})",
        "source_url": f"{api_url}/risk-profiles/{symbol}",
        "chunk_text": text,
        "publisher": "Team 5 Spark risk model",
        "source_domain": "team5-financial-literacy",
        "published_at": quarter,
        "fetched_at": str(latest.get("updated_at") or ""),
        "similarity": None,
        "metadata": {"source": "risk_profiles", "symbol": symbol},
    }


# --- the retriever ---

class Retriever:
    def __init__(
        self,
        config: OrchestratorConfig,
        *,
        search: Callable[[str, int], dict[str, Any]] | None = None,
        ingest_news: Callable[[str, int], Any] | None = None,
        index_news: Callable[[], int] | None = None,
        ingest_prices: Callable[[str], Any] | None = None,
        load_bars: Callable[[str, int], list[dict[str, Any]]] = load_recent_bars,
        find_tickers: Callable[[str], list[str]] = find_tickers,
        load_profile: Callable[[str], dict[str, Any] | None] = load_risk_profile,
    ) -> None:
        self.config = config
        self._search = search
        self._ingest_news = ingest_news
        self._index_news = index_news
        self._ingest_prices = ingest_prices
        self._load_bars = load_bars
        self._find_tickers = find_tickers
        self._load_profile = load_profile

    # lazy defaults keep import-time free of model/db work
    def search(self, query: str, top_k: int) -> dict[str, Any]:
        if self._search is None:
            from ..ontology.hybrid_search import hybrid_search
            self._search = hybrid_search
        return self._search(query, top_k)

    def ingest_news(self, query: str, days: int) -> Any:
        if self._ingest_news is None:
            from ..ingestion import Ingestor
            from ..ingestion.config import load_settings
            from ..ingestion.store import PostgresStore
            ingestor = Ingestor(PostgresStore(), load_settings())
            self._ingest_news = lambda q, d: ingestor.ingest_news(q, days=d)
        return self._ingest_news(query, days)

    def index_news(self) -> int:
        if self._index_news is None:
            from ..semantic_search.service import index_news
            self._index_news = index_news
        return self._index_news()

    def ingest_prices(self, symbol: str) -> Any:
        if self._ingest_prices is None:
            from ..ingestion import Ingestor
            from ..ingestion.config import load_settings
            from ..ingestion.store import PostgresStore
            ingestor = Ingestor(PostgresStore(), load_settings())
            self._ingest_prices = lambda s: ingestor.ingest_prices(s)
        return self._ingest_prices(symbol)

    def _select(self, hybrid: dict[str, Any], top_k: int) -> tuple[list[dict[str, Any]], int]:
        """Dedup, drop rows under the relevance floor, then keep the best-ranked top_k. Returns (rows, dropped)."""
        rows = dedup_results(list(hybrid.get("results") or []))
        kept = above_floor(rows, self.config.relevance_floor)
        return prefer_registered(kept, top_k), len(rows) - len(kept)

    def retrieve(self, query: str, *, top_k: int | None = None, fetch_on_miss: bool | None = None,
                 with_prices: bool = True, leading_rows: list[dict[str, Any]] | None = None) -> RetrievalOutcome:
        top_k = top_k or self.config.top_k
        fetch = self.config.fetch_on_miss if fetch_on_miss is None else fetch_on_miss
        notes: list[str] = []

        hybrid = self.search(query, top_k * CANDIDATE_MULTIPLIER)
        results, floor_dropped = self._select(hybrid, top_k)
        fetched = False

        thin = len(results) < 3 or best_similarity(results) < self.config.min_similarity
        if fetch and thin:
            try:
                ingest = self.ingest_news(query, self.config.fetch_days)
                status = getattr(ingest, "status", "unknown")
                notes.append(f"fetch_on_miss:{status}")
                if status in ("ok", "fallback"):
                    indexed = self.index_news()
                    notes.append(f"indexed:{indexed}")
                    hybrid = self.search(query, top_k * CANDIDATE_MULTIPLIER)
                    results, floor_dropped = self._select(hybrid, top_k)
                    fetched = True
            except Exception as exc:  # noqa: BLE001
                log.warning("fetch-on-miss failed: %s", exc)
                notes.append("fetch_on_miss:error")

        tickers: list[str] = []
        if with_prices:
            try:
                tickers = self._find_tickers(query)[: self.config.max_price_tickers]
            except Exception as exc:  # noqa: BLE001
                log.warning("ticker detection failed: %s", exc)
            for symbol in tickers:
                try:
                    self.ingest_prices(symbol)   # cache-first, only hits a provider when nothing is stored
                    row = price_context_row(symbol, self._load_bars(symbol, 5))
                except Exception as exc:  # noqa: BLE001
                    log.warning("price context for %s failed: %s", symbol, exc)
                    row = None
                if row:
                    results.append(row)
                    notes.append(f"price_context:{symbol}")
                try:
                    profile_row = risk_profile_row(symbol, self._load_profile(symbol), self.config.public_api_url)
                except Exception as exc:  # noqa: BLE001  (table may not exist until the Spark job has run)
                    log.warning("risk profile for %s unavailable: %s", symbol, exc)
                    profile_row = None
                if profile_row:
                    results.append(profile_row)
                    notes.append(f"risk_profile:{symbol}")

        if floor_dropped:
            notes.append(f"below_floor:{floor_dropped}")
        results = list(leading_rows or []) + results
        hybrid = {**hybrid, "results": results, "count": len(results)}
        context = build_hybrid_context(query, hybrid)
        return RetrievalOutcome(context=context, hybrid=hybrid, tickers=tickers, fetched_on_miss=fetched, notes=notes)
