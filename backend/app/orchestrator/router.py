import logging

from fastapi import APIRouter, HTTPException

from .cache import AskCache, cache_key
from .config import load_config
from .pipeline import build_orchestrator
from .schemas import AskRequest, AskResponse

log = logging.getLogger("orchestrator.router")

router = APIRouter(tags=["Orchestrator"])

ask_cache = AskCache()


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    key = cache_key(request.query, load_config().model, request.top_k)
    if request.cache:
        hit = ask_cache.get(key)
        if hit is not None:
            return hit
    try:
        response = build_orchestrator().ask(request.query, top_k=request.top_k, debug=request.debug)
    except Exception as exc:  # noqa: BLE001
        log.exception("ask failed")
        raise HTTPException(status_code=503, detail="The assistant is unavailable right now") from exc
    ask_cache.set(key, response)
    return response
