from fastapi.testclient import TestClient

from app import main as api
from app.orchestrator import router as ask_router
from app.orchestrator.schemas import AskResponse, GovernanceOut


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
