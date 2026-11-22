from fastapi.testclient import TestClient

import pytest

from app import main as api
from app.orchestrator import router as ask_router
from app.orchestrator.cache import AskCache, cache_key, is_cacheable
from app.orchestrator.schemas import AskResponse, GovernanceOut


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    """Every router test gets its own in-memory answer cache."""
    monkeypatch.setattr(ask_router, "ask_cache", AskCache(client=FakeRedis(), ttl_seconds=3600))


def _response(answer="An ETF is a fund [1].", status="PASS"):
    return AskResponse(
        answer=answer,
        governance=GovernanceOut(
            intent="EDUCATIONAL", action="ALLOW", mode="STANDARD", confidence=0.85, status=status
        ),
        generated=True,
        generator="fake",
    )


class FakeOrchestrator:
    def __init__(self, response=None, error=None):
        self.response = response or _response()
        self.error = error
        self.calls = []

    def ask(self, query, *, top_k=None, debug=False):
        self.calls.append({"query": query, "top_k": top_k, "debug": debug})
        if self.error:
            raise self.error
        return self.response


def test_ask_route_is_registered():
    assert "/ask" in {route.path for route in api.app.routes}


def test_ask_returns_orchestrator_response(monkeypatch):
    fake = FakeOrchestrator()
    monkeypatch.setattr(ask_router, "build_orchestrator", lambda: fake)

    response = TestClient(api.app).post("/ask", json={"query": "What is an ETF?", "top_k": 4, "debug": True})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "An ETF is a fund [1]."
    assert body["governance"]["status"] == "PASS"
    assert fake.calls == [{"query": "What is an ETF?", "top_k": 4, "debug": True}]


def test_ask_validates_input(monkeypatch):
    monkeypatch.setattr(ask_router, "build_orchestrator", lambda: FakeOrchestrator())
    client = TestClient(api.app)
    assert client.post("/ask", json={"query": "x"}).status_code == 422
    assert client.post("/ask", json={"query": "What is an ETF?", "top_k": 0}).status_code == 422
    assert client.post("/ask", json={}).status_code == 422


def test_ask_maps_failures_to_503(monkeypatch):
    monkeypatch.setattr(ask_router, "build_orchestrator", lambda: FakeOrchestrator(error=RuntimeError("boom")))
    response = TestClient(api.app).post("/ask", json={"query": "What is an ETF?"})
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]


def test_repeated_question_is_served_from_cache(monkeypatch):
    fake = FakeOrchestrator()
    monkeypatch.setattr(ask_router, "build_orchestrator", lambda: fake)
    client = TestClient(api.app)

    first = client.post("/ask", json={"query": "What is an ETF?"}).json()
    second = client.post("/ask", json={"query": "  what is an ETF?  "}).json()   # same question, different spacing/case

    assert first["cached"] is False and second["cached"] is True
    assert second["cached_at"]
    assert second["answer"] == first["answer"]
    assert len(fake.calls) == 1


def test_cache_can_be_bypassed_and_refreshed(monkeypatch):
    fake = FakeOrchestrator()
    monkeypatch.setattr(ask_router, "build_orchestrator", lambda: fake)
    client = TestClient(api.app)

    client.post("/ask", json={"query": "What is an ETF?"})
    fresh = client.post("/ask", json={"query": "What is an ETF?", "cache": False}).json()

    assert fresh["cached"] is False
    assert len(fake.calls) == 2


def test_cache_key_depends_on_model_and_top_k():
    assert cache_key("What is an ETF?", "m1", None) == cache_key("what is an etf?", "m1", None)
    assert cache_key("What is an ETF?", "m1", None) != cache_key("What is an ETF?", "m2", None)
    assert cache_key("What is an ETF?", "m1", 3) != cache_key("What is an ETF?", "m1", 5)


def test_only_real_model_answers_are_cached(monkeypatch):
    fallback = _response(answer="I couldn't generate an answer right now.", status="REVIEW")
    fallback.generated = False
    blocked = _response(status="BLOCK")
    assert is_cacheable(_response()) and is_cacheable(_response(status="REVIEW"))
    assert not is_cacheable(fallback) and not is_cacheable(blocked)

    fake = FakeOrchestrator(response=fallback)
    monkeypatch.setattr(ask_router, "build_orchestrator", lambda: fake)
    client = TestClient(api.app)
    client.post("/ask", json={"query": "What is an ETF?"})
    client.post("/ask", json={"query": "What is an ETF?"})
    assert len(fake.calls) == 2


def test_cached_answers_never_carry_a_trace(monkeypatch):
    fake = FakeOrchestrator()
    monkeypatch.setattr(ask_router, "build_orchestrator", lambda: fake)
    client = TestClient(api.app)
    client.post("/ask", json={"query": "What is an ETF?", "debug": True})
    body = client.post("/ask", json={"query": "What is an ETF?", "debug": True}).json()
    assert body["cached"] is True and body["trace"] is None


def test_cache_is_fail_open(monkeypatch):
    class BrokenRedis:
        def get(self, key):
            raise ConnectionError("redis down")

        def set(self, key, value, ex=None):
            raise ConnectionError("redis down")

    monkeypatch.setattr(ask_router, "ask_cache", AskCache(client=BrokenRedis(), ttl_seconds=60))
    fake = FakeOrchestrator()
    monkeypatch.setattr(ask_router, "build_orchestrator", lambda: fake)
    response = TestClient(api.app).post("/ask", json={"query": "What is an ETF?"})
    assert response.status_code == 200 and response.json()["cached"] is False


def test_cache_disabled_by_zero_ttl(monkeypatch):
    monkeypatch.setattr(ask_router, "ask_cache", AskCache(client=FakeRedis(), ttl_seconds=0))
    fake = FakeOrchestrator()
    monkeypatch.setattr(ask_router, "build_orchestrator", lambda: fake)
    client = TestClient(api.app)
    client.post("/ask", json={"query": "What is an ETF?"})
    client.post("/ask", json={"query": "What is an ETF?"})
    assert len(fake.calls) == 2
