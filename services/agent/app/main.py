import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import chat_db, context, llm, quotas, signal, storage, tasks
from .auth import bearer_token, require_uid
from .graph import build_graph, initial_state
from .langfuse_obs import traced_turn
from .languages import SUPPORTED_LANGUAGES
from .service_auth import require_service_caller
from .summarize import run_summarize
from .tools import build_tools

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agent")

RECENT_MESSAGE_LIMIT = 40  # rows fetched before token-budget trimming (context.py)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await chat_db.init_pool()
    yield
    await chat_db.close_pool()


app = FastAPI(title="agent-service", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# --- threads -----------------------------------------------------------------------


@app.get("/api/chat/threads")
async def list_threads(uid: str = Depends(require_uid)):
    async with chat_db.uid_conn(uid) as conn:
        rows = await chat_db.list_threads(conn, uid)
    return {"items": [dict(r) for r in rows]}


@app.post("/api/chat/threads", status_code=201)
async def create_thread_endpoint(
    uid: str = Depends(require_uid),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
):
    async with chat_db.uid_conn(uid) as conn:
        thread = await chat_db.create_thread(conn, uid)
    await signal.bump_async(uid, ["threads_version"], x_client_id)
    return {**thread, "id": str(thread["id"])}


def _message_out(row) -> dict:
    content = row["content"]
    content = json.loads(content) if isinstance(content, str) else content
    return {
        "seq": row["seq"],
        "role": row["role"],
        "content": content,
        "created_at": row["created_at"].isoformat(),
    }


@app.get("/api/chat/threads/{thread_id}/messages")
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
    return {"items": [_message_out(r) for r in rows], "has_more": has_more}


# --- preferences ---------------------------------------------------------------------


class PreferencesUpdate(BaseModel):
    language: str


@app.get("/api/chat/preferences")
async def get_preferences_endpoint(uid: str = Depends(require_uid)):
    async with chat_db.uid_conn(uid) as conn:
        row = await chat_db.get_preferences(conn, uid)
    return {
        "language": row["language"] if row else "en",
        "default_currency": row["default_currency"] if row else None,
    }


@app.put("/api/chat/preferences")
async def update_preferences_endpoint(body: PreferencesUpdate, uid: str = Depends(require_uid)):
    if body.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"unsupported language: {body.language}")
    async with chat_db.uid_conn(uid) as conn:
        row = await chat_db.set_language(conn, uid, body.language)
    return {"language": row["language"], "default_currency": row["default_currency"]}


# --- receipt uploads ------------------------------------------------------------------


@app.post("/api/chat/uploads")
async def create_upload_target(uid: str = Depends(require_uid)):
    """Returns a signed GCS URL in production, a direct fake-gcs URL locally. The
    frontend PUTs/POSTs the image there, then sends the returned `object` path back as
    `receipt_object` on the next /api/chat/chat call."""
    object_id = str(uuid.uuid4())
    return storage.upload_target(uid, object_id)


# --- voice input -----------------------------------------------------------------------


@app.post("/api/chat/transcribe")
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
    return {"text": resp.text}


# --- chat (SSE) ----------------------------------------------------------------------


class ChatRequest(BaseModel):
    thread_id: str | None = None
    message: str
    client_msg_id: str | None = None
    receipt_object: str | None = None  # gs object path from a just-completed upload


def _sse(event: str | None, data: dict) -> bytes:
    lines = [f"event: {event}"] if event else []
    lines.append(f"data: {json.dumps(data, default=str)}")
    return ("\n".join(lines) + "\n\n").encode()


def _working_set_entries(tool_name: str, result: dict) -> dict:
    if not isinstance(result, dict):
        return {}

    def label(row: dict) -> str:
        what = row.get("description") or row.get("category") or "transaction"
        return f"{what}, {row.get('amount')} {row.get('currency')}, {row.get('occurred_on')}"

    if tool_name in ("add_transaction", "edit_transaction") and "id" in result:
        return {result["id"]: label(result)}
    if tool_name == "query_transactions" and isinstance(result.get("items"), list):
        return {i["id"]: label(i) for i in result["items"][:20] if "id" in i}
    return {}


def _cap_working_set(ws: dict, limit: int = 20) -> dict:
    if len(ws) <= limit:
        return ws
    for k in list(ws.keys())[: len(ws) - limit]:
        ws.pop(k, None)
    return ws


