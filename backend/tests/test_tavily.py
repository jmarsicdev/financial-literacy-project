from datetime import datetime, timezone

import pytest

from app.ingestion import dedup
from app.ingestion.providers import tavily


@pytest.mark.parametrize("raw, expected", [
    ("2026-10-20T21:05:00Z", "2026-10-20T21:05:00+00:00"),
    ("2026-10-20T21:05:00+00:00", "2026-10-20T21:05:00+00:00"),
    ("2026-10-19T13:00:00-04:00", "2026-10-19T17:00:00+00:00"),
    ("Tue, 20 Oct 2026 21:05:00 GMT", "2026-10-20T21:05:00+00:00"),
    ("2026-10-19", "2026-10-19T00:00:00+00:00"),
    (datetime(2026, 1, 1, 5, 0), "2026-01-01T05:00:00+00:00"),
])
def test_parse_published_formats(raw, expected):
    parsed = tavily.parse_published(raw)
    assert parsed.tzinfo is not None
    assert parsed.isoformat() == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "yesterday", 12345])
def test_parse_published_unparsable_is_none(raw):
    assert tavily.parse_published(raw) is None


def test_classify(tavily_news):
    assert tavily.classify(tavily_news) == "ok"
    assert tavily.classify({"error": "rate_limited", "status_code": 429}) == "rate_limited"
    assert tavily.classify({"detail": "Unauthorized"}) == "error"
    assert tavily.classify({"results": "nope"}) == "invalid"
    assert tavily.classify([]) == "invalid"


def test_normalize_results(tavily_news):
    out = tavily.normalize_results(tavily_news, "Nvidia earnings")
    # 6 raw items: one has no title and is rejected
    assert len(out.results) == 5
    assert len(out.rejected) == 1 and "missing title" in out.rejected[0]
    assert out.undated == 1

    first = out.results[0]
    assert first.source_domain == "reuters.com"
    assert first.normalized_url == "https://reuters.com/technology/nvidia-record-revenue-2026-10-20"
    assert first.published_at == datetime(2026, 10, 20, 21, 5, tzinfo=timezone.utc)
    assert first.query_text == "Nvidia earnings"
    assert first.provider == "tavily"

    # http/#fragment variant normalizes to the same URL as the first
    assert out.results[1].normalized_url == first.normalized_url

    # score above 1 is clamped, tracking params stripped
    amd = out.results[-1]
    assert amd.score == 1.0
    assert amd.normalized_url == "https://cnbc.com/2026/10/19/amd-instinct.html"
    assert amd.published_at.isoformat() == "2026-10-19T17:00:00+00:00"

    # undated row is kept with published_at None
    undated = next(r for r in out.results if not r.is_dated)
    assert undated.source_domain == "investopedia.com"
    assert undated.raw_content == "Long raw page content here."


def test_normalize_then_dedup(tavily_news):
    out = tavily.normalize_results(tavily_news, "q")
    kept, reasons = dedup.drop_duplicates(out.results)
    # reuters dup URL + yahoo syndicated title/date dropped -> 3 remain
    assert len(kept) == 3
    assert len(reasons) == 2


def test_cache_key_normalizes_query():
    assert tavily.cache_key("  Nvidia   Earnings ", "news", 7, 10) == "search:news:7:10:nvidia earnings"
    assert tavily.cache_key("x", "general", 7, 5) == "search:general:-:5:x"


def test_public_params_days_only_for_news():
    assert tavily.public_params("q", "news", 3, 5)["days"] == 3
    assert "days" not in tavily.public_params("q", "general", 3, 5)
