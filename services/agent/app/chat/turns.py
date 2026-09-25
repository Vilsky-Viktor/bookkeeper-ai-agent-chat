"""Turn bookkeeping: deciding whether a transaction-marker turn actually did what it
claimed, recording a fallback assistant message when a turn fails outright, and
persisting a completed turn's results (assistant message, tool results, working set,
quota, summarization trigger)."""

import json
import logging

from .. import chat_db, context, quotas, tasks
from ..models.message_content import AssistantMessageContent, ToolMessageContent
from ..models.turns import ToolCallRecord, TurnState

log = logging.getLogger("agent")

RECENT_MESSAGE_LIMIT = 40  # rows fetched before token-budget trimming (context/__init__.py)


def _marker_call_missing(tool_calls_made: list[ToolCallRecord], marker_ids: list[str]) -> bool:
    return not any(
        tc.name in ("edit_transaction", "delete_transaction") and (tc.args or {}).get("transaction_id") in marker_ids
        for tc in tool_calls_made
    )


async def _record_turn_failure(uid: str, thread_id: str, note: str) -> None:
    """Called when a turn fails after its user message was already saved (a crash, a
    quota 429, anything reaching the except blocks below with thread_id set) —
    without this, the thread's next turn sees two consecutive human messages with no
    assistant reply between them, which is a much stronger source of confusion for
    the model than ordinary response variance. Observed directly: an unhandled crash
    left exactly this kind of orphaned message behind, and every retry of the same
    edit in that thread afterward failed the same way, even though the same context
    replayed outside that thread succeeded."""
    try:
        async with chat_db.uid_conn(uid) as conn:
            await chat_db.insert_message(
                conn,
                uid,
                thread_id,
                "assistant",
                AssistantMessageContent(text=note, tool_calls=[]).model_dump(),
                context.count_tokens(note),
            )
    except Exception:
        log.exception("failed to record fallback assistant message after a failed turn")


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


async def finalize_turn(uid: str, thread_id: str, thread: dict, state: TurnState, user_tokens: int) -> None:
    """Persists a completed turn: assistant message + tool result messages, updates
    the working set, touches the thread, advances the token quota, and enqueues
    rolling-summary work if the unsummarized tail has grown past
    RECENT_MESSAGE_LIMIT."""
    assistant_text = "".join(state.assistant_text_parts)

    async with chat_db.uid_conn(uid) as conn:
        assistant_content = AssistantMessageContent(text=assistant_text, tool_calls=state.tool_calls_made)
        await chat_db.insert_message(
            conn, uid, thread_id, "assistant", assistant_content.model_dump(), context.count_tokens(assistant_text)
        )

        working_set = thread.get("working_set")
        working_set = json.loads(working_set) if isinstance(working_set, str) else (working_set or {})

        for tool_result in state.tool_results:
            name, tool_call_id, result = tool_result.name, tool_result.tool_call_id, tool_result.result
            # tool_call_id is near-always present (LangGraph's ToolNode always sets
            # it) — the "" fallback only covers the defensive getattr(..., None) in
            # streaming.py ever actually returning None, which ToolMessageContent
            # doesn't model as optional since nothing downstream treats a missing id
            # as meaningfully different from an empty one.
            tool_content = ToolMessageContent(tool_call_id=tool_call_id or "", name=name, result=result)
            compact = context.compact_tool_result(name, result)
            await chat_db.insert_message(
                conn,
                uid,
                thread_id,
                "tool",
                tool_content.model_dump(),
                context.count_tokens(json.dumps(result, default=str)),
                compact=compact,
            )
            working_set.update(_working_set_entries(name, result))

        working_set = _cap_working_set(working_set)
        await chat_db.update_working_set(conn, uid, thread_id, working_set)
        await chat_db.touch_thread(conn, uid, thread_id)
        await quotas.add_tokens(
            conn, uid, state.total_tokens_used or (user_tokens + context.count_tokens(assistant_text))
        )

        latest = await conn.fetchrow(
            "SELECT max(seq) AS max_seq FROM messages WHERE uid=$1 AND thread_id=$2", uid, thread_id
        )
        latest_seq = latest["max_seq"] or 0
        summarized_through = thread.get("summarized_through") or 0

    # Off the hot path: fold anything that fell out of the recent-message window into
    # the rolling summary (architecture doc, p. 9, technique 3). Caught here, not left
    # to propagate — a failure to enqueue a background summarization job (e.g. a
    # misconfigured Cloud Tasks env var) must not surface as the whole turn erroring
    # out to the user; the turn itself already succeeded by this point.
    if latest_seq - summarized_through > RECENT_MESSAGE_LIMIT:
        try:
            await tasks.enqueue_summarize(uid, thread_id, latest_seq - RECENT_MESSAGE_LIMIT)
        except Exception:
            log.exception("failed to enqueue summarize task", extra={"thread_id": thread_id})
