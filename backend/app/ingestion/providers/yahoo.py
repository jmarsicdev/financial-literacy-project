from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from ..models import PriceBar, TickerMetadata

PROVIDER = "yfinance"
ENDPOINT_HISTORY = "history"
ENDPOINT_INFO = "info"

PayloadStatus = Literal["ok", "error", "invalid"]

_INFO_KEYS = (
    "symbol", "shortName", "longName", "quoteType", "sector", "industry",
    "exchange", "fullExchangeName", "marketCap", "longBusinessSummary",
    "currency", "country", "website", "fundFamily", "category",
)


@dataclass
class NormalizedBars:
    bars: list[PriceBar]
    rejected: list[str] = field(default_factory=list)
    is_adjusted: bool = True


def cache_key_history(symbol: str, period: str = "max") -> str:
    return f"{ENDPOINT_HISTORY}:{period}:{symbol.strip().upper()}"


def cache_key_info(symbol: str) -> str:
    return f"{ENDPOINT_INFO}:{symbol.strip().upper()}"


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


# --- fetch, dataframe -> plain json so it fits in raw_payloads ---

def fetch_history(symbol: str, period: str = "max") -> dict[str, Any]:
    import yfinance as yf

    ticker = yf.Ticker(symbol.strip().upper())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # pandas deprecation spam from yfinance
        frame = ticker.history(period=period, auto_adjust=False, actions=True)
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        rows.append(
            {
                "date": index.date().isoformat() if hasattr(index, "date") else str(index)[:10],
                "open": _num(row.get("Open")),
                "high": _num(row.get("High")),
                "low": _num(row.get("Low")),
                "close": _num(row.get("Close")),
                "adj_close": _num(row.get("Adj Close")),
                "volume": _num(row.get("Volume")),
                "dividends": _num(row.get("Dividends")),
                "stock_splits": _num(row.get("Stock Splits")),
            }
        )
    return {"symbol": symbol.strip().upper(), "period": period, "rows": rows}


def fetch_info(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    info = yf.Ticker(symbol.strip().upper()).info or {}
    payload: dict[str, Any] = {"requested_symbol": symbol.strip().upper()}
    for key in _INFO_KEYS:
        value = info.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[key] = value
    return payload


# --- classify ---

def classify_history(payload: Any) -> PayloadStatus:
    if not isinstance(payload, dict):
        return "invalid"
    if "error" in payload:
        return "error"
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return "invalid"
    return "ok" if rows else "error"


def classify_info(payload: Any) -> PayloadStatus:
    if not isinstance(payload, dict):
        return "invalid"
    if "error" in payload:
        return "error"
    if any(payload.get(k) for k in ("longName", "shortName", "sector", "marketCap", "quoteType")):
        return "ok"
    return "error"


# --- normalize ---

def normalize_history(payload: dict[str, Any], requested_symbol: str, provider: str = PROVIDER) -> NormalizedBars:
    symbol = requested_symbol.strip().upper()
    result = NormalizedBars(bars=[])
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("payload has no 'rows' list")
    saw_adjusted = False
    for row in rows:
        day = row.get("date")
        try:
            close = row["close"]
            adj = row.get("adj_close")
            if adj is not None:
                saw_adjusted = True
            bar = PriceBar(
                symbol=symbol,
                bar_date=day,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=close,
                adjusted_close=adj if adj is not None else close,
                volume=int(row["volume"] or 0),
                provider=provider,
            )
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            result.rejected.append(f"{day}: {_short_error(exc)}")
            continue
        result.bars.append(bar)
    result.is_adjusted = saw_adjusted
    result.bars.sort(key=lambda b: b.bar_date)
    return result


def normalize_info(payload: dict[str, Any], requested_symbol: str, provider: str = PROVIDER) -> TickerMetadata:
    symbol = requested_symbol.strip().upper()
    market_cap = payload.get("marketCap")
    try:
        market_cap_int = int(market_cap) if market_cap is not None else None
    except (TypeError, ValueError):
        market_cap_int = None
    sector = payload.get("sector")
    industry = payload.get("industry")
    if not sector and not industry and payload.get("quoteType") == "ETF":
        industry = payload.get("category") or "ETF"
    return TickerMetadata(
        symbol=symbol,
        company_name=payload.get("longName") or payload.get("shortName"),
        sector=sector,
        industry=industry,
        exchange=payload.get("fullExchangeName") or payload.get("exchange"),
        market_cap=market_cap_int,
        business_summary=payload.get("longBusinessSummary"),
        provider=provider,
    )


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(e.get("msg", "invalid") for e in exc.errors())
    if isinstance(exc, KeyError):
        return f"missing field {exc}"
    return str(exc)
