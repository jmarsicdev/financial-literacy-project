from datetime import timedelta

import httpx
import pytest

from app.ingestion.pipeline import Ingestor
from app.ingestion.providers import alpha_vantage, tavily, yahoo
from tests.conftest import make_settings


class Fake:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        item = self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0]
        if isinstance(item, Exception):
            raise item
        return item


def build(store, settings, *, av=None, yf_hist=None, yf_info=None, tv=None):
    av = av or Fake({"Information": "unused"})
    yf_hist = yf_hist or Fake({"symbol": "X", "rows": []})
    yf_info = yf_info or Fake({})
    tv = tv or Fake({"results": []})
    ingestor = Ingestor(store, settings, fetch_av=av, fetch_yf_history=yf_hist, fetch_yf_info=yf_info, fetch_tavily=tv)
    return ingestor, av, yf_hist, yf_info, tv


# ---------------------------------------------------------------------------
# Price bars
# ---------------------------------------------------------------------------


def test_av_success_then_cache_hit(store, settings, av_adjusted):
    ingestor, av, yf, *_ = build(store, settings, av=Fake(av_adjusted))

    first = ingestor.ingest_prices("nvda")
    assert first.status == "ok" and first.source == "api" and first.provider == "alpha_vantage"
    assert first.records == 3 and first.rejected == 1
    assert len(av.calls) == 1 and len(yf.calls) == 0
    assert ingestor.av_budget().used == 1
    assert store.table_counts()["price_bars"] == {"rows": 3, "symbols": 1}

    second = ingestor.ingest_prices("NVDA")
    assert second.status == "ok" and second.source == "cache"
    assert len(av.calls) == 1, "cache hit must not spend budget"
    assert ingestor.av_budget().used == 1


def test_refresh_bypasses_cache(store, settings, av_adjusted):
    ingestor, av, *_ = build(store, settings, av=Fake(av_adjusted))
    ingestor.ingest_prices("NVDA")
    ingestor.ingest_prices("NVDA", refresh=True)
    assert len(av.calls) == 2
    assert ingestor.av_budget().used == 2


def test_no_key_uses_yfinance(store, yf_history):
    settings = make_settings(av_key=None)
    ingestor, av, yf, *_ = build(store, settings, yf_hist=Fake(yf_history))
    result = ingestor.ingest_prices("NVDA")
    assert result.status == "fallback" and result.provider == "yfinance" and result.source == "api"
    assert result.records == 3 and result.rejected == 1
    assert "no ALPHA_VANTAGE_API_KEY" in result.message
    assert len(av.calls) == 0 and len(yf.calls) == 1
    assert ingestor.av_budget().used == 0


@pytest.mark.parametrize("notice_key, expected_status", [
    ("premium_endpoint", "premium"),
    ("daily_limit", "rate_limited"),
    ("bad_symbol", "error"),
])
def test_av_notice_is_recorded_and_falls_back(store, settings, av_notices, yf_history, notice_key, expected_status):
    ingestor, av, yf, *_ = build(store, settings, av=Fake(av_notices[notice_key]), yf_hist=Fake(yf_history))
    result = ingestor.ingest_prices("NVDA")
    assert result.status == "fallback" and result.provider == "yfinance"
    assert f"alpha_vantage {expected_status}" in result.message
    assert len(av.calls) == 1 and len(yf.calls) == 1
    # the failed attempt still counts against the budget
    assert ingestor.av_budget().used == 1
    recorded = [p for p in store.payloads if p.provider == alpha_vantage.PROVIDER]
    assert recorded[0].status == expected_status
    # and is NOT served from cache next time
    assert store.get_cached(alpha_vantage.PROVIDER, alpha_vantage.cache_key("NVDA")) is None


def test_av_transport_error_recorded_as_error(store, settings, yf_history):
    boom = httpx.ConnectError("connection refused")
    ingestor, av, yf, *_ = build(store, settings, av=Fake(boom), yf_hist=Fake(yf_history))
    result = ingestor.ingest_prices("NVDA")
    assert result.status == "fallback"
    recorded = [p for p in store.payloads if p.provider == alpha_vantage.PROVIDER][0]
    assert recorded.status == "error" and "ConnectError" in recorded.payload["error"]


def test_av_symbol_mismatch_falls_back(store, settings, av_adjusted, yf_history):
    # fixture is NVDA; ask for AMD
    ingestor, av, yf, *_ = build(store, settings, av=Fake(av_adjusted), yf_hist=Fake(yf_history))
    result = ingestor.ingest_prices("AMD")
    assert result.status == "fallback"
    assert "alpha_vantage invalid" in result.message


def test_budget_exhausted_skips_av(store, settings, av_adjusted, yf_history, clock):
    settings = make_settings(limit=2)
    ingestor, av, yf, *_ = build(store, settings, av=Fake(av_adjusted), yf_hist=Fake(yf_history))
    # two different symbols spend the whole budget (fixture symbol mismatch doesn't matter for counting)
    store.record(alpha_vantage.PROVIDER, "x", {}, "k1", {}, "ok")
    store.record(alpha_vantage.PROVIDER, "x", {}, "k2", {}, "rate_limited")
    assert ingestor.av_budget().remaining == 0

    result = ingestor.ingest_prices("NVDA")
    assert result.status == "fallback" and result.provider == "yfinance"
    assert "budget exhausted" in result.message
    assert len(av.calls) == 0

    # budget window rolls over
    clock.advance(hours=25)
    assert ingestor.av_budget().remaining == 2


