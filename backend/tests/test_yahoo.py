import pytest

from app.ingestion.providers import yahoo


def test_classify_history(yf_history):
    assert yahoo.classify_history(yf_history) == "ok"
    assert yahoo.classify_history({"symbol": "X", "rows": []}) == "error"
    assert yahoo.classify_history({"error": "boom"}) == "error"
    assert yahoo.classify_history({"nope": 1}) == "invalid"


def test_normalize_history_uses_adj_close_and_rejects_null_open(yf_history):
    result = yahoo.normalize_history(yf_history, "nvda")
    assert result.is_adjusted is True
    assert [b.bar_date.isoformat() for b in result.bars] == ["2026-10-17", "2026-10-20", "2026-10-21"]
    assert result.bars[0].adjusted_close == pytest.approx(179.19)
    assert result.bars[0].volume == 133885000
    assert result.bars[0].provider == "yfinance"
    assert len(result.rejected) == 1 and "2026-10-16" in result.rejected[0]


def test_normalize_info_stock(yf_info):
    meta = yahoo.normalize_info(yf_info["stock"], "NVDA")
    assert meta.company_name == "NVIDIA Corporation"
    assert meta.sector == "Technology"
    assert meta.industry == "Semiconductors"
    assert meta.exchange == "NasdaqGS"
    assert meta.market_cap == 4512000000000
    assert meta.business_summary.startswith("NVIDIA")
    assert meta.provider == "yfinance"


def test_normalize_info_etf_uses_category(yf_info):
    meta = yahoo.normalize_info(yf_info["etf"], "SMH")
    assert meta.sector is None
    assert meta.industry == "Technology"
    assert meta.market_cap is None


def test_classify_info(yf_info):
    assert yahoo.classify_info(yf_info["stock"]) == "ok"
    assert yahoo.classify_info(yf_info["etf"]) == "ok"
    assert yahoo.classify_info(yf_info["unknown"]) == "error"


def test_cache_keys():
    assert yahoo.cache_key_history("nvda") == "history:max:NVDA"
    assert yahoo.cache_key_info("nvda") == "info:NVDA"


def test_num_helper_handles_nan_and_none():
    assert yahoo._num(float("nan")) is None
    assert yahoo._num(None) is None
    assert yahoo._num("1.5") == 1.5
    assert yahoo._num("abc") is None
