from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    alpha_vantage_api_key: str | None
    tavily_api_key: str | None
    alpha_vantage_daily_limit: int = 25
    alpha_vantage_budget_window_hours: int = 24
    request_timeout_seconds: float = 30.0


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_str(name: str) -> str | None:
    return (os.getenv(name) or "").strip() or None


def load_settings() -> Settings:
    return Settings(
        alpha_vantage_api_key=_env_str("ALPHA_VANTAGE_API_KEY"),
        tavily_api_key=_env_str("TAVILY_API_KEY"),
        alpha_vantage_daily_limit=_env_int("ALPHA_VANTAGE_DAILY_LIMIT", 25),
        alpha_vantage_budget_window_hours=_env_int("ALPHA_VANTAGE_BUDGET_WINDOW_HOURS", 24),
        request_timeout_seconds=float(_env_int("INGEST_REQUEST_TIMEOUT_SECONDS", 30)),
    )
