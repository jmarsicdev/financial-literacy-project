from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main as api
from app import risk_profiles
from app.ingestion.pipeline import Ingestor
from app.orchestrator.config import OrchestratorConfig
from app.orchestrator.retrieval import Retriever, quarter_label, risk_profile_row
from app.rag_governance.intent_classifier import classify_intent
from app.rag_governance.schemas import Intent
from tests.conftest import make_settings
from tests.test_pipeline import Fake

LATEST = {
    "symbol": "NVDA",
    "quarter_start": date(2026, 7, 1),
    "risk_profile": "lower historical variability",
    "profile_rank": 0,
    "profile_count": 2,
    "annualized_volatility": 0.383,
    "max_drawdown": -0.106,
    "beta_vs_benchmark": 1.89,
    "avg_intraday_range": 0.027,
    "return_observations": 63,
    "asset_type": "EQUITY",
    "sector": "Technology",
    "benchmark": "SPY",
    "data_split": "test",
    "train_silhouette": 0.667,
    "test_silhouette": 0.621,
    "updated_at": "2026-11-16T20:00:00+00:00",
}
MIX = [
    {"risk_profile": "lower historical variability", "profile_rank": 0, "quarters": 41, "first_quarter": date(1999, 4, 1)},
    {"risk_profile": "higher historical variability", "profile_rank": 1, "quarters": 70, "first_quarter": date(1999, 1, 1)},
]


class FakeConnection:
    """Returns queued result sets in order, one per execute()."""

    def __init__(self, *results):
        self.results = list(results)
        self.queries = []
        self.row_factory = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.queries.append((query, params))
        rows = self.results.pop(0)

        class Result:
            def fetchall(self_inner):
                return rows

        return Result()


def test_symbol_profile_summarizes_latest_quarter_and_mix(monkeypatch):
    conn = FakeConnection([LATEST], MIX)
    monkeypatch.setattr(risk_profiles, "get_connection", lambda: conn)

    profile = risk_profiles.get_symbol_profile(" nvda ")

    assert profile["symbol"] == "NVDA"
    assert profile["latest"]["risk_profile"] == "lower historical variability"
    assert profile["quarters_total"] == 111
    assert profile["first_quarter"] == date(1999, 1, 1)
    assert [m["pct_of_quarters"] for m in profile["profile_mix"]] == [36.9, 63.1]
    assert "not a forecast" in profile["disclaimer"]
    assert conn.queries[0][1] == ("NVDA", 8)


def test_symbol_profile_is_none_when_not_computed(monkeypatch):
    monkeypatch.setattr(risk_profiles, "get_connection", lambda: FakeConnection([]))
    assert risk_profiles.get_symbol_profile("ZZZZ") is None


def test_risk_profile_endpoints(monkeypatch):
    client = TestClient(api.app)

    monkeypatch.setattr(risk_profiles, "get_connection", lambda: FakeConnection([LATEST], MIX))
    body = client.get("/risk-profiles/nvda").json()
    assert body["latest"]["annualized_volatility"] == 0.383
    assert body["profile_mix"][1]["quarters"] == 70

    monkeypatch.setattr(risk_profiles, "get_connection", lambda: FakeConnection([]))
    missing = client.get("/risk-profiles/ZZZZ")
    assert missing.status_code == 404 and "Spark clustering job" in missing.json()["detail"]

    monkeypatch.setattr(risk_profiles, "get_connection", lambda: FakeConnection([LATEST]))
    listing = client.get("/risk-profiles").json()
    assert listing["count"] == 1 and listing["items"][0]["symbol"] == "NVDA"

    def broken():
        raise RuntimeError("table missing")

    monkeypatch.setattr(risk_profiles, "get_connection", broken)
    assert client.get("/risk-profiles/NVDA").status_code == 503


# --- assistant evidence ---

def _profile():
    return {
        "latest": LATEST,
        "quarters_total": 111,
        "first_quarter": date(1999, 1, 1),
        "profile_mix": [
            {"risk_profile": "lower historical variability", "pct_of_quarters": 36.9},
            {"risk_profile": "higher historical variability", "pct_of_quarters": 63.1},
        ],
    }


