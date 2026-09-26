"""Turn grouping and per-row message rendering for build_context()'s trimming loop."""

import json
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from ..models.message_content import AssistantMessageContent, ToolMessageContent, UserMessageContent

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


def row_to_message(row, full_detail: bool) -> BaseMessage:
    content = _content_json(row)
    role = row["role"]

    if role == "user":
        return HumanMessage(content=UserMessageContent.model_validate(content).text)

    if role == "assistant":
        assistant_content = AssistantMessageContent.model_validate(content)
        return AIMessage(
            content=assistant_content.text,
            tool_calls=[tc.model_dump() for tc in assistant_content.tool_calls],
        )

    if role == "tool":
        tool_content = ToolMessageContent.model_validate(content)
        compact = _compact_json(row)
        if not full_detail and compact:
            payload = compact
        else:
            payload = tool_content.result
        return ToolMessage(
            content=json.dumps(payload, default=str),
            tool_call_id=tool_content.tool_call_id,
            name=tool_content.name,
        )

    raise ValueError(f"unknown message role: {role}")


def group_into_turns(rows: list) -> list[list]:
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

    # `rows` is a row-count window (chat_db.unsummarized_messages), which has no
    # notion of turn boundaries — it can start mid-turn, e.g. on a tool-result message
    # whose assistant tool_calls message fell just outside the limit or was summarized. Sending an
    # orphaned tool message with no preceding tool_calls message breaks OpenAI's
    # message-order validation, so drop that incomplete leading fragment.
    if turns and turns[0][0]["role"] != "user":
        turns = turns[1:]
    return turns
