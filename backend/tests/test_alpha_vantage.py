import pytest

from app.ingestion.providers import alpha_vantage as av


def test_classify_success_and_symbol_check(av_adjusted):
    assert av.classify(av_adjusted) == "ok"
    assert av.classify(av_adjusted, "nvda") == "ok"
    assert av.classify(av_adjusted, "AMD") == "invalid"


@pytest.mark.parametrize("key, expected", [
    ("daily_limit", "rate_limited"),
    ("premium_endpoint", "premium"),
    ("per_minute_note", "rate_limited"),
    ("bad_symbol", "error"),
    ("empty", "invalid"),
])
def test_classify_notices(av_notices, key, expected):
    assert av.classify(av_notices[key]) == expected


def test_classify_non_dict():
    assert av.classify(None) == "invalid"
    assert av.classify("text") == "invalid"


def test_normalize_adjusted_strips_prefixes_and_rejects_bad_rows(av_adjusted):
    result = av.normalize_daily(av_adjusted, "NVDA")
    assert result.is_adjusted is True
    assert result.meta_symbol == "NVDA"
    assert result.last_refreshed == "2026-10-21"
    # 4 rows in fixture, 2026-10-16 has high < low and must be rejected
    assert [b.bar_date.isoformat() for b in result.bars] == ["2026-10-17", "2026-10-20", "2026-10-21"]
    assert len(result.rejected) == 1 and "2026-10-16" in result.rejected[0]
    oct17 = result.bars[0]
    assert oct17.close == pytest.approx(179.20)
    assert oct17.adjusted_close == pytest.approx(179.19)
    assert oct17.volume == 133885000
    assert oct17.provider == "alpha_vantage"
    assert oct17.symbol == "NVDA"


def test_normalize_unadjusted_falls_back_to_close(av_unadjusted):
    result = av.normalize_daily(av_unadjusted, "amd")
    assert result.is_adjusted is False
    assert all(b.adjusted_close == b.close for b in result.bars)
    assert len(result.bars) == 2 and not result.rejected


def test_normalize_symbol_mismatch_raises(av_adjusted):
    with pytest.raises(av.SymbolMismatch):
        av.normalize_daily(av_adjusted, "MSFT")


def test_normalize_requires_series(av_notices):
    with pytest.raises(ValueError):
        av.normalize_daily(av_notices["daily_limit"], "NVDA")


def test_cache_key_and_params_exclude_api_key():
    assert av.cache_key(" nvda ") == "daily_adjusted:NVDA"
    assert av.cache_key("NVDA", adjusted=False) == "daily:NVDA"
    params = av.public_params("nvda")
    assert params["symbol"] == "NVDA"
    assert params["function"] == "TIME_SERIES_DAILY_ADJUSTED"
    assert "apikey" not in params
