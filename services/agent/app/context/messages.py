"""Turn grouping and per-row message rendering for build_context()'s trimming loop."""

import json
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

# Matches the marker ChatPanel.tsx's insertReference() drops into the message box
# (`[transaction: ${id}]`) when the user clicks a table row's # reference button.
TRANSACTION_MARKER_RE = re.compile(r"\[transaction: ([^\]]+)\]")

FULL_DETAIL_TURNS = 3  # most-recent N turns keep full tool-result content, not compact


def _content_json(row) -> dict:
    c = row["content"]
    return json.loads(c) if isinstance(c, str) else c


def _compact_json(row) -> dict | None:
    c = row["compact"]
    if c is None:
        return None
    return json.loads(c) if isinstance(c, str) else c


def compact_tool_result(tool_name: str, result: dict) -> dict:
    """Deterministic, cheap compaction for a tool result — no LLM call. Used once a
    tool message ages out of the most-recent turns."""
    if tool_name == "query_transactions" and isinstance(result.get("items"), list):
        items = result["items"]
        return {"summary": f"{tool_name}: {len(items)} rows returned, ids stored"}
    if tool_name == "add_transaction" and "id" in result:
        return {"summary": f"added transaction {result['id']}"}
    if tool_name == "extract_receipt" and isinstance(result.get("items"), list):
        return {"summary": f"extracted {len(result['items'])} receipt line items (proposed, not saved)"}
    text = json.dumps(result)
    return {"summary": text[:200] + ("..." if len(text) > 200 else "")}


def _row_to_message(row, full_detail: bool) -> BaseMessage:
    content = _content_json(row)
    role = row["role"]

    if role == "user":
        return HumanMessage(content=content.get("text", ""))

    if role == "assistant":
        tool_calls = content.get("tool_calls") or []
        return AIMessage(content=content.get("text", ""), tool_calls=tool_calls)

    if role == "tool":
        compact = _compact_json(row)
        if not full_detail and compact:
            payload = compact
        else:
            payload = content.get("result", content)
        return ToolMessage(
            content=json.dumps(payload, default=str),
            tool_call_id=content.get("tool_call_id", ""),
            name=content.get("name"),
        )

    raise ValueError(f"unknown message role: {role}")


def _group_into_turns(rows: list) -> list[list]:
    """Groups oldest-first rows into turns: a user message starts a new turn; the
    assistant/tool messages that follow belong to it. Keeps a tool call and its
    result in the same turn so trimming never separates them."""
    turns: list[list] = []
    current: list = []
    for row in rows:
        if row["role"] == "user" and current:
            turns.append(current)
            current = []
        current.append(row)
    if current:
        turns.append(current)

    # `rows` is a raw row-count window (chat_db.recent_messages LIMIT), which has no
    # notion of turn boundaries — it can start mid-turn, e.g. on a tool-result message
    # whose assistant tool_calls message fell just outside the limit. Sending an
    # orphaned tool message with no preceding tool_calls message breaks OpenAI's
    # message-order validation, so drop that incomplete leading fragment.
    if turns and turns[0][0]["role"] != "user":
        turns = turns[1:]
    return turns
