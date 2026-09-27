"""One chat turn, streamed as SSE (chat/runner.py does the work)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..auth import bearer_token, require_uid
from ..chat import runner
from ..models.api import ChatRequest

router = APIRouter()


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    uid: str = Depends(require_uid),
    jwt: str = Depends(bearer_token),
):
    # This service's own public origin, for Cloud Tasks to POST summaries back to.
    # Cloud Run terminates TLS at its edge and preserves the external Host header, so
    # Host plus a hardcoded https is reliable — and avoids an AGENT_URL env var, which
    # Terraform can't set (a Cloud Run service can't reference its own URL).
    agent_base_url = f"https://{request.headers.get('host', '')}"

    return StreamingResponse(runner.stream_chat_turn(body, uid, jwt, agent_base_url), media_type="text/event-stream")
