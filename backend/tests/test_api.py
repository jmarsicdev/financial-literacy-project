import pytest
from fastapi.testclient import TestClient

from app import main as api
from app.ingestion.pipeline import Ingestor
from tests.conftest import make_settings
from tests.fake_store import InMemoryStore
from tests.test_pipeline import Fake


@pytest.fixture
def client(monkeypatch, av_adjusted, tavily_news):
    memory = InMemoryStore()
    ingestor = Ingestor(
        memory, make_settings(),
        fetch_av=Fake(av_adjusted), fetch_yf_history=Fake({"rows": []}),
        fetch_yf_info=Fake({}), fetch_tavily=Fake(tavily_news),
    )
    monkeypatch.setattr(api, "build_ingestor", lambda: ingestor)
    return TestClient(api.app), memory


def test_budget_endpoint(client):
    http, _ = client
    response = http.get("/ingest/budget")
    assert response.status_code == 200
    assert response.json()["remaining"] == 25


def test_ingest_prices_endpoint(client):
    http, memory = client
    response = http.post("/ingest/prices/nvda")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok" and body["records"] == 3 and body["target"] == "NVDA"
    assert memory.table_counts()["price_bars"]["rows"] == 3

    cached = http.post("/ingest/prices/NVDA").json()
    assert cached["source"] == "cache"


def test_ingest_news_endpoint_and_status(client):
    http, _ = client
    response = http.post("/ingest/news", params={"query": "Nvidia earnings", "days": 3})
    assert response.status_code == 200, response.text
    assert response.json()["records"] == 3
    status = http.get("/ingest/status").json()
    assert status["search_results"]["rows"] == 3
    assert status["raw_payloads"]["tavily"] == {"ok": 1}


def test_ingest_news_validation(client):
    http, _ = client
    assert http.post("/ingest/news", params={"query": "x"}).status_code == 422
    assert http.post("/ingest/news", params={"query": "ok query", "topic": "weird"}).status_code == 422


def test_failed_ingest_returns_502(client, monkeypatch, av_notices):
    http, memory = client
    failing = Ingestor(
        memory, make_settings(),
        fetch_av=Fake(av_notices["daily_limit"]), fetch_yf_history=Fake(RuntimeError("down")),
        fetch_yf_info=Fake({}), fetch_tavily=Fake({}),
    )
    monkeypatch.setattr(api, "build_ingestor", lambda: failing)
    response = http.post("/ingest/prices/AMD")
    assert response.status_code == 502
    assert response.json()["detail"]["status"] == "failed"