@app.post("/api/chat/chat")
async def chat(
    body: ChatRequest,
    uid: str = Depends(require_uid),
    jwt: str = Depends(bearer_token),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
):
    async def event_stream():
        request_id = str(uuid.uuid4())
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
                    {"text": user_text},
                    user_tokens,
                    client_msg_id=body.client_msg_id,
                )
                if inserted is None:
                    yield _sse("error", {"message": "That message was already sent — no need to resend it."})
                    return

                # Quota and receipt counters only advance once we know this is a new
                # message, not a resubmit of one already processed.
                await quotas.increment_and_check_turn(conn, uid)
                if body.receipt_object:
                    await quotas.increment_receipt(conn, uid)

                preferences_row = await chat_db.get_preferences(conn, uid)
                preferences = dict(preferences_row) if preferences_row else None

                recent_rows = await chat_db.recent_messages(conn, uid, thread_id, RECENT_MESSAGE_LIMIT)
                recent_rows = [r for r in recent_rows if r["seq"] != inserted["seq"]]
                messages = context.build_context(thread, preferences, recent_rows, user_text)

            language = (preferences or {}).get("language") or "en"
            tools = build_tools(jwt, x_client_id, language)
            compiled_graph = build_graph(tools)

            assistant_text_parts: list[str] = []
            tool_calls_made: list[dict] = []
            tool_results: list[tuple] = []  # (name, tool_call_id, parsed_result)
            total_tokens_used = 0

            with traced_turn(uid, thread_id, request_id, tags=["turn"]) as handler:
                async for event in compiled_graph.astream_events(
                    initial_state(messages), config={"callbacks": [handler]}, version="v2"
                ):
                    kind = event["event"]

                    if kind == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        text = chunk.content if isinstance(chunk.content, str) else ""
                        if text:
                            assistant_text_parts.append(text)
                            yield _sse(None, {"type": "token", "text": text})

                    elif kind == "on_chat_model_end":
                        output = event["data"].get("output")
                        usage = getattr(output, "usage_metadata", None)
                        if usage:
                            total_tokens_used += usage.get("total_tokens", 0)
                        round_tool_calls = getattr(output, "tool_calls", None) or []
                        for c in round_tool_calls:
                            tool_calls_made.append({"id": c.get("id"), "name": c.get("name"), "args": c.get("args")})
                        if round_tool_calls:
                            # This round's streamed text (if any) was narration before
                            # a tool call, not the final answer — e.g. "I'll export
                            # this now." Without discarding it, it gets concatenated
                            # with the real answer that follows the tool result, with
                            # no separator, reading as a garbled double answer.
                            assistant_text_parts.clear()
                            yield _sse("reset_pending", {"type": "reset_pending"})

                    elif kind == "on_tool_end":
                        output = event["data"].get("output")
                        name = event.get("name", "")
                        tool_call_id = getattr(output, "tool_call_id", None)
                        raw = getattr(output, "content", "{}")
                        try:
                            parsed = json.loads(raw) if isinstance(raw, str) else raw
                        except (TypeError, ValueError):
                            parsed = {"result": raw}
                        if not isinstance(parsed, dict):
                            parsed = {"result": parsed}
                        ui_event = parsed.pop("ui_event", None)
                        tool_results.append((name, tool_call_id, parsed))

                        if ui_event == "table_changed":
                            payload = {"type": "table_changed", "transaction": parsed}
                        elif ui_event == "filter_set":
                            payload = {"type": "filter_set", "filter": parsed.get("filter", {})}
                        elif ui_event == "receipt_proposed":
                            payload = {
                                "type": "receipt_proposed",
                                "items": parsed.get("items", []),
                                "receipt_uri": parsed.get("receipt_uri"),
                            }
                        elif ui_event == "export_ready":
                            payload = {"type": "export_ready"}
                        else:
                            payload = None
                        if payload:
                            yield _sse(ui_event, payload)

            assistant_text = "".join(assistant_text_parts)

            async with chat_db.uid_conn(uid) as conn:
                assistant_content = {"text": assistant_text, "tool_calls": tool_calls_made}
                await chat_db.insert_message(
                    conn, uid, thread_id, "assistant", assistant_content, context.count_tokens(assistant_text)
                )

                working_set = thread.get("working_set")
                working_set = json.loads(working_set) if isinstance(working_set, str) else (working_set or {})

                for name, tool_call_id, result in tool_results:
                    tool_content = {"tool_call_id": tool_call_id, "name": name, "result": result}
                    compact = context.compact_tool_result(name, result)
                    await chat_db.insert_message(
                        conn,
                        uid,
                        thread_id,
                        "tool",
                        tool_content,
                        context.count_tokens(json.dumps(result, default=str)),
                        compact=compact,
                    )
                    working_set.update(_working_set_entries(name, result))

                working_set = _cap_working_set(working_set)
                await chat_db.update_working_set(conn, uid, thread_id, working_set)
                await chat_db.touch_thread(conn, uid, thread_id)
                await quotas.add_tokens(
                    conn, uid, total_tokens_used or (user_tokens + context.count_tokens(assistant_text))
                )

                latest = await conn.fetchrow(
                    "SELECT max(seq) AS max_seq FROM messages WHERE uid=$1 AND thread_id=$2", uid, thread_id
                )
                latest_seq = latest["max_seq"] or 0
                summarized_through = thread.get("summarized_through") or 0

            # Off the hot path: fold anything that fell out of the recent-message
            # window into the rolling summary (architecture doc, p. 9, technique 3).
            if latest_seq - summarized_through > RECENT_MESSAGE_LIMIT:
                await tasks.enqueue_summarize(uid, thread_id, latest_seq - RECENT_MESSAGE_LIMIT)

            await signal.bump_async(uid, [f"thread_versions.{thread_id}"], x_client_id)
            yield _sse("done", {"thread_id": thread_id})

        except HTTPException as e:
            log.warning("chat turn returned %s: %s", e.status_code, e.detail)
            # Quota messages (429) are already written as user-facing sentences (see
            # quotas.py); everything else gets a plain, non-technical message instead
            # of surfacing the raw detail (e.g. "thread not found") in the chat.
            message = e.detail if e.status_code == 429 else "Sorry, I couldn't do that — please try again."
            yield _sse("error", {"message": message, "status": e.status_code})
        except Exception:
            log.exception("chat turn failed")
            yield _sse(
                "error",
                {"message": "Sorry, I ran into a problem and couldn't finish that. Please try again."},
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# --- internal ------------------------------------------------------------------------


class SummarizeRequest(BaseModel):
    uid: str
    thread_id: str
    through_seq: int


@app.post("/internal/summarize", dependencies=[Depends(require_service_caller)])
async def summarize_endpoint(body: SummarizeRequest):
    await run_summarize(body.uid, body.thread_id, body.through_seq)
    return {"ok": True}
