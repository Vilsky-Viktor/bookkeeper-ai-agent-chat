"""Per-turn state handed between chat/streaming.py's run_graph_turn (which builds it while
draining the graph's event stream) and chat/turns.py's finalize_turn (which persists
it) — the turn's outcome in one place instead of untyped dict keys."""

from typing import Any

from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    """One `on_chat_model_end` tool call — also the shape stored in the `assistant`
    message row's `content.tool_calls` (see models/message_content.py), so this is
    the read/write contract for that DB round-trip too, not just in-memory state."""

    id: str | None = None
    name: str | None = None
    args: dict[str, Any] | None = None


class ToolResult(BaseModel):
    """One `on_tool_end` result — name/tool_call_id identify which call it answers;
    `result` stays a loose dict here since different tools have different shapes and
    this is a heterogeneous aggregation point, not a single tool's own return type
    (see models/tool_results.py for those)."""

    name: str
    tool_call_id: str | None
    result: dict[str, Any]


class TurnState(BaseModel):
    """Mutated in place throughout run_graph_turn (list fields support the same
    .append()/.clear() calls a dict-of-lists did), then read by finalize_turn and
    turns.marker_call_missing once the turn is done."""

    assistant_text_parts: list[str] = Field(default_factory=list)
    tool_calls_made: list[ToolCallRecord] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    total_tokens_used: int = 0
