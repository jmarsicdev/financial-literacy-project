import logging

from fastapi import APIRouter, HTTPException

from .pipeline import build_orchestrator
from .schemas import AskRequest, AskResponse

log = logging.getLogger("orchestrator.router")

router = APIRouter(tags=["Orchestrator"])


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    try:
        return build_orchestrator().ask(request.query, top_k=request.top_k, debug=request.debug)
    except Exception as exc:  # noqa: BLE001
        log.exception("ask failed")
        raise HTTPException(status_code=503, detail="The assistant is unavailable right now") from exc
