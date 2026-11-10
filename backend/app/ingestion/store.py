from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Protocol

from .models import PriceBar, SearchResult, TickerMetadata


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CachedPayload:
    id: int
    provider: str
    endpoint: str
    params: dict[str, Any]
    cache_key: str
    payload: Any
    status: str
    fetched_at: datetime


class PayloadStore(Protocol):
    def get_cached(self, provider: str, cache_key: str, max_age: timedelta | None = None) -> CachedPayload | None: ...
    def record(self, provider: str, endpoint: str, params: dict[str, Any], cache_key: str, payload: Any, status: str) -> int: ...
    def calls_within(self, provider: str, window: timedelta) -> int: ...
    def latest_payloads(self, provider: str, status: str = "ok") -> list[CachedPayload]: ...
    def upsert_price_bars(self, bars: Iterable[PriceBar]) -> int: ...
    def upsert_ticker_metadata(self, metadata: TickerMetadata) -> None: ...
    def upsert_search_results(self, results: Iterable[SearchResult]) -> int: ...
    def table_counts(self) -> dict[str, Any]: ...


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value, dumps=lambda obj: json.dumps(obj, default=str))


class PostgresStore:
    def __init__(self, connection_factory: Callable[[], Any] | None = None) -> None:
        if connection_factory is None:
            from ..db import get_connection

            connection_factory = get_connection
        self._connect = connection_factory

    # --- raw payloads ---

    def get_cached(self, provider: str, cache_key: str, max_age: timedelta | None = None) -> CachedPayload | None:
        sql = (
            "SELECT id, provider, endpoint, params, cache_key, payload, status, fetched_at "
            "FROM raw_payloads WHERE provider=%s AND cache_key=%s AND status='ok'"
        )
        args: list[Any] = [provider, cache_key]
        if max_age is not None:
            sql += " AND fetched_at >= now() - %s"
            args.append(max_age)
        sql += " ORDER BY fetched_at DESC, id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, args).fetchone()
        return self._row_to_payload(row) if row else None

    def record(self, provider: str, endpoint: str, params: dict[str, Any], cache_key: str, payload: Any, status: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO raw_payloads (provider, endpoint, params, cache_key, payload, status) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (provider, endpoint, _jsonb(params), cache_key, _jsonb(payload), status),
            ).fetchone()
        return int(row[0])

    def calls_within(self, provider: str, window: timedelta) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT count(*) FROM raw_payloads WHERE provider=%s AND fetched_at >= now() - %s",
                (provider, window),
            ).fetchone()
        return int(row[0])

    def latest_payloads(self, provider: str, status: str = "ok") -> list[CachedPayload]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ON (cache_key) id, provider, endpoint, params, cache_key, payload, status, fetched_at "
                "FROM raw_payloads WHERE provider=%s AND status=%s "
                "ORDER BY cache_key, fetched_at DESC, id DESC",
                (provider, status),
            ).fetchall()
        return [self._row_to_payload(r) for r in rows]

    @staticmethod
    def _row_to_payload(row: Any) -> CachedPayload:
        return CachedPayload(
            id=int(row[0]), provider=row[1], endpoint=row[2], params=row[3] or {},
            cache_key=row[4], payload=row[5], status=row[6], fetched_at=row[7],
        )

    # --- normalized tables ---

    def upsert_price_bars(self, bars: Iterable[PriceBar]) -> int:
        rows = [
            (b.symbol, b.bar_date, b.open, b.high, b.low, b.close, b.adjusted_close, b.volume, b.provider)
            for b in bars
        ]
        if not rows:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO price_bars (symbol,bar_date,open,high,low,close,adjusted_close,volume,provider) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (symbol,bar_date) DO UPDATE SET open=EXCLUDED.open, high=EXCLUDED.high, "
                    "low=EXCLUDED.low, close=EXCLUDED.close, adjusted_close=EXCLUDED.adjusted_close, "
                    "volume=EXCLUDED.volume, provider=EXCLUDED.provider, updated_at=now()",
                    rows,
                )
        return len(rows)

    def upsert_ticker_metadata(self, metadata: TickerMetadata) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ticker_metadata (symbol, company_name, sector, industry, exchange, market_cap, "
                "business_summary, provider) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (symbol) DO UPDATE SET company_name=EXCLUDED.company_name, sector=EXCLUDED.sector, "
                "industry=EXCLUDED.industry, exchange=EXCLUDED.exchange, market_cap=EXCLUDED.market_cap, "
                "business_summary=EXCLUDED.business_summary, provider=EXCLUDED.provider, updated_at=now()",
                (
                    metadata.symbol, metadata.company_name, metadata.sector, metadata.industry,
                    metadata.exchange, metadata.market_cap, metadata.business_summary, metadata.provider,
                ),
            )

    def upsert_search_results(self, results: Iterable[SearchResult]) -> int:
        rows = [
            (
                r.title, r.url, r.normalized_url, r.content, r.raw_content, r.source_domain,
                r.score, r.published_at, r.query_text, r.provider,
            )
            for r in results
        ]
        if not rows:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO search_results (title, url, normalized_url, content, raw_content, source_domain, "
                    "score, published_at, query_text, provider) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (normalized_url) DO UPDATE SET "
                    "title=EXCLUDED.title, "
                    "content=COALESCE(EXCLUDED.content, search_results.content), "
                    "raw_content=COALESCE(EXCLUDED.raw_content, search_results.raw_content), "
                    "score=COALESCE(EXCLUDED.score, search_results.score), "
                    "published_at=COALESCE(EXCLUDED.published_at, search_results.published_at), "
                    "query_text=EXCLUDED.query_text, fetched_at=now()",
                    rows,
                )
        return len(rows)

    def table_counts(self) -> dict[str, Any]:
        with self._connect() as conn:
            raw = conn.execute(
                "SELECT provider, status, count(*) FROM raw_payloads GROUP BY provider, status ORDER BY 1, 2"
            ).fetchall()
            bars = conn.execute("SELECT count(*), count(DISTINCT symbol) FROM price_bars").fetchone()
            meta = conn.execute("SELECT count(*) FROM ticker_metadata").fetchone()
            search = conn.execute(
                "SELECT count(*), count(published_at), count(DISTINCT source_domain) FROM search_results"
            ).fetchone()
        by_provider: dict[str, dict[str, int]] = {}
        for provider, status, count in raw:
            by_provider.setdefault(provider, {})[status] = int(count)
        return {
            "raw_payloads": by_provider,
            "price_bars": {"rows": int(bars[0]), "symbols": int(bars[1])},
            "ticker_metadata": {"rows": int(meta[0])},
            "search_results": {"rows": int(search[0]), "dated": int(search[1]), "domains": int(search[2])},
        }
