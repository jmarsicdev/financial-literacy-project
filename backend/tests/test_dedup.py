from datetime import datetime, timezone

import pytest

from app.ingestion import dedup
from app.ingestion.models import SearchResult


@pytest.mark.parametrize("a, b", [
    ("https://www.reuters.com/x/?utm_source=tw&utm_medium=s", "http://reuters.com/x"),
    ("https://Example.com/Path/", "https://example.com/Path"),
    ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
    ("https://example.com/a#section", "https://example.com/a"),
    ("https://example.com:443/a", "https://example.com/a"),
    ("example.com/a", "https://example.com/a"),
    ("https://example.com//a///b", "https://example.com/a/b"),
    ("https://example.com/a?fbclid=zzz&id=7", "https://example.com/a?id=7"),
])
def test_normalize_url_equivalences(a, b):
    assert dedup.normalize_url(a) == dedup.normalize_url(b)


def test_normalize_url_keeps_meaningful_differences():
    assert dedup.normalize_url("https://example.com/a?id=1") != dedup.normalize_url("https://example.com/a?id=2")
    assert dedup.normalize_url("https://example.com/a") != dedup.normalize_url("https://example.com/b")
    assert dedup.normalize_url("https://example.com:8080/a") != dedup.normalize_url("https://example.com/a")


def test_normalize_url_handles_empty():
    assert dedup.normalize_url(None) is None
    assert dedup.normalize_url("   ") is None


def test_source_domain():
    assert dedup.source_domain("https://www.cnbc.com/2026/x.html") == "cnbc.com"
    assert dedup.source_domain("finance.yahoo.com/news/a") == "finance.yahoo.com"
    assert dedup.source_domain(None) is None


def test_normalize_title():
    assert dedup.normalize_title("  Nvidia Posts RECORD Revenue!  ") == "nvidia posts record revenue"
    assert dedup.normalize_title(None) == ""


def _result(title, url, published=None):
    return SearchResult(
        title=title, url=url, normalized_url=dedup.normalize_url(url),
        published_at=published,
    )


def test_drop_duplicates_url_then_title_date():
    day = datetime(2026, 10, 20, 21, 5, tzinfo=timezone.utc)
    batch = [
        _result("Nvidia posts record revenue", "https://www.reuters.com/a?utm_source=x", day),
        _result("Nvidia posts record revenue", "http://reuters.com/a#c", day),            # same URL
        _result("NVIDIA POSTS RECORD REVENUE", "https://finance.yahoo.com/syndicated", day),  # same title+date
        _result("Nvidia posts record revenue", "https://cnbc.com/other", day.replace(day=21)),  # different date
        _result("Undated guide", "https://a.com/1"),
        _result("Undated guide", "https://b.com/2"),  # undated: never merged by title
    ]
    kept, reasons = dedup.drop_duplicates(batch)
    assert [r.url for r in kept] == [
        "https://www.reuters.com/a?utm_source=x",
        "https://cnbc.com/other",
        "https://a.com/1",
        "https://b.com/2",
    ]
    assert len(reasons) == 2
    assert reasons[0].startswith("duplicate url")
    assert reasons[1].startswith("duplicate title/date")
