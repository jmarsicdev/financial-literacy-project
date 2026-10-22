from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from .. import dedup
from ..models import SearchResult

PROVIDER = "tavily"
BASE_URL = "https://api.tavily.com/search"
ENDPOINT_SEARCH = "search"

PayloadStatus = Literal["ok", "rate_limited", "error", "invalid"]


@dataclass
class NormalizedSearch:
    results: list[SearchResult]
    rejected: list[str] = field(default_factory=list)
    undated: int = 0


def cache_key(query: str, topic: str = "news", days: int | None = 7, max_results: int = 10) -> str:
    normalized_query = " ".join(query.strip().lower().split())
    return f"{ENDPOINT_SEARCH}:{topic}:{days if topic == 'news' else '-'}:{max_results}:{normalized_query}"


def public_params(
    query: str,
    topic: str = "news",
    days: int | None = 7,
    max_results: int = 10,
    search_depth: str = "basic",
    include_raw_content: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "query": query.strip(),
        "topic": topic,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_raw_content": include_raw_content,
    }
    if topic == "news" and days:
        body["days"] = days
    return body


# --- fetch ---

def fetch_search(
    query: str,
    api_key: str,
    *,
    topic: str = "news",
    days: int | None = 7,
    max_results: int = 10,
    search_depth: str = "basic",
    include_raw_content: bool = False,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    body = public_params(query, topic, days, max_results, search_depth, include_raw_content)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if client is None:
        with httpx.Client(timeout=timeout) as owned:
            response = owned.post(BASE_URL, json=body, headers=headers)
    else:
        response = client.post(BASE_URL, json=body, headers=headers)
    if response.status_code == 429:
        return {"error": "rate_limited", "status_code": 429, "detail": response.text[:500]}
    response.raise_for_status()
    return response.json()


# --- classify ---

def classify(payload: Any) -> PayloadStatus:
    if not isinstance(payload, dict):
        return "invalid"
    if payload.get("error") == "rate_limited" or payload.get("status_code") == 429:
        return "rate_limited"
    if "error" in payload or ("detail" in payload and "results" not in payload):
        return "error"
    results = payload.get("results")
    if not isinstance(results, list):
        return "invalid"
    return "ok"


# --- normalize ---

def parse_published(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        iso = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(iso)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clamp_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score != score:
        return None
    return max(0.0, min(1.0, score))


def normalize_results(payload: dict[str, Any], query_text: str, provider: str = PROVIDER) -> NormalizedSearch:
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("payload has no 'results' list")

    out = NormalizedSearch(results=[])
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            out.rejected.append(f"#{index}: not an object")
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip() or None
        if not title:
            out.rejected.append(f"#{index}: missing title ({url or 'no url'})")
            continue
        published_at = parse_published(item.get("published_date"))
        if published_at is None:
            out.undated += 1
        try:
            record = SearchResult(
                title=title,
                url=url,
                normalized_url=dedup.normalize_url(url),
                content=(item.get("content") or None),
                raw_content=(item.get("raw_content") or None),
                source_domain=dedup.source_domain(url),
                score=_clamp_score(item.get("score")),
                published_at=published_at,
                query_text=query_text,
                provider=provider,
            )
        except ValidationError as exc:
            out.rejected.append(f"#{index}: " + "; ".join(e.get("msg", "invalid") for e in exc.errors()))
            continue
        out.results.append(record)
    return out
