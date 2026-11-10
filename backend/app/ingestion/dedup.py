# TODO: fuzzy title match, check against existing search_results rows, canonical urls
from __future__ import annotations

import re
from datetime import date
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import SearchResult

TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid",
    "ref", "ref_src", "ref_url", "source", "cmpid", "ncid", "ocid",
    "_ga", "yclid", "s", "sr_share",
}

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def _is_tracking_param(name: str) -> bool:
    lowered = name.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PARAM_PREFIXES)


def normalize_url(url: str | None) -> str | None:
    if url is None:
        return None
    text = url.strip()
    if not text:
        return None
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return text.lower()

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return text.lower()

    port = parts.port
    if port and port not in (80, 443):
        host = f"{host}:{port}"

    path = re.sub(r"/{2,}", "/", parts.path or "")
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    if path == "/":
        path = ""

    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not _is_tracking_param(k)]
    kept.sort()
    query = urlencode(kept)

    return urlunsplit(("https", host, path, query, ""))


def source_domain(url: str | None) -> str | None:
    if not url:
        return None
    text = url.strip()
    if "://" not in text:
        text = "https://" + text
    try:
        host = (urlsplit(text).hostname or "").lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    lowered = _NON_ALNUM.sub(" ", title.lower())
    return _WHITESPACE.sub(" ", lowered).strip()


def title_date_key(result: SearchResult) -> tuple[str, date | None]:
    return normalize_title(result.title), result.published_date


def drop_duplicates(results: Iterable[SearchResult]) -> tuple[list[SearchResult], list[str]]:
    kept: list[SearchResult] = []
    reasons: list[str] = []
    seen_urls: set[str] = set()
    seen_title_dates: set[tuple[str, date]] = set()

    for result in results:
        url_key = result.normalized_url or normalize_url(result.url)
        if url_key:
            if url_key in seen_urls:
                reasons.append(f"duplicate url: {url_key}")
                continue
        title_key, published = title_date_key(result)
        if published is not None and title_key:
            td_key = (title_key, published)
            if td_key in seen_title_dates:
                reasons.append(f"duplicate title/date: {result.title!r} on {published}")
                continue
            seen_title_dates.add(td_key)
        if url_key:
            seen_urls.add(url_key)
        kept.append(result)
    return kept, reasons
