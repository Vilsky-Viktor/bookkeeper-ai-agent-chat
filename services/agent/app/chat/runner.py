"""One chat turn end to end, as a stream of SSE chunks: save the user's message,
build the context, run the main graph (workflows/main.py routes it), save the
result, and turn any failure into a user-facing error event."""

import datetime
import logging
import uuid

from fastapi import HTTPException
from langchain_core.messages import AnyMessage

from .. import context
from ..helpers.dates import user_today
from ..integrations.tracing import traced_turn
from ..models.api import ChatRequest
from ..models.message_content import UserMessageContent
from ..models.notices import Notice
from ..models.turns import PreparedTurn, TurnState
from ..storage import chat_db, quotas
from ..workflows import build_main_graph
from . import streaming, turns
from .streaming import sse

log = logging.getLogger("agent")

# Error replies are notices: keys the web app shows in the user's language.
ALREADY_SENT = Notice(key="alreadySent")
REQUEST_FAILED = Notice(key="requestFailed")
CRASHED = Notice(key="turnFailed")


async def _open_thread(conn, uid: str, thread_id: str | None) -> dict:
    if not thread_id:
        return dict(await chat_db.create_thread(conn, uid))

    try:
        uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="thread not found")
    row = await chat_db.get_thread(conn, uid, thread_id)

    if row is None:
        raise HTTPException(status_code=404, detail="thread not found")

    return dict(row)


async def _prepare_turn(conn, uid: str, thread: dict, body: ChatRequest, today: datetime.date) -> PreparedTurn | None:
    """Saves the user's message and builds the model's context. None if this exact
    message (same client_msg_id) was already processed."""
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
        return None

    # Counted only once we know this is a new message, not a resubmit.
    await quotas.increment_and_check_turn(conn, uid)

    if body.receipt_object:
        await quotas.increment_receipt(conn, uid)

    preferences_row = await chat_db.get_preferences(conn, uid)
    preferences = dict(preferences_row) if preferences_row else None

    rows = await chat_db.unsummarized_messages(
        conn, uid, thread_id, thread.get("summarized_through") or 0, turns.MAX_UNSUMMARIZED_MESSAGES
    )
    rows = [r for r in rows if r["seq"] != inserted["seq"]]
    kept_from = context.first_kept_seq(rows)

    return PreparedTurn(
        user_text=user_text,
        user_tokens=user_tokens,
        language=(preferences or {}).get("language") or "en",
        messages=context.build_context(thread, preferences, rows, user_text, today=today),
        trimmed_before_seq=kept_from if rows and kept_from and kept_from > rows[0]["seq"] else None,
    )


async def _run_marker_turn(
    compiled_graph, inputs: dict, marker_ids: list[str], uid: str, thread_id: str, request_id: str
) -> tuple[list[bytes], TurnState]:
    """A "[transaction: <id>]" marker turn must end in an edit/delete call for that id
    (it comes straight from a table row the user clicked, so it's always valid). The
    model occasionally replies "not found" without calling any tool, so the turn is
    buffered instead of streamed — a fabricated reply never reaches the client — and
    retried once from scratch if that happens (nothing to undo: no tool was called)."""
    state = TurnState()

    with traced_turn(uid, thread_id, request_id, tags=["turn"]) as run_config:
        chunks = [c async for c in streaming.run_graph_turn(compiled_graph, inputs, run_config, state)]

    if turns.marker_call_missing(state.tool_calls_made, marker_ids):
        log.warning("transaction-marker turn made no matching tool call, retrying once")
        state = TurnState()

        with traced_turn(uid, thread_id, request_id, tags=["turn", "retry"]) as run_config:
            chunks = [c async for c in streaming.run_graph_turn(compiled_graph, inputs, run_config, state)]

    return chunks, state


async def stream_chat_turn(body: ChatRequest, uid: str, jwt: str, agent_base_url: str):
    """A transaction-marker turn is buffered and checked (_run_marker_turn); every
    other turn streams live. Where it goes — receipt workflow, assistant, or both —
    is the main graph's router's call."""
    request_id = str(uuid.uuid4())
    thread_id: str | None = None
    today = user_today(body.timezone)

    try:
        async with chat_db.uid_conn(uid) as conn:
            thread = await _open_thread(conn, uid, body.thread_id)
            thread_id = str(thread["id"])
            turn = await _prepare_turn(conn, uid, thread, body, today)

        if turn is None:
            yield sse("error", {"notice": ALREADY_SENT.model_dump()})

            return

        graph = build_main_graph(jwt, turn.language, today)
        inputs = {"messages": turn.messages, "receipt_object": body.receipt_object, "note": body.message.strip()}
        marker_ids = context.TRANSACTION_MARKER_RE.findall(turn.user_text)
        state = TurnState()

        if marker_ids and not body.receipt_object:
            chunks, state = await _run_marker_turn(graph, inputs, marker_ids, uid, thread_id, request_id)

            for chunk in chunks:
                yield chunk
        else:
            with traced_turn(uid, thread_id, request_id, tags=["turn"]) as run_config:
                async for chunk in streaming.run_graph_turn(graph, inputs, run_config, state):
                    yield chunk

        await turns.finalize_turn(
            uid,
            thread_id,
            thread,
            state,
            turn.user_tokens,
            agent_base_url,
            trimmed_before_seq=turn.trimmed_before_seq,
        )
        yield sse("done", {"thread_id": thread_id})

    except HTTPException as e:
        log.warning("chat turn returned %s: %s", e.status_code, e.detail)
        # A daily limit has its own notice (see storage/quotas.py); anything else gets a plain
        # "couldn't do that", never the raw detail.
        notice = Notice(key=e.notice_key) if isinstance(e, quotas.LimitReached) else REQUEST_FAILED

        if thread_id is not None:
            await turns.record_turn_failure(uid, thread_id, notice)
        yield sse("error", {"notice": notice.model_dump(), "status": e.status_code})
    except Exception:
        log.exception("chat turn failed")

        if thread_id is not None:
            await turns.record_turn_failure(uid, thread_id, CRASHED)
        yield sse("error", {"notice": CRASHED.model_dump()})
