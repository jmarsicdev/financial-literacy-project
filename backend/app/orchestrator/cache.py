# Redis cache for /ask answers. A repeated question is served from the stored answer instead of a new
# model call; the response says so (`cached`, `cached_at`). Only real model answers are stored: fallbacks,
# scripted replies and blocked answers are never cached. Fails open: Redis trouble means no caching.
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Protocol

from .schemas import AskResponse

log = logging.getLogger("orchestrator.cache")

KEY_PREFIX = "ask:v1:"
DEFAULT_TTL_SECONDS = 24 * 3600


class CacheClient(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: str, ex: int | None = None) -> Any: ...


def _redis_client() -> CacheClient:
    import redis

    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


def ttl_from_env() -> int:
    raw = (os.getenv("ASK_CACHE_TTL_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_TTL_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def cache_key(query: str, model: str, top_k: int | None) -> str:
    normalized = " ".join(query.lower().split())
    digest = hashlib.sha256(f"{normalized}|{model}|{top_k or ''}".encode()).hexdigest()[:40]
    return KEY_PREFIX + digest


def is_cacheable(response: AskResponse) -> bool:
    return bool(response.generated) and response.governance.status in ("PASS", "REVIEW")


class AskCache:
    def __init__(self, client: CacheClient | None = None, ttl_seconds: int | None = None) -> None:
        self._client = client
        self.ttl_seconds = ttl_from_env() if ttl_seconds is None else ttl_seconds

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    def _conn(self) -> CacheClient:
        if self._client is None:
            self._client = _redis_client()
        return self._client

    def get(self, key: str) -> AskResponse | None:
        if not self.enabled:
            return None
        try:
            raw = self._conn().get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("ask cache read failed: %s", exc)
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
            response = AskResponse.model_validate(data["response"])
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("ask cache entry unreadable: %s", exc)
            return None
        response.cached = True
        response.cached_at = str(data.get("cached_at") or "")
        response.trace = None
        return response

    def set(self, key: str, response: AskResponse) -> bool:
        if not self.enabled or not is_cacheable(response):
            return False
        payload = {
            "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "response": response.model_dump(exclude={"trace", "cached", "cached_at"}),
        }
        try:
            self._conn().set(key, json.dumps(payload), ex=self.ttl_seconds)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("ask cache write failed: %s", exc)
            return False