def test_budget_exhausted_no_fallback_is_skipped(store, av_adjusted):
    settings = make_settings(limit=0)
    ingestor, av, yf, *_ = build(store, settings, av=Fake(av_adjusted))
    result = ingestor.ingest_prices("NVDA", allow_fallback=False)
    assert result.status == "skipped"
    assert len(av.calls) == 0 and len(yf.calls) == 0
    assert store.table_counts()["price_bars"]["rows"] == 0


def test_yfinance_failure_after_av_failure_is_failed(store, settings, av_notices):
    ingestor, *_ = build(store, settings, av=Fake(av_notices["daily_limit"]), yf_hist=Fake(RuntimeError("yf down")))
    result = ingestor.ingest_prices("NVDA")
    assert result.status == "failed"
    assert "alpha_vantage rate_limited" in result.message and "yfinance error" in result.message


def test_cached_yfinance_preferred_over_spending_budget(store, settings, av_adjusted, yf_history):
    no_key = make_settings(av_key=None)
    ingestor, av, yf, *_ = build(store, no_key, yf_hist=Fake(yf_history))
    ingestor.ingest_prices("NVDA")  # yfinance payload now cached

    with_key, av2, yf2, *_ = build(store, settings, av=Fake(av_adjusted), yf_hist=Fake(yf_history))
    result = with_key.ingest_prices("NVDA")
    assert result.source == "cache" and result.provider == "yfinance"
    assert len(av2.calls) == 0


def test_plan_prices(store, settings, av_adjusted):
    settings = make_settings(limit=2)
    ingestor, *_ = build(store, settings, av=Fake(av_adjusted))
    ingestor.ingest_prices("NVDA")
    plan = ingestor.plan_prices(["NVDA", "AMD", "MSFT", "AAPL"])
    assert [p["action"] for p in plan] == [
        "cache:alpha_vantage",
        "api:alpha_vantage",
        "api:yfinance (alpha_vantage budget exhausted)",
        "api:yfinance (alpha_vantage budget exhausted)",
    ]
    no_key = Ingestor(store, make_settings(av_key=None), fetch_av=Fake({}), fetch_yf_history=Fake({}))
    assert no_key.plan_prices(["AMD"], allow_fallback=False)[0]["action"].startswith("skip (no alpha_vantage key")


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_metadata_cache_first(store, settings, yf_info):
    ingestor, _, _, info, _ = build(store, settings, yf_info=Fake(yf_info["stock"]))
    first = ingestor.ingest_metadata("nvda")
    assert first.status == "ok" and first.source == "api"
    second = ingestor.ingest_metadata("NVDA")
    assert second.source == "cache"
    assert len(info.calls) == 1
    assert store.ticker_metadata["NVDA"].sector == "Technology"


def test_metadata_unknown_symbol_fails(store, settings, yf_info):
    ingestor, _, _, info, _ = build(store, settings, yf_info=Fake(yf_info["unknown"]))
    result = ingestor.ingest_metadata("ZZZZ")
    assert result.status == "failed"
    assert store.payloads[-1].status == "error"


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


def test_news_normalizes_dedups_and_caches(store, settings, tavily_news, clock):
    ingestor, *_, tv = build(store, settings, tv=Fake(tavily_news))
    result = ingestor.ingest_news("Nvidia  earnings")
    assert result.status == "ok" and result.source == "api"
    assert result.records == 3 and result.duplicates == 2 and result.rejected == 1
    assert "1 undated" in result.message
    assert store.table_counts()["search_results"]["rows"] == 3
    recorded = store.payloads[-1]
    assert recorded.provider == tavily.PROVIDER and recorded.params["query"] == "Nvidia earnings"

    again = ingestor.ingest_news("nvidia earnings")  # same key after whitespace/case normalization
    assert again.source == "cache" and len(tv.calls) == 1

    clock.advance(hours=7)  # past the 6h default max age
    stale = ingestor.ingest_news("nvidia earnings")
    assert stale.source == "api" and len(tv.calls) == 2


def test_news_without_key_is_skipped(store, tavily_news):
    ingestor, *_, tv = build(store, make_settings(tavily_key=None), tv=Fake(tavily_news))
    result = ingestor.ingest_news("anything")
    assert result.status == "skipped" and len(tv.calls) == 0


def test_news_rate_limited_recorded(store, settings):
    ingestor, *_, tv = build(store, settings, tv=Fake({"error": "rate_limited", "status_code": 429}))
    result = ingestor.ingest_news("q")
    assert result.status == "failed" and "rate_limited" in result.message
    assert store.payloads[-1].status == "rate_limited"


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def test_replay_rebuilds_tables_without_api_calls(store, settings, av_adjusted, yf_history, yf_info, tavily_news):
    ingestor, av, yf, info, tv = build(
        store, settings, av=Fake(av_adjusted), yf_hist=Fake(yf_history), yf_info=Fake(yf_info["stock"]), tv=Fake(tavily_news),
    )
    ingestor.ingest_prices("NVDA")
    ingestor.ingest_prices("AMD")      # AV fixture mismatch -> yfinance fallback (fixture says NVDA but normalizes under AMD)
    ingestor.ingest_metadata("NVDA")
    ingestor.ingest_news("Nvidia earnings")
    before = store.table_counts()
    call_counts = (len(av.calls), len(yf.calls), len(info.calls), len(tv.calls))

    store.price_bars.clear()
    store.ticker_metadata.clear()
    store.search_results.clear()

    results = ingestor.replay()
    assert all(r.succeeded for r in results), [r.to_dict() for r in results]
    assert {r.kind for r in results} == {"prices", "metadata", "news"}
    assert store.table_counts() == before
    assert (len(av.calls), len(yf.calls), len(info.calls), len(tv.calls)) == call_counts
    # invalid AV payload for AMD is not replayed (status != ok)
    assert sum(1 for r in results if r.provider == yahoo.PROVIDER and r.kind == "prices") == 1
