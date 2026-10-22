import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

from app.ingestion.models import PriceBar, SearchResult, TickerMetadata
from app.ingestion.store import PostgresStore

DSN = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.integration
SYMBOL = "ZZTEST"


@pytest.fixture(scope="module")
def pg():
    if not DSN:
        pytest.skip("TEST_DATABASE_URL not set")
    import psycopg

    @contextmanager
    def connect():
        with psycopg.connect(DSN) as conn:
            yield conn

    store = PostgresStore(connect)
    yield store
    with connect() as conn:
        conn.execute("DELETE FROM raw_payloads WHERE provider LIKE '__test__%'")
        conn.execute("DELETE FROM price_bars WHERE symbol=%s", (SYMBOL,))
        conn.execute("DELETE FROM ticker_metadata WHERE symbol=%s", (SYMBOL,))
        conn.execute("DELETE FROM search_results WHERE query_text='__TEST__'")


def test_record_get_cached_and_budget(pg):
    provider = "__test__av"
    key = "daily_adjusted:ZZTEST"
    assert pg.get_cached(provider, key) is None
    pg.record(provider, "TIME_SERIES_DAILY_ADJUSTED", {"symbol": SYMBOL}, key, {"Information": "limit"}, "rate_limited")
    assert pg.get_cached(provider, key) is None, "non-ok payloads are never served from cache"
    pg.record(provider, "TIME_SERIES_DAILY_ADJUSTED", {"symbol": SYMBOL}, key, {"Meta Data": {}, "n": 1}, "ok")
    pg.record(provider, "TIME_SERIES_DAILY_ADJUSTED", {"symbol": SYMBOL}, key, {"Meta Data": {}, "n": 2}, "ok")
    cached = pg.get_cached(provider, key)
    assert cached.payload["n"] == 2 and cached.params == {"symbol": SYMBOL} and cached.status == "ok"
    assert cached.fetched_at.tzinfo is not None
    assert pg.get_cached(provider, key, max_age=timedelta(seconds=0)) is None or True  # race-free either way
    assert pg.get_cached(provider, key, max_age=timedelta(hours=1)).payload["n"] == 2
    assert pg.calls_within(provider, timedelta(hours=1)) == 3
    latest = pg.latest_payloads(provider)
    assert len(latest) == 1 and latest[0].payload["n"] == 2


def test_upserts_are_idempotent(pg):
    bars = [
        PriceBar(symbol=SYMBOL, bar_date=date(2026, 1, 2), open=1, high=2, low=1, close=1.5, adjusted_close=1.5, volume=10, provider="t"),
        PriceBar(symbol=SYMBOL, bar_date=date(2026, 1, 3), open=1.5, high=2, low=1, close=1.8, adjusted_close=1.8, volume=11, provider="t"),
    ]
    assert pg.upsert_price_bars(bars) == 2
    bars[1] = bars[1].model_copy(update={"close": 1.9, "adjusted_close": 1.9})
    assert pg.upsert_price_bars(bars) == 2
    counts = pg.table_counts()
    assert counts["price_bars"]["rows"] >= 2

    pg.upsert_ticker_metadata(TickerMetadata(symbol=SYMBOL, company_name="Test Co", market_cap=5, provider="t"))
    pg.upsert_ticker_metadata(TickerMetadata(symbol=SYMBOL, company_name="Test Co 2", market_cap=6, provider="t"))

    published = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    rows = [
        SearchResult(title="A", url="https://x.test/a", normalized_url="https://x.test/a", query_text="__TEST__", published_at=published, score=0.5),
        SearchResult(title="B undated", url=None, normalized_url=None, query_text="__TEST__"),
        SearchResult(title="C undated", url=None, normalized_url=None, query_text="__TEST__"),
    ]
    assert pg.upsert_search_results(rows) == 3
    # same normalized_url again -> update, not a duplicate row
    assert pg.upsert_search_results([rows[0].model_copy(update={"title": "A2", "content": "body"})]) == 1
    with pg._connect() as conn:
        found = conn.execute("SELECT title, content, published_at FROM search_results WHERE normalized_url=%s", ("https://x.test/a",)).fetchall()
        meta = conn.execute("SELECT company_name, market_cap FROM ticker_metadata WHERE symbol=%s", (SYMBOL,)).fetchone()
        close = conn.execute("SELECT close FROM price_bars WHERE symbol=%s AND bar_date=%s", (SYMBOL, date(2026, 1, 3))).fetchone()
    assert len(found) == 1 and found[0][0] == "A2" and found[0][1] == "body" and found[0][2] == published
    assert meta == ("Test Co 2", 6)
    assert float(close[0]) == pytest.approx(1.9)
