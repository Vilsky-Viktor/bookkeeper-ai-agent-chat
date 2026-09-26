"""One chat turn end to end, as a stream of SSE chunks: save the user's message,
build the model's context, run the turn (one of three ways, see stream_chat_turn),
save the result, and turn any failure into a user-facing error event."""

import logging
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from langchain_core.messages import AnyMessage

from .. import chat_db, context, quotas, signal
from ..graph import build_graph
from ..langsmith_obs import traced_turn
from ..models.api import ChatRequest
from ..models.message_content import UserMessageContent
from ..models.turns import TurnState
from ..tools import build_tools
from . import receipt_turn, streaming, turns
from .streaming import sse

log = logging.getLogger("agent")

ALREADY_SENT = "That message was already sent — no need to resend it."
COULDNT_DO_THAT = "Sorry, I couldn't do that — please try again."
CRASHED = "Sorry, I ran into a problem and couldn't finish that. Please try again."


@dataclass
class _PreparedTurn:
    user_text: str
    user_tokens: int
    language: str
    messages: list[AnyMessage]
    trimmed_before_seq: int | None  # see context.first_kept_seq


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


async def _prepare_turn(conn, uid: str, thread: dict, body: ChatRequest) -> _PreparedTurn | None:
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
    return _PreparedTurn(
        user_text=user_text,
        user_tokens=user_tokens,
        language=(preferences or {}).get("language") or "en",
        messages=context.build_context(thread, preferences, rows, user_text),
        trimmed_before_seq=kept_from if rows and kept_from and kept_from > rows[0]["seq"] else None,
    )


async def _run_marker_turn(
    compiled_graph, messages: list[AnyMessage], marker_ids: list[str], uid: str, thread_id: str, request_id: str
) -> tuple[list[bytes], TurnState]:
    """A "[transaction: <id>]" marker turn must end in an edit/delete call for that id
    (it comes straight from a table row the user clicked, so it's always valid). The
    model occasionally replies "not found" without calling any tool, so the turn is
    buffered instead of streamed — a fabricated reply never reaches the client — and
    retried once from scratch if that happens (nothing to undo: no tool was called)."""
    state = TurnState()
    with traced_turn(uid, thread_id, request_id, tags=["turn"]) as run_config:
        chunks = [c async for c in streaming.run_graph_turn(compiled_graph, messages, run_config, state)]
    if turns.marker_call_missing(state.tool_calls_made, marker_ids):
        log.warning("transaction-marker turn made no matching tool call, retrying once")
        state = TurnState()
        with traced_turn(uid, thread_id, request_id, tags=["turn", "retry"]) as run_config:
            chunks = [c async for c in streaming.run_graph_turn(compiled_graph, messages, run_config, state)]
    return chunks, state


async def stream_chat_turn(body: ChatRequest, uid: str, jwt: str, x_client_id: str | None, agent_base_url: str):
    """The turn runs one of three ways: a receipt upload with no text skips the model
    (receipt_turn.py); a transaction-marker turn is buffered and checked
    (_run_marker_turn); anything else streams the graph's output live."""
    request_id = str(uuid.uuid4())
    thread_id: str | None = None
    try:
        async with chat_db.uid_conn(uid) as conn:
            thread = await _open_thread(conn, uid, body.thread_id)
            thread_id = str(thread["id"])
            turn = await _prepare_turn(conn, uid, thread, body)
        if turn is None:
            yield sse("error", {"message": ALREADY_SENT})
            return

        tools = build_tools(jwt, x_client_id, turn.language)
        marker_ids = context.TRANSACTION_MARKER_RE.findall(turn.user_text)
        state = TurnState()

        if body.receipt_object and not body.message.strip():
            with traced_turn(uid, thread_id, request_id, tags=["turn", "receipt-direct"]) as run_config:
                async for chunk in receipt_turn.run_receipt_turn(
                    tools, body.receipt_object, turn.language, run_config, state
                ):
                    yield chunk
        elif marker_ids:
            chunks, state = await _run_marker_turn(
                build_graph(tools), turn.messages, marker_ids, uid, thread_id, request_id
            )
            for chunk in chunks:
                yield chunk
        else:
            with traced_turn(uid, thread_id, request_id, tags=["turn"]) as run_config:
                async for chunk in streaming.run_graph_turn(build_graph(tools), turn.messages, run_config, state):
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
        await signal.bump_async(uid, [f"thread_versions.{thread_id}"], x_client_id)
        yield sse("done", {"thread_id": thread_id})

    except HTTPException as e:
        log.warning("chat turn returned %s: %s", e.status_code, e.detail)
        # Quota messages (429) are already user-facing sentences (see quotas.py);
        # anything else gets a plain message instead of the raw detail.
        message = e.detail if e.status_code == 429 else COULDNT_DO_THAT
        if thread_id is not None:
            await turns.record_turn_failure(uid, thread_id, message)
        yield sse("error", {"message": message, "status": e.status_code})
    except Exception:
        log.exception("chat turn failed")
        if thread_id is not None:
            await turns.record_turn_failure(uid, thread_id, CRASHED)
        yield sse("error", {"message": CRASHED})
