# answer generators: a deterministic stub for tests/offline, and Qwen via the Hugging Face Inference API
from __future__ import annotations

import logging
import re
from typing import Any, Protocol

import httpx

from ..rag_governance.evidence import RetrievalContext
from ..rag_governance.terminology import GlossaryEntry
from .config import HF_BASE_URL, OrchestratorConfig

log = logging.getLogger("orchestrator.generator")


class GeneratorError(RuntimeError):
    """The model could not produce an answer (transport, auth, quota, malformed reply)."""


class Generator(Protocol):
    name: str

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        context: RetrievalContext | None = None,
        glossary: list[GlossaryEntry] | None = None,
    ) -> str: ...


def _first_sentence(text: str, limit: int = 220) -> str:
    text = " ".join(text.split())
    match = re.search(r"(.+?[.!?])(\s|$)", text)
    sentence = match.group(1) if match else text
    return sentence[:limit].rstrip(" ,;:")


class StubGenerator:
    """Deterministic, citation-correct output built from the evidence itself. No network."""

    name = "stub"

    def generate(self, messages, *, context=None, glossary=None) -> str:
        parts: list[str] = []
        if context is not None:
            for chunk in context.evidence_chunks:
                sentence = _first_sentence(chunk.supporting_text)
                if sentence:
                    parts.append(f"{sentence} [{chunk.citation_id}]")
        if not parts:
            parts.append("No definitions or sources were available for this question.")
        return "\n\n".join(parts)


def _error_detail(response: httpx.Response) -> str:
    """Short provider error code/message from a JSON error body; never the raw page."""
    try:
        data = response.json()
    except ValueError:
        return ""
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("code") or err.get("message") or "")[:160]
    if isinstance(err, str):
        return err[:160]
    return ""


class QwenGenerator:
    """OpenAI-compatible chat completion. Default target is the Hugging Face router; any /v1 base url works."""

    name = "huggingface"

    def __init__(self, config: OrchestratorConfig, *, client: httpx.Client | None = None) -> None:
        self.config = config
        self.base_url = (config.base_url or HF_BASE_URL).rstrip("/")
        self.url = self.base_url + "/chat/completions"
        if self.base_url == HF_BASE_URL and not config.hf_token:
            raise GeneratorError("HF_TOKEN is not set")
        if self.base_url != HF_BASE_URL:
            self.name = "openai_compatible"
        self._client = client

    def generate(self, messages, *, context=None, glossary=None) -> str:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self.config.hf_token:
            headers["Authorization"] = f"Bearer {self.config.hf_token}"
        try:
            if self._client is None:
                with httpx.Client(timeout=self.config.timeout_seconds) as client:
                    response = client.post(self.url, json=body, headers=headers)
            else:
                response = self._client.post(self.url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise GeneratorError(f"transport error: {type(exc).__name__}") from exc

        if response.status_code != 200:
            # never log the body verbatim: provider error pages can echo request headers
            detail = _error_detail(response)
            raise GeneratorError(
                f"{self.name} returned HTTP {response.status_code}" + (f" ({detail})" if detail else "")
            )
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GeneratorError("malformed completion response") from exc
        if not isinstance(content, str) or not content.strip():
            raise GeneratorError("empty completion")
        # some Qwen variants emit a reasoning block; keep only the answer
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        return content


def build_generator(config: OrchestratorConfig) -> Generator:
    if config.provider in ("huggingface", "openai_compatible"):
        return QwenGenerator(config)
    if config.provider == "stub":
        return StubGenerator()
    raise GeneratorError(f"unknown LLM_PROVIDER {config.provider!r}")
