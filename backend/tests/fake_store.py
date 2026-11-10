from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from app.ingestion.models import PriceBar, SearchResult, TickerMetadata
from app.ingestion.store import CachedPayload, utcnow


@dataclass
class InMemoryStore:
    clock: Callable[[], datetime] = utcnow
    payloads: list[CachedPayload] = field(default_factory=list)
    price_bars: dict[tuple[str, Any], PriceBar] = field(default_factory=dict)
    ticker_metadata: dict[str, TickerMetadata] = field(default_factory=dict)
    search_results: dict[str, SearchResult] = field(default_factory=dict)
    _next_id: int = 1

    def get_cached(self, provider: str, cache_key: str, max_age: timedelta | None = None) -> CachedPayload | None:
        cutoff = self.clock() - max_age if max_age is not None else None
        matches = [
            p for p in self.payloads
            if p.provider == provider and p.cache_key == cache_key and p.status == "ok"
            and (cutoff is None or p.fetched_at >= cutoff)
        ]
        return max(matches, key=lambda p: (p.fetched_at, p.id)) if matches else None

    def record(self, provider: str, endpoint: str, params: dict[str, Any], cache_key: str, payload: Any, status: str) -> int:
        entry = CachedPayload(
            id=self._next_id, provider=provider, endpoint=endpoint, params=dict(params), cache_key=cache_key,
            payload=json.loads(json.dumps(payload, default=str)),
            status=status, fetched_at=self.clock(),
        )
        self._next_id += 1
        self.payloads.append(entry)
        return entry.id

    def calls_within(self, provider: str, window: timedelta) -> int:
        cutoff = self.clock() - window
        return sum(1 for p in self.payloads if p.provider == provider and p.fetched_at >= cutoff)

    def latest_payloads(self, provider: str, status: str = "ok") -> list[CachedPayload]:
        latest: dict[str, CachedPayload] = {}
        for p in self.payloads:
            if p.provider == provider and p.status == status:
                current = latest.get(p.cache_key)
                if current is None or (p.fetched_at, p.id) > (current.fetched_at, current.id):
                    latest[p.cache_key] = p
        return sorted(latest.values(), key=lambda p: p.cache_key)

    def upsert_price_bars(self, bars: Iterable[PriceBar]) -> int:
        count = 0
        for bar in bars:
            self.price_bars[(bar.symbol, bar.bar_date)] = bar
            count += 1
        return count

    def upsert_ticker_metadata(self, metadata: TickerMetadata) -> None:
        self.ticker_metadata[metadata.symbol] = metadata

    def upsert_search_results(self, results: Iterable[SearchResult]) -> int:
        count = 0
        for result in results:
            self.search_results[result.normalized_url or f"__anon__{len(self.search_results)}"] = result
            count += 1
        return count

    def table_counts(self) -> dict[str, Any]:
        by_provider: dict[str, dict[str, int]] = {}
        for p in self.payloads:
            by_provider.setdefault(p.provider, {})
            by_provider[p.provider][p.status] = by_provider[p.provider].get(p.status, 0) + 1
        return {
            "raw_payloads": by_provider,
            "price_bars": {"rows": len(self.price_bars), "symbols": len({s for s, _ in self.price_bars})},
            "ticker_metadata": {"rows": len(self.ticker_metadata)},
            "search_results": {"rows": len(self.search_results)},
        }
