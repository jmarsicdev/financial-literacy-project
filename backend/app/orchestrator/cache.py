# Redis cache for /ask answers. A repeated question is served from the stored answer instead of a new
# model call; the response says so (`cached`, `cached_at`). Only real model answers are stored: fallbacks,
# scripted replies and blocked answers are never cached. Fails open: Redis trouble means no caching.
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
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

    # --- demo answers shipped in the repository ---

    def raw(self, key: str) -> dict[str, Any] | None:
        """The stored payload (cached_at + response) for a key, or None."""
        try:
            value = self._conn().get(key)
            return json.loads(value) if value else None
        except Exception as exc:  # noqa: BLE001
            log.warning("ask cache read failed: %s", exc)
            return None

    def exists(self, key: str) -> bool:
        return self.raw(key) is not None

    def put_fixture(self, key: str, payload: dict[str, Any]) -> bool:
        """Store a shipped demo answer. No expiry: it is an explicit fixture, not a live cache entry."""
        try:
            self._conn().set(key, json.dumps(payload))
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("ask cache fixture write failed: %s", exc)
            return False


def dump_answers(cache: AskCache, queries: list[str], model: str, path: str) -> int:
    """Write the cached answers for these questions to a JSON file (questions without an entry are skipped)."""
    entries = []
    for query in queries:
        payload = cache.raw(cache_key(query, model, None))
        if payload:
            entries.append({"query": query, "cached_at": payload.get("cached_at", ""), "response": payload["response"]})
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"generated_with": model, "entries": entries}, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return len(entries)


def load_answers(cache: AskCache, path: str, model: str, *, replace: bool = False) -> int:
    """Load shipped answers into Redis under the configured model. Existing entries are kept unless replace."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    loaded = 0
    for entry in data.get("entries", []):
        query = entry.get("query") or ""
        response = entry.get("response")
        if not query.strip() or not isinstance(response, dict):
            continue
        try:
            AskResponse.model_validate(response)
        except ValueError as exc:
            log.warning("skipping unreadable demo answer for %r: %s", query, exc)
            continue
        key = cache_key(query, model, None)
        if not replace and cache.exists(key):
            continue
        if cache.put_fixture(key, {"cached_at": entry.get("cached_at", ""), "response": response}):
            loaded += 1
    return loaded


def seed_from_env(cache: AskCache, model: str) -> int:
    """Startup hook: load ASK_CACHE_SEED (a JSON file) if it is set and exists. Never raises."""
    path = (os.getenv("ASK_CACHE_SEED") or "").strip()
    if not path or not cache.enabled:
        return 0
    if not os.path.exists(path):
        log.warning("ASK_CACHE_SEED %s not found", path)
        return 0
    try:
        count = load_answers(cache, path, model)
    except Exception as exc:  # noqa: BLE001
        log.warning("ask cache seed failed: %s", exc)
        return 0
    if count:
        log.info("seeded %d demo answers from %s", count, path)
    return count


def main(argv: list[str]) -> int:
    """python -m app.orchestrator.cache dump FILE "question" [...]   |   load FILE [--replace]"""
    from .config import load_config

    if len(argv) < 2 or argv[0] not in ("dump", "load"):
        print(main.__doc__)
        return 2
    model = load_config().model
    cache = AskCache()
    if argv[0] == "dump":
        count = dump_answers(cache, argv[2:], model, argv[1])
        print(f"wrote {count} answers to {argv[1]} (model {model})")
    else:
        count = load_answers(cache, argv[1], model, replace="--replace" in argv[2:])
        print(f"loaded {count} answers from {argv[1]} under model {model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