def test_risk_profile_row_is_descriptive_and_citable():
    row = risk_profile_row("NVDA", _profile(), "http://localhost:8000")

    assert row["title"] == "NVDA historical risk profile (2026 Q3)"
    assert "In 2026 Q3 (the three months from July 1 to September 30, 2026)" in row["chunk_text"]
    assert quarter_label("2025-10-01") == ("2025 Q4", "October 1 to December 31, 2025")
    assert row["source_url"] == "http://localhost:8000/risk-profiles/NVDA"
    assert row["publisher"] == "Team 5 Spark risk model"
    text = row["chunk_text"]
    assert "annualized volatility 38.3%" in text and "beta versus SPY 1.89" in text
    assert "63% of quarters in 'higher historical variability'" in text
    assert "not a forecast or a recommendation" in text
    assert risk_profile_row("NVDA", None, "http://x") is None
    assert risk_profile_row("NVDA", {"latest": None}, "http://x") is None


def _retriever(load_profile):
    search = lambda query, top_k: {  # noqa: E731
        "query": query, "expanded_query": query, "matched_concepts": [], "relationships": [], "results": [],
    }
    return Retriever(
        OrchestratorConfig(provider="stub"),
        search=search,
        ingest_prices=lambda s: None,
        load_bars=lambda s, n: [],
        find_tickers=lambda q: ["NVDA"],
        load_profile=load_profile,
    )


def test_retriever_adds_risk_profile_evidence_for_named_ticker():
    outcome = _retriever(lambda s: _profile()).retrieve("How volatile is NVDA?", fetch_on_miss=False, with_prices=True)
    assert "risk_profile:NVDA" in outcome.notes
    assert [c.title for c in outcome.context.evidence_chunks] == [
        "NVDA historical risk profile (2026 Q3)"
    ]
    assert outcome.context.warnings == ()


def test_retriever_survives_missing_risk_profile_table():
    def boom(symbol):
        raise RuntimeError('relation "risk_profiles" does not exist')

    outcome = _retriever(boom).retrieve("How volatile is NVDA?", fetch_on_miss=False, with_prices=True)
    assert outcome.context.evidence_chunks == ()
    assert not any(note.startswith("risk_profile") for note in outcome.notes)

    skipped = _retriever(lambda s: _profile()).retrieve("How volatile is NVDA?", fetch_on_miss=False, with_prices=False)
    assert skipped.context.evidence_chunks == ()


# --- intent rules for risk and performance questions ---

@pytest.mark.parametrize("query", [
    "What is the risk profile of NVDA?",
    "How volatile has AMD been?",
    "What is the historical volatility of SPY?",
    "How has NVDA stock performed this week?",
])
def test_risk_and_performance_questions_are_market_information(query):
    assert classify_intent(query).intent == Intent.MARKET_INFORMATION


def test_personal_and_transactional_intents_still_take_priority():
    assert classify_intent("How risky is NVDA, should I buy it for my retirement?").intent == Intent.PERSONALIZED_ADVICE
    assert classify_intent("Buy 10 shares of NVDA for me").intent == Intent.TRANSACTIONAL


# --- price cache freshness ---

def test_price_history_is_refetched_after_a_day(store, yf_history, clock):
    fetch = Fake(yf_history)
    ingestor = Ingestor(store, make_settings(av_key=None), fetch_yf_history=fetch)

    assert ingestor.ingest_prices("NVDA").source == "api"
    clock.advance(hours=23)
    assert ingestor.ingest_prices("NVDA").source == "cache"
    assert len(fetch.calls) == 1

    clock.advance(hours=2)
    refreshed = ingestor.ingest_prices("NVDA")
    assert refreshed.source == "api" and refreshed.status == "ok"
    assert len(fetch.calls) == 2


def test_stale_price_history_is_served_when_refresh_fails(store, yf_history, clock):
    fetch = Fake(yf_history, RuntimeError("yfinance down"))
    ingestor = Ingestor(store, make_settings(av_key=None), fetch_yf_history=fetch)
    ingestor.ingest_prices("NVDA")
    clock.advance(hours=30)

    result = ingestor.ingest_prices("NVDA")

    assert result.status == "ok" and result.source == "cache"
    assert "served older cached history" in result.message
    assert store.table_counts()["price_bars"]["rows"] == 3


def test_price_cache_age_limit_can_be_disabled(store, yf_history, clock):
    fetch = Fake(yf_history)
    ingestor = Ingestor(store, make_settings(av_key=None), fetch_yf_history=fetch, price_max_age=timedelta(days=3650))
    ingestor.ingest_prices("NVDA")
    clock.advance(days=30)
    assert ingestor.ingest_prices("NVDA").source == "cache"
    assert len(fetch.calls) == 1
