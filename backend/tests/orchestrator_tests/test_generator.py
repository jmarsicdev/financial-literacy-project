import json

import httpx
import pytest

from app.orchestrator.config import HF_BASE_URL, HF_CHAT_URL, OrchestratorConfig
from app.orchestrator.generator import GeneratorError, QwenGenerator, StubGenerator, build_generator
from app.rag_governance.evidence import build_semantic_context

ROWS = [
    {
        "id": 1, "title": "ETF basics", "source_url": "https://www.sec.gov/etf",
        "chunk_text": "An ETF pools money from investors. It trades on an exchange.",
        "publisher": "SEC", "fetched_at": "2026-11-08",
    },
    {
        "id": 2, "title": "Index funds", "source_url": "https://www.sec.gov/index",
        "chunk_text": "An index fund tracks a market index! Costs are usually low.",
        "publisher": "SEC", "fetched_at": "2026-11-08",
    },
]


def test_stub_generator_cites_each_evidence_chunk_in_order():
    context = build_semantic_context("What is an ETF?", ROWS)
    text = StubGenerator().generate([], context=context)
    assert text == "An ETF pools money from investors. [1]\n\nAn index fund tracks a market index! [2]"


def test_stub_generator_without_evidence_says_so():
    assert "No definitions or sources" in StubGenerator().generate([], context=None)


def _config(**overrides):
    base = dict(provider="huggingface", hf_token="test-token", model="Qwen/Test", max_tokens=50, temperature=0.1)
    base.update(overrides)
    return OrchestratorConfig(**base)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_qwen_generator_posts_openai_style_body_and_returns_content():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "  An ETF is a fund [1].  "}}]})

    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]
    text = QwenGenerator(_config(), client=_client(handler)).generate(messages)

    assert text == "An ETF is a fund [1]."
    assert seen["url"] == HF_CHAT_URL
    assert seen["auth"] == "Bearer test-token"
    assert seen["body"]["model"] == "Qwen/Test"
    assert seen["body"]["messages"] == messages
    assert seen["body"]["max_tokens"] == 50 and seen["body"]["stream"] is False


def test_qwen_generator_strips_reasoning_blocks():
    handler = lambda request: httpx.Response(  # noqa: E731
        200, json={"choices": [{"message": {"content": "<think>hmm</think>\nFinal answer [1]."}}]}
    )
    assert QwenGenerator(_config(), client=_client(handler)).generate([]) == "Final answer [1]."


@pytest.mark.parametrize("status", [401, 402, 429, 503])
def test_qwen_generator_raises_on_http_errors(status):
    handler = lambda request: httpx.Response(status, text="<html>error page</html>")  # noqa: E731
    with pytest.raises(GeneratorError) as excinfo:
        QwenGenerator(_config(), client=_client(handler)).generate([])
    assert str(status) in str(excinfo.value)
    assert "error page" not in str(excinfo.value)


def test_qwen_generator_raises_on_malformed_or_empty_reply():
    with pytest.raises(GeneratorError):
        QwenGenerator(_config(), client=_client(lambda r: httpx.Response(200, json={"nope": 1}))).generate([])
    with pytest.raises(GeneratorError):
        QwenGenerator(_config(), client=_client(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})
        )).generate([])


def test_qwen_generator_wraps_transport_errors():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(GeneratorError, match="transport error"):
        QwenGenerator(_config(), client=_client(handler)).generate([])


def test_qwen_generator_requires_token_only_for_hugging_face():
    with pytest.raises(GeneratorError, match="HF_TOKEN"):
        QwenGenerator(_config(hf_token=None))

    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "local answer [1]."}}]})

    local = QwenGenerator(_config(hf_token=None, base_url="http://localhost:11434/v1"), client=_client(handler))
    assert local.name == "openai_compatible"
    assert local.generate([]) == "local answer [1]."
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["auth"] is None


def test_qwen_generator_reports_provider_error_code():
    handler = lambda request: httpx.Response(  # noqa: E731
        402, json={"error": "Purchase pre-paid credits to continue using Inference Providers."}
    )
    with pytest.raises(GeneratorError, match="402 \\(Purchase pre-paid credits"):
        QwenGenerator(_config(), client=_client(handler)).generate([])

    handler = lambda request: httpx.Response(  # noqa: E731
        400, json={"error": {"message": "not supported", "code": "model_not_supported"}}
    )
    with pytest.raises(GeneratorError, match="model_not_supported"):
        QwenGenerator(_config(), client=_client(handler)).generate([])


def test_build_generator_selects_by_provider():
    assert isinstance(build_generator(OrchestratorConfig(provider="stub")), StubGenerator)
    assert isinstance(build_generator(_config()), QwenGenerator)
    assert isinstance(build_generator(_config(provider="openai_compatible", hf_token=None, base_url="http://x/v1")), QwenGenerator)
    with pytest.raises(GeneratorError):
        build_generator(OrchestratorConfig(provider="other"))
