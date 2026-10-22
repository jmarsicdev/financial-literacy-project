import json

import pytest

from app.ingestion import __main__ as cli
from app.ingestion import store as store_module
from app.ingestion.tickers import AI_TECH_STOCKS, BENCHMARK_ETFS, DEFAULT_TICKERS, parse_ticker_list
from tests.fake_store import InMemoryStore


def test_default_ticker_universe_fits_budget():
    assert len(DEFAULT_TICKERS) <= 25 - 5, "keep at least 5 calls of headroom"
    assert len(set(DEFAULT_TICKERS)) == len(DEFAULT_TICKERS)
    assert set(BENCHMARK_ETFS) <= set(DEFAULT_TICKERS)
    assert "NVDA" in AI_TECH_STOCKS


def test_parse_ticker_list():
    assert parse_ticker_list(None) == DEFAULT_TICKERS
    assert parse_ticker_list("nvda, amd  msft,nvda") == ["NVDA", "AMD", "MSFT"]


@pytest.fixture
def cli_store(monkeypatch):
    memory = InMemoryStore()
    monkeypatch.setattr(store_module, "PostgresStore", lambda: memory)
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    return memory


def test_cli_budget_json(cli_store, capsys):
    assert cli.main(["--json", "budget"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["limit"] == 25 and out["used"] == 0 and out["remaining"] == 25


def test_cli_dry_run_makes_no_calls(cli_store, capsys):
    assert cli.main(["seed-prices", "--tickers", "NVDA,AMD", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "NVDA   api:alpha_vantage" in out
    assert "would spend 2 alpha_vantage call(s)" in out
    assert cli_store.payloads == []


def test_cli_status(cli_store, capsys):
    assert cli.main(["status"]) == 0
    assert "price_bars" in capsys.readouterr().out


def test_cli_news_without_key_fails_exit_code(cli_store, capsys):
    assert cli.main(["news", "--query", "x"]) == 1
    assert "skipped" in capsys.readouterr().out
