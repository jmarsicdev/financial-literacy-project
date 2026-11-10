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
    lines = [f"{b['bar_date']}: adjusted close {float(b['adjusted_close']):.2f}" for b in bars]
    text = f"{symbol} daily closing prices from stored market data, newest first. " + "; ".join(lines) + "."
    if len(bars) > 1 and float(oldest["adjusted_close"]) > 0:
        change = (float(newest["adjusted_close"]) / float(oldest["adjusted_close"]) - 1) * 100
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
    ) -> None:
        self.config = config
        self._search = search
        self._ingest_news = ingest_news
        self._index_news = index_news
        self._ingest_prices = ingest_prices
        self._load_bars = load_bars
        self._find_tickers = find_tickers

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

    def retrieve(self, query: str, *, top_k: int | None = None, fetch_on_miss: bool | None = None,
                 with_prices: bool = True, leading_rows: list[dict[str, Any]] | None = None) -> RetrievalOutcome:
        top_k = top_k or self.config.top_k
        fetch = self.config.fetch_on_miss if fetch_on_miss is None else fetch_on_miss
        notes: list[str] = []

        hybrid = self.search(query, top_k)
        results = dedup_results(list(hybrid.get("results") or []))
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
                    hybrid = self.search(query, top_k)
                    results = dedup_results(list(hybrid.get("results") or []))
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

        dropped = len(results)
        results = above_floor(results, self.config.relevance_floor)
        dropped -= len(results)
        if dropped:
            notes.append(f"below_floor:{dropped}")
        results = list(leading_rows or []) + results
        hybrid = {**hybrid, "results": results, "count": len(results)}
        context = build_hybrid_context(query, hybrid)
        return RetrievalOutcome(context=context, hybrid=hybrid, tickers=tickers, fetched_on_miss=fetched, notes=notes)
