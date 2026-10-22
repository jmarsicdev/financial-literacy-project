import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ingestion.config import Settings
from tests.fake_store import InMemoryStore

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def av_adjusted():
    return load_fixture("alpha_vantage_daily_adjusted.json")


@pytest.fixture
def av_unadjusted():
    return load_fixture("alpha_vantage_daily_unadjusted.json")


@pytest.fixture
def av_notices():
    return load_fixture("alpha_vantage_notices.json")


@pytest.fixture
def yf_history():
    return load_fixture("yahoo_history.json")


@pytest.fixture
def yf_info():
    return load_fixture("yahoo_info.json")


@pytest.fixture
def tavily_news():
    return load_fixture("tavily_news.json")


class FakeClock:
    """Controllable clock for the in-memory store."""

    def __init__(self, start: datetime | None = None):
        self.now = start or datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(clock):
    return InMemoryStore(clock=clock)


def make_settings(*, av_key="av-test-key", tavily_key="tv-test-key", limit=25, window_hours=24) -> Settings:
    return Settings(
        alpha_vantage_api_key=av_key,
        tavily_api_key=tavily_key,
        alpha_vantage_daily_limit=limit,
        alpha_vantage_budget_window_hours=window_hours,
        request_timeout_seconds=5.0,
    )


@pytest.fixture
def settings():
    return make_settings()
