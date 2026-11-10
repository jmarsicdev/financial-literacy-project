# av returns errors/limits as http 200, classify() sorts them out
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from ..models import PriceBar

PROVIDER = "alpha_vantage"
BASE_URL = "https://www.alphavantage.co/query"
FUNCTION_ADJUSTED = "TIME_SERIES_DAILY_ADJUSTED"
FUNCTION_DAILY = "TIME_SERIES_DAILY"

PayloadStatus = Literal["ok", "rate_limited", "premium", "error", "invalid"]

_FIELD_PREFIX = re.compile(r"^\d+[a-z]?\.\s*")


class SymbolMismatch(ValueError):
    pass


@dataclass
class NormalizedBars:
    bars: list[PriceBar]
    rejected: list[str] = field(default_factory=list)
    is_adjusted: bool = False
    meta_symbol: str | None = None
    last_refreshed: str | None = None


def function_name(adjusted: bool) -> str:
    return FUNCTION_ADJUSTED if adjusted else FUNCTION_DAILY


def cache_key(symbol: str, adjusted: bool = True) -> str:
    return f"{'daily_adjusted' if adjusted else 'daily'}:{symbol.strip().upper()}"


def public_params(symbol: str, adjusted: bool = True, outputsize: str = "full") -> dict[str, str]:
    return {
        "function": function_name(adjusted),
        "symbol": symbol.strip().upper(),
        "outputsize": outputsize,
        "datatype": "json",
    }


# --- fetch ---

def fetch_daily(
    symbol: str,
    api_key: str,
    *,
    adjusted: bool = True,
    outputsize: str = "full",
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    params = {**public_params(symbol, adjusted, outputsize), "apikey": api_key}
    if client is None:
        with httpx.Client(timeout=timeout) as owned:
            response = owned.get(BASE_URL, params=params)
    else:
        response = client.get(BASE_URL, params=params)
    response.raise_for_status()
    return response.json()


# --- classify ---

def _series_key(payload: dict[str, Any]) -> str | None:
    for key in payload:
        if isinstance(key, str) and key.startswith("Time Series"):
            return key
    return None


def _meta_symbol(payload: dict[str, Any]) -> str | None:
    meta = payload.get("Meta Data")
    if not isinstance(meta, dict):
        return None
    for key, value in meta.items():
        if "symbol" in str(key).lower():
            return str(value).strip().upper() or None
    return None


def classify(payload: Any, requested_symbol: str | None = None) -> PayloadStatus:
    if not isinstance(payload, dict):
        return "invalid"
    if "Error Message" in payload:
        return "error"
    if "Note" in payload:
        return "rate_limited"
    info = payload.get("Information")
    if info:
        text = str(info).lower()
        if "premium endpoint" in text:
            return "premium"
        if any(p in text for p in ("rate limit", "per day", "per minute", "call frequency", "requests/day")):
            return "rate_limited"
        if "premium" in text:
            return "premium"
        return "error"
    if "Meta Data" in payload and _series_key(payload):
        if requested_symbol:
            meta_symbol = _meta_symbol(payload)
            if meta_symbol and meta_symbol != requested_symbol.strip().upper():
                return "invalid"
        return "ok"
    return "invalid"


# --- normalize ---

def _clean_field(name: str) -> str:
    return _FIELD_PREFIX.sub("", name).strip().lower().replace(" ", "_")


def normalize_daily(payload: dict[str, Any], requested_symbol: str, provider: str = PROVIDER) -> NormalizedBars:
    series_key = _series_key(payload)
    if series_key is None:
        raise ValueError("payload has no 'Time Series' block")

    symbol = requested_symbol.strip().upper()
    meta_symbol = _meta_symbol(payload)
    if meta_symbol and meta_symbol != symbol:
        raise SymbolMismatch(f"requested {symbol} but payload is for {meta_symbol}")

    meta = payload.get("Meta Data") or {}
    last_refreshed = next((str(v) for k, v in meta.items() if "last refreshed" in str(k).lower()), None)

    result = NormalizedBars(bars=[], meta_symbol=meta_symbol, last_refreshed=last_refreshed)
    series = payload[series_key]
    if not isinstance(series, dict):
        raise ValueError("'Time Series' block is not an object")

    is_adjusted: bool | None = None
    for day, fields in series.items():
        if not isinstance(fields, dict):
            result.rejected.append(f"{day}: row is not an object")
            continue
        row = {_clean_field(k): v for k, v in fields.items()}
        if is_adjusted is None:
            is_adjusted = "adjusted_close" in row
        try:
            bar = PriceBar(
                symbol=symbol,
                bar_date=day,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                adjusted_close=row.get("adjusted_close", row["close"]),
                volume=int(float(row["volume"])),
                provider=provider,
            )
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            result.rejected.append(f"{day}: {_short_error(exc)}")
            continue
        result.bars.append(bar)

    result.is_adjusted = bool(is_adjusted)
    result.bars.sort(key=lambda b: b.bar_date)
    return result


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(e.get("msg", "invalid") for e in exc.errors())
    if isinstance(exc, KeyError):
        return f"missing field {exc}"
    return str(exc)
