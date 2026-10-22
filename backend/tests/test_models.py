from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.ingestion.models import PriceBar, SearchResult, TickerMetadata


def test_price_bar_normalizes_symbol_and_casts_strings():
    bar = PriceBar(symbol=" nvda ", bar_date="2026-10-21", open="1.5", high="2", low="1", close="1.75",
                   adjusted_close="1.75", volume="100", provider="alpha_vantage")
    assert bar.symbol == "NVDA"
    assert bar.bar_date.isoformat() == "2026-10-21"
    assert bar.volume == 100
    assert bar.open == 1.5


@pytest.mark.parametrize("kwargs, fragment", [
    (dict(high=1.0, low=2.0, open=1.5, close=1.5), "below low"),
    (dict(high=2.0, low=1.0, open=2.5, close=1.5), "open"),
    (dict(high=2.0, low=1.0, open=1.5, close=0.5), "close"),
    (dict(high=2.0, low=1.0, open=1.5, close=1.5, volume=-1), "greater than or equal"),
])
def test_price_bar_rejects_inconsistent_ohlc(kwargs, fragment):
    base = dict(symbol="X", bar_date="2026-01-01", adjusted_close=1.5, volume=1)
    base.update(kwargs)
    with pytest.raises(ValidationError) as excinfo:
        PriceBar(**base)
    assert fragment in str(excinfo.value)


def test_search_result_forces_utc_and_exposes_date():
    naive = SearchResult(title="t", published_at=datetime(2026, 10, 20, 9, 0))
    assert naive.published_at.tzinfo is timezone.utc
    assert naive.published_date.isoformat() == "2026-10-20"
    assert naive.is_dated

    eastern = SearchResult(title="t", published_at="2026-10-19T23:30:00-04:00")
    assert eastern.published_at.isoformat() == "2026-10-20T03:30:00+00:00"

    undated = SearchResult(title="t")
    assert not undated.is_dated and undated.published_date is None


def test_search_result_requires_title_and_bounds_score():
    with pytest.raises(ValidationError):
        SearchResult(title="   ")
    with pytest.raises(ValidationError):
        SearchResult(title="t", score=1.5)


def test_ticker_metadata_symbol_upper():
    assert TickerMetadata(symbol="spy").symbol == "SPY"
