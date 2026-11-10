# cache -> alpha vantage (only if a key is set and budget remains) -> yfinance
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Callable

import httpx

from . import dedup
from .config import Settings, load_settings
from .providers import alpha_vantage, tavily, yahoo
from .store import CachedPayload, PayloadStore

log = logging.getLogger("ingestion")

DEFAULT_NEWS_MAX_AGE = timedelta(hours=6)


@dataclass
class BudgetStatus:
    provider: str
    limit: int
    used: int
    window_hours: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "remaining": self.remaining}


@dataclass
class IngestResult:
    kind: str                 # prices | metadata | news | replay
    target: str               # symbol or query
    status: str               # ok | fallback | skipped | failed
    provider: str | None = None
    source: str = "none"      # cache | api | none
    records: int = 0
    rejected: int = 0
    duplicates: int = 0
    message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status in ("ok", "fallback")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Ingestor:
    def __init__(
        self,
        store: PayloadStore,
        settings: Settings | None = None,
        *,
        fetch_av: Callable[..., dict[str, Any]] | None = None,
        fetch_yf_history: Callable[..., dict[str, Any]] | None = None,
        fetch_yf_info: Callable[..., dict[str, Any]] | None = None,
        fetch_tavily: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.settings = settings or load_settings()
        self._fetch_av = fetch_av or alpha_vantage.fetch_daily
        self._fetch_yf_history = fetch_yf_history or yahoo.fetch_history
        self._fetch_yf_info = fetch_yf_info or yahoo.fetch_info
        self._fetch_tavily = fetch_tavily or tavily.fetch_search

    # --- budget ---

    def av_budget(self) -> BudgetStatus:
        window = timedelta(hours=self.settings.alpha_vantage_budget_window_hours)
        used = self.store.calls_within(alpha_vantage.PROVIDER, window)
        return BudgetStatus(
            provider=alpha_vantage.PROVIDER,
            limit=self.settings.alpha_vantage_daily_limit,
            used=used,
            window_hours=self.settings.alpha_vantage_budget_window_hours,
        )

    def plan_prices(self, symbols: list[str], refresh: bool = False, allow_fallback: bool = True) -> list[dict[str, str]]:
        remaining = self.av_budget().remaining
        has_key = bool(self.settings.alpha_vantage_api_key)
        plan: list[dict[str, str]] = []
        for raw in symbols:
            symbol = raw.strip().upper()
            action: str
            if not refresh and self.store.get_cached(alpha_vantage.PROVIDER, alpha_vantage.cache_key(symbol)):
                action = "cache:alpha_vantage"
            elif not refresh and self.store.get_cached(yahoo.PROVIDER, yahoo.cache_key_history(symbol)):
                action = "cache:yfinance"
            elif has_key and remaining > 0:
                action = "api:alpha_vantage"
                remaining -= 1
            elif allow_fallback:
                action = "api:yfinance (alpha_vantage budget exhausted)" if has_key else "api:yfinance"
            else:
                reason = "alpha_vantage budget exhausted" if has_key else "no alpha_vantage key"
                action = f"skip ({reason}, fallback disabled)"
            plan.append({"symbol": symbol, "action": action})
        return plan

    # --- price bars ---

    def ingest_prices(self, symbol: str, *, refresh: bool = False, allow_fallback: bool = True) -> IngestResult:
        symbol = symbol.strip().upper()
        if not refresh:
            cached = self.store.get_cached(alpha_vantage.PROVIDER, alpha_vantage.cache_key(symbol))
            if cached is not None:
                return self._load_av(cached.payload, symbol, source="cache")
            cached = self.store.get_cached(yahoo.PROVIDER, yahoo.cache_key_history(symbol))
            if cached is not None:
                return self._load_yf_history(cached.payload, symbol, source="cache", status="ok")

        notes: list[str] = []
        if self.settings.alpha_vantage_api_key:
            budget = self.av_budget()
            if budget.remaining > 0:
                status, payload = self._call_av(symbol)
                if status == "ok":
                    return self._load_av(payload, symbol, source="api")
                notes.append(f"alpha_vantage {status}")  # still counts against budget
                log.warning("%s: alpha_vantage returned %s", symbol, status)
            else:
                notes.append(f"alpha_vantage budget exhausted ({budget.used}/{budget.limit} in {budget.window_hours}h)")

        if not allow_fallback:
            return IngestResult("prices", symbol, "skipped", message="; ".join(notes) or "no ALPHA_VANTAGE_API_KEY")

        status, payload = self._call_yf_history(symbol)
        if status == "ok":
            return self._load_yf_history(payload, symbol, source="api", status="fallback" if notes else "ok", notes=notes)
        notes.append(f"yfinance {status}")
        return IngestResult("prices", symbol, "failed", provider=None, source="api", message="; ".join(notes))

    def _call_av(self, symbol: str) -> tuple[str, dict[str, Any]]:
        params = alpha_vantage.public_params(symbol, adjusted=True)
        try:
            payload = self._fetch_av(
                symbol, self.settings.alpha_vantage_api_key, adjusted=True,
                timeout=self.settings.request_timeout_seconds,
            )
            status = alpha_vantage.classify(payload, symbol)
        except (httpx.HTTPError, ValueError) as exc:
            payload = {"error": f"{type(exc).__name__}: {exc}"}
            status = "error"
        self.store.record(
            alpha_vantage.PROVIDER, params["function"], params, alpha_vantage.cache_key(symbol), payload, status,
        )
        return status, payload

    def _load_av(self, payload: dict[str, Any], symbol: str, *, source: str) -> IngestResult:
        try:
            normalized = alpha_vantage.normalize_daily(payload, symbol)
        except (alpha_vantage.SymbolMismatch, ValueError) as exc:
            return IngestResult("prices", symbol, "failed", alpha_vantage.PROVIDER, source, message=str(exc))
        count = self.store.upsert_price_bars(normalized.bars)
        message = "" if normalized.is_adjusted else "unadjusted series: adjusted_close = close"
        return IngestResult(
            "prices", symbol, "ok", alpha_vantage.PROVIDER, source,
            records=count, rejected=len(normalized.rejected), message=message,
        )

    def _call_yf_history(self, symbol: str) -> tuple[str, dict[str, Any]]:
        params = {"symbol": symbol, "period": "max"}
        try:
            payload = self._fetch_yf_history(symbol, period="max")
            status = yahoo.classify_history(payload)
        except Exception as exc:
            payload = {"error": f"{type(exc).__name__}: {exc}"}
            status = "error"
        self.store.record(yahoo.PROVIDER, yahoo.ENDPOINT_HISTORY, params, yahoo.cache_key_history(symbol), payload, status)
        return status, payload

    def _load_yf_history(
        self, payload: dict[str, Any], symbol: str, *, source: str, status: str, notes: list[str] | None = None,
    ) -> IngestResult:
        try:
            normalized = yahoo.normalize_history(payload, symbol)
        except ValueError as exc:
            return IngestResult("prices", symbol, "failed", yahoo.PROVIDER, source, message=str(exc))
        count = self.store.upsert_price_bars(normalized.bars)
        return IngestResult(
            "prices", symbol, status, yahoo.PROVIDER, source,
            records=count, rejected=len(normalized.rejected), message="; ".join(notes or []),
        )

    # --- ticker metadata ---

    def ingest_metadata(self, symbol: str, *, refresh: bool = False) -> IngestResult:
        symbol = symbol.strip().upper()
        key = yahoo.cache_key_info(symbol)
        source = "cache"
        payload: dict[str, Any] | None = None
        if not refresh:
            cached = self.store.get_cached(yahoo.PROVIDER, key)
            if cached is not None:
                payload = cached.payload
        if payload is None:
            source = "api"
            try:
                payload = self._fetch_yf_info(symbol)
                status = yahoo.classify_info(payload)
            except Exception as exc:
                payload = {"error": f"{type(exc).__name__}: {exc}"}
                status = "error"
            self.store.record(yahoo.PROVIDER, yahoo.ENDPOINT_INFO, {"symbol": symbol}, key, payload, status)
            if status != "ok":
                return IngestResult("metadata", symbol, "failed", yahoo.PROVIDER, source, message=f"yfinance {status}")
        metadata = yahoo.normalize_info(payload, symbol)
        self.store.upsert_ticker_metadata(metadata)
        return IngestResult("metadata", symbol, "ok", yahoo.PROVIDER, source, records=1)

    # --- news ---

    def ingest_news(
        self,
        query: str,
        *,
        topic: str = "news",
        days: int | None = 7,
        max_results: int = 10,
        refresh: bool = False,
        max_age: timedelta | None = DEFAULT_NEWS_MAX_AGE,
    ) -> IngestResult:
        query = " ".join(query.split())
        key = tavily.cache_key(query, topic, days, max_results)
        source = "cache"
        payload: dict[str, Any] | None = None
        if not refresh:
            cached = self.store.get_cached(tavily.PROVIDER, key, max_age)
            if cached is not None:
                payload = cached.payload
        if payload is None:
            if not self.settings.tavily_api_key:
                return IngestResult("news", query, "skipped", tavily.PROVIDER, message="no TAVILY_API_KEY")
            source = "api"
            params = tavily.public_params(query, topic, days, max_results)
            try:
                payload = self._fetch_tavily(
                    query, self.settings.tavily_api_key, topic=topic, days=days, max_results=max_results,
                    timeout=self.settings.request_timeout_seconds,
                )
                status = tavily.classify(payload)
            except (httpx.HTTPError, ValueError) as exc:
                payload = {"error": f"{type(exc).__name__}: {exc}"}
                status = "error"
            self.store.record(tavily.PROVIDER, tavily.ENDPOINT_SEARCH, params, key, payload, status)
            if status != "ok":
                return IngestResult("news", query, "failed", tavily.PROVIDER, source, message=f"tavily {status}")
        return self._load_tavily(payload, query, source=source)

    def _load_tavily(self, payload: dict[str, Any], query: str, *, source: str) -> IngestResult:
        try:
            normalized = tavily.normalize_results(payload, query)
        except ValueError as exc:
            return IngestResult("news", query, "failed", tavily.PROVIDER, source, message=str(exc))
        kept, dropped = dedup.drop_duplicates(normalized.results)
        for reason in dropped:
            log.info("%s: dropped %s", query, reason)
        count = self.store.upsert_search_results(kept)
        return IngestResult(
            "news", query, "ok", tavily.PROVIDER, source,
            records=count, rejected=len(normalized.rejected), duplicates=len(dropped),
            message=f"{normalized.undated} undated" if normalized.undated else "",
        )

    # --- replay, rebuild tables from raw_payloads with no api calls ---

    def replay(self) -> list[IngestResult]:
        results: list[IngestResult] = []
        for cached in self.store.latest_payloads(alpha_vantage.PROVIDER):
            results.append(self._replay_one(cached))
        for cached in self.store.latest_payloads(yahoo.PROVIDER):
            results.append(self._replay_one(cached))
        for cached in self.store.latest_payloads(tavily.PROVIDER):
            results.append(self._replay_one(cached))
        return results

    def _replay_one(self, cached: CachedPayload) -> IngestResult:
        params = cached.params or {}
        if cached.provider == alpha_vantage.PROVIDER:
            return self._load_av(cached.payload, params.get("symbol", "?"), source="cache")
        if cached.provider == yahoo.PROVIDER and cached.endpoint == yahoo.ENDPOINT_HISTORY:
            return self._load_yf_history(cached.payload, params.get("symbol", "?"), source="cache", status="ok")
        if cached.provider == yahoo.PROVIDER and cached.endpoint == yahoo.ENDPOINT_INFO:
            symbol = params.get("symbol", "?")
            metadata = yahoo.normalize_info(cached.payload, symbol)
            self.store.upsert_ticker_metadata(metadata)
            return IngestResult("metadata", symbol, "ok", yahoo.PROVIDER, "cache", records=1)
        if cached.provider == tavily.PROVIDER:
            return self._load_tavily(cached.payload, params.get("query", "?"), source="cache")
        return IngestResult("replay", cached.cache_key, "skipped", cached.provider, "cache", message="unknown endpoint")
