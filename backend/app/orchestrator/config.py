from __future__ import annotations

import os
from dataclasses import dataclass

HF_BASE_URL = "https://router.huggingface.co/v1"
HF_CHAT_URL = HF_BASE_URL + "/chat/completions"
# Qwen2.5-7B-Instruct is no longer served by any Inference Provider (checked Nov 9, 2026)
DEFAULT_MODEL = "Qwen/Qwen2.5-72B-Instruct"


@dataclass(frozen=True)
class OrchestratorConfig:
    provider: str = "stub"              # stub | huggingface | openai_compatible
    model: str = DEFAULT_MODEL
    hf_token: str | None = None
    base_url: str = HF_BASE_URL         # any OpenAI-compatible /v1 (HF router, Ollama, vLLM)
    top_k: int = 5
    min_similarity: float = 0.45
    fetch_on_miss: bool = True
    fetch_days: int = 30
    max_tokens: int = 600
    temperature: float = 0.2
    timeout_seconds: float = 60.0
    max_price_tickers: int = 2


def _env_str(name: str) -> str | None:
    return (os.getenv(name) or "").strip() or None


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name) or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name) or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def load_config() -> OrchestratorConfig:
    token = _env_str("HF_TOKEN") or _env_str("LLM_API_KEY")
    base_url = (_env_str("LLM_BASE_URL") or HF_BASE_URL).rstrip("/")
    default_provider = "huggingface" if token else ("openai_compatible" if base_url != HF_BASE_URL else "stub")
    provider = (_env_str("LLM_PROVIDER") or default_provider).lower()
    return OrchestratorConfig(
        provider=provider,
        model=_env_str("LLM_MODEL") or DEFAULT_MODEL,
        hf_token=token,
        base_url=base_url,
        top_k=_env_int("RETRIEVAL_TOP_K", 5),
        min_similarity=_env_float("MIN_SIMILARITY", 0.45),
        fetch_on_miss=_env_bool("FETCH_ON_MISS", True),
        fetch_days=_env_int("FETCH_ON_MISS_DAYS", 30),
        max_tokens=_env_int("LLM_MAX_TOKENS", 600),
        temperature=_env_float("LLM_TEMPERATURE", 0.2),
        timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 60.0),
    )
