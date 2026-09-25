import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from . import chat_db, context, llm, quotas, signal, storage
from .auth import bearer_token, require_uid
from .chat import streaming, turns
from .graph import build_graph
from .langsmith_obs import traced_turn
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
)
from .models.message_content import UserMessageContent
from .models.turns import TurnState
from .service_auth import require_service_caller
from .summarize import run_summarize
from .tools import build_tools

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agent")

# Single source of truth lives in context/messages.py (build_context() also needs it
# to force a marker's id into the working-set text). Re-exported here since chat()
# below also needs it, for the retry-on-no-matching-tool-call logic.
TRANSACTION_MARKER_RE = context.TRANSACTION_MARKER_RE


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
async def create_upload_target(uid: str = Depends(require_uid)):
    """Returns a signed GCS URL in production, a direct fake-gcs URL locally. The
    frontend PUTs/POSTs the image there, then sends the returned `object` path back as
    `receipt_object` on the next /api/chat/chat call."""
    object_id = str(uuid.uuid4())
    return storage.upload_target(uid, object_id)


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
    # Cloud Run always terminates TLS at its own edge and forwards over plain HTTP
    # internally with the original external Host header preserved as-is — so this is
    # reliably this service's own real public origin, no proxy-header trust config
    # needed (unlike scheme, which uvicorn would need --forwarded-allow-ips to trust
    # from X-Forwarded-Proto; hardcoding https sidesteps that entirely, and is always
    # correct for a *.run.app URL). Used by finalize_turn -> tasks.enqueue_summarize
    # so Cloud Tasks knows where to POST back to — avoids a Terraform self-reference
    # (a Cloud Run service can't read its own .uri from within its own resource
    # block) that an AGENT_URL env var would otherwise require.
    agent_base_url = f"https://{request.headers.get('host', '')}"

    async def event_stream():
        request_id = str(uuid.uuid4())
        thread_id: str | None = None
        try:
            async with chat_db.uid_conn(uid) as conn:
                if not body.thread_id:
                    thread_row = await chat_db.create_thread(conn, uid)
                    thread = dict(thread_row)
                else:
                    try:
                        uuid.UUID(body.thread_id)
                    except ValueError:
                        raise HTTPException(status_code=404, detail="thread not found")
                    thread_row = await chat_db.get_thread(conn, uid, body.thread_id)
                    if thread_row is None:
                        raise HTTPException(status_code=404, detail="thread not found")
                    thread = dict(thread_row)
                thread_id = str(thread["id"])

                user_text = body.message
                if body.receipt_object:
                    user_text = f"{user_text}\n\n[uploaded receipt: {body.receipt_object}]"

                user_tokens = context.count_tokens(user_text)
                inserted = await chat_db.insert_message(
                    conn,
                    uid,
                    thread_id,
                    "user",
                    UserMessageContent(text=user_text).model_dump(),
                    user_tokens,
                    client_msg_id=body.client_msg_id,
                )
                if inserted is None:
                    yield streaming._sse("error", {"message": "That message was already sent — no need to resend it."})
                    return

                # Quota and receipt counters only advance once we know this is a new
                # message, not a resubmit of one already processed.
                await quotas.increment_and_check_turn(conn, uid)
                if body.receipt_object:
                    await quotas.increment_receipt(conn, uid)

                preferences_row = await chat_db.get_preferences(conn, uid)
                preferences = dict(preferences_row) if preferences_row else None

                recent_rows = await chat_db.recent_messages(conn, uid, thread_id, turns.RECENT_MESSAGE_LIMIT)
                recent_rows = [r for r in recent_rows if r["seq"] != inserted["seq"]]
                messages = context.build_context(thread, preferences, recent_rows, user_text)

            language = (preferences or {}).get("language") or "en"
            tools = build_tools(jwt, x_client_id, language)
            compiled_graph = build_graph(tools)

            marker_ids = TRANSACTION_MARKER_RE.findall(user_text)
            state = TurnState()

            if marker_ids:
                # A "[transaction: <id>]" marker turn should always end in exactly
                # one matching edit_transaction/delete_transaction call — the id
                # comes straight from a table row the user clicked, so it's always
                # valid. Observed failure mode: the model occasionally replies "not
                # found"/"invalid id" without ever calling the tool at all (an empty
                # tool_calls list). Buffer instead of streaming live, so a fabricated
                # reply never reaches the client before it's checked, and retry once
                # (silently, from scratch — the failed attempt made no tool calls, so
                # there's nothing to undo) if this exact failure signature shows up.
                with traced_turn(uid, thread_id, request_id, tags=["turn"]) as run_config:
                    buffered = [c async for c in streaming._run_turn(compiled_graph, messages, run_config, state)]
                if turns._marker_call_missing(state.tool_calls_made, marker_ids):
                    log.warning("transaction-marker turn made no matching tool call, retrying once")
                    state = TurnState()
                    with traced_turn(uid, thread_id, request_id, tags=["turn", "retry"]) as run_config:
                        buffered = [c async for c in streaming._run_turn(compiled_graph, messages, run_config, state)]
                for chunk in buffered:
                    yield chunk
            else:
                with traced_turn(uid, thread_id, request_id, tags=["turn"]) as run_config:
                    async for chunk in streaming._run_turn(compiled_graph, messages, run_config, state):
                        yield chunk

            await turns.finalize_turn(uid, thread_id, thread, state, user_tokens, agent_base_url)

            await signal.bump_async(uid, [f"thread_versions.{thread_id}"], x_client_id)
            yield streaming._sse("done", {"thread_id": thread_id})

        except HTTPException as e:
            log.warning("chat turn returned %s: %s", e.status_code, e.detail)
            # Quota messages (429) are already written as user-facing sentences (see
            # quotas.py); everything else gets a plain, non-technical message instead
            # of surfacing the raw detail (e.g. "thread not found") in the chat.
            message = e.detail if e.status_code == 429 else "Sorry, I couldn't do that — please try again."
            if thread_id is not None:
                await turns._record_turn_failure(uid, thread_id, message)
            yield streaming._sse("error", {"message": message, "status": e.status_code})
        except Exception:
            log.exception("chat turn failed")
            message = "Sorry, I ran into a problem and couldn't finish that. Please try again."
            if thread_id is not None:
                await turns._record_turn_failure(uid, thread_id, message)
            yield streaming._sse("error", {"message": message})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# --- internal ------------------------------------------------------------------------


@app.post("/internal/summarize", dependencies=[Depends(require_service_caller)], response_model=HealthzResponse)
async def summarize_endpoint(body: SummarizeRequest):
    await run_summarize(body.uid, body.thread_id, body.through_seq)
    return HealthzResponse(ok=True)
