import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from . import chat_db, llm, signal, storage
from .auth import bearer_token, require_uid
from .chat import runner
from .languages import SUPPORTED_LANGUAGES
from .models.api import (
    ChatRequest,
    HealthzResponse,
    MessageOut,
    MessagesPageResponse,
    PreferencesOut,
    PreferencesUpdate,
    SummarizeRequest,
    ThreadOut,
    ThreadsListResponse,
    ThreadSummary,
    TranscribeResponse,
    UploadTargetOut,
    UploadTargetRequest,
)
from .service_auth import require_service_caller
from .summarize import run_summarize

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await chat_db.init_pool()
    yield
    await chat_db.close_pool()


app = FastAPI(title="agent-service", lifespan=lifespan)


@app.get("/healthz", response_model=HealthzResponse)
async def healthz():
    return HealthzResponse(ok=True)


# --- threads -----------------------------------------------------------------------


@app.get("/api/chat/threads", response_model=ThreadsListResponse)
async def list_threads(uid: str = Depends(require_uid)):
    async with chat_db.uid_conn(uid) as conn:
        rows = await chat_db.list_threads(conn, uid)
    # asyncpg decodes the uuid column as a real uuid.UUID, not str — ThreadSummary.id
    # is str (matching what the wire format has always been), so this needs the same
    # explicit str() conversion create_thread_endpoint below already does.
    return ThreadsListResponse(items=[ThreadSummary(**{**dict(r), "id": str(r["id"])}) for r in rows])


@app.post("/api/chat/threads", status_code=201, response_model=ThreadOut)
async def create_thread_endpoint(
    uid: str = Depends(require_uid),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
):
    async with chat_db.uid_conn(uid) as conn:
        thread = await chat_db.create_thread(conn, uid)
    await signal.bump_async(uid, ["threads_version"], x_client_id)
    # asyncpg doesn't decode jsonb columns on its own — working_set comes back as the
    # raw JSON text, same as context/__init__.py's build_context() already has to
    # handle defensively.
    working_set = thread["working_set"]
    if isinstance(working_set, str):
        working_set = json.loads(working_set) if working_set else {}
    return ThreadOut(**{**thread, "id": str(thread["id"]), "working_set": working_set})


def _message_out(row) -> MessageOut:
    content = row["content"]
    content = json.loads(content) if isinstance(content, str) else content
    return MessageOut(
        seq=row["seq"],
        role=row["role"],
        content=content,
        created_at=row["created_at"].isoformat(),
    )


@app.get("/api/chat/threads/{thread_id}/messages", response_model=MessagesPageResponse)
async def get_messages(
    thread_id: str,
    before_seq: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    uid: str = Depends(require_uid),
):
    async with chat_db.uid_conn(uid) as conn:
        thread = await chat_db.get_thread(conn, uid, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="thread not found")
        rows, has_more = await chat_db.messages_page(conn, uid, thread_id, before_seq, limit)
    return MessagesPageResponse(items=[_message_out(r) for r in rows], has_more=has_more)


# --- preferences ---------------------------------------------------------------------


@app.get("/api/chat/preferences", response_model=PreferencesOut)
async def get_preferences_endpoint(uid: str = Depends(require_uid)):
    async with chat_db.uid_conn(uid) as conn:
        row = await chat_db.get_preferences(conn, uid)
    return PreferencesOut(
        language=row["language"] if row else "en",
        default_currency=row["default_currency"] if row else None,
    )


@app.put("/api/chat/preferences", response_model=PreferencesOut)
async def update_preferences_endpoint(body: PreferencesUpdate, uid: str = Depends(require_uid)):
    if body.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"unsupported language: {body.language}")
    async with chat_db.uid_conn(uid) as conn:
        row = await chat_db.set_language(conn, uid, body.language)
    return PreferencesOut(language=row["language"], default_currency=row["default_currency"])


# --- receipt uploads ------------------------------------------------------------------


@app.post("/api/chat/uploads", response_model=UploadTargetOut)
async def create_upload_target(body: UploadTargetRequest | None = None, uid: str = Depends(require_uid)):
    """Returns a signed GCS URL in production, a direct fake-gcs URL locally. The
    frontend PUTs/POSTs the file there, then sends the returned `object` path back as
    `receipt_object` on the next /api/chat/chat call."""
    content_type = body.content_type if body else "image/jpeg"
    return storage.upload_target(uid, str(uuid.uuid4()), content_type)


# --- voice input -----------------------------------------------------------------------


@app.post("/api/chat/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(file: UploadFile = File(...), uid: str = Depends(require_uid)):
    """Transcribes a recorded voice message to text — the frontend then drops that
    text into the message box for the user to review/edit before sending, same as any
    typed message. Doesn't touch quotas itself; the actual chat turn it feeds into
    does."""
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty audio")

    async with chat_db.uid_conn(uid) as conn:
        preferences_row = await chat_db.get_preferences(conn, uid)
    language = (dict(preferences_row) if preferences_row else {}).get("language")

    # The SDK's `language` param takes a plain str (or must be omitted entirely) — it
    # doesn't accept None as "no hint", so this is only added when there's a real value.
    transcribe_kwargs = {"language": language} if language in SUPPORTED_LANGUAGES else {}
    try:
        resp = await llm.transcribe_client().audio.transcriptions.create(
            model=llm.TRANSCRIBE_MODEL,
            file=(file.filename or "audio.webm", audio_bytes, file.content_type or "audio/webm"),
            **transcribe_kwargs,
        )
    except Exception as e:
        log.warning("transcription failed: %s", e)
        raise HTTPException(status_code=502, detail="Couldn't transcribe that — please try again.") from e
    return TranscribeResponse(text=resp.text)


# --- chat (SSE) ----------------------------------------------------------------------


@app.post("/api/chat/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    uid: str = Depends(require_uid),
    jwt: str = Depends(bearer_token),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
):
    # This service's own public origin, for Cloud Tasks to POST summaries back to.
    # Cloud Run terminates TLS at its edge and preserves the external Host header, so
    # Host plus a hardcoded https is reliable — and avoids an AGENT_URL env var, which
    # Terraform can't set (a Cloud Run service can't reference its own URL).
    agent_base_url = f"https://{request.headers.get('host', '')}"
    return StreamingResponse(
        runner.stream_chat_turn(body, uid, jwt, x_client_id, agent_base_url), media_type="text/event-stream"
    )


# --- internal ------------------------------------------------------------------------


@app.post("/internal/summarize", dependencies=[Depends(require_service_caller)], response_model=HealthzResponse)
async def summarize_endpoint(body: SummarizeRequest):
    await run_summarize(body.uid, body.thread_id, body.through_seq)
    return HealthzResponse(ok=True)
