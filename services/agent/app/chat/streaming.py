"""Runs one LangGraph turn end-to-end via astream_events, translating graph events
into the chat SSE wire format."""

import json

from ..graph import initial_state
from ..models.turns import ToolCallRecord, ToolResult, TurnState


def sse(event: str | None, data: dict) -> bytes:
    lines = [f"event: {event}"] if event else []
    lines.append(f"data: {json.dumps(data, default=str)}")
    return ("\n".join(lines) + "\n\n").encode()


async def run_graph_turn(compiled_graph, messages: list, run_config: dict, state: TurnState):
    """Runs the graph once, yielding each SSE chunk as it's produced and writing the
    turn's outcome into `state` (assistant_text_parts/tool_calls_made/tool_results/
    total_tokens_used) as it goes. The caller either forwards each yielded chunk to
    the client immediately (true streaming, the normal case) or collects them into a
    list first so it can inspect `state` and discard+retry before anything reaches
    the client — see runner._run_marker_turn's handling of a "[transaction: <id>]" marker turn,
    where an empty tool_calls_made despite the marker means the model fabricated a
    reply without ever calling the tool.

    run_config carries the LangSmith tags/metadata built by langsmith_obs.traced_turn
    — LangSmith attaches its own tracer from environment variables, so there's no
    callback handler to pass here."""
    async for event in compiled_graph.astream_events(initial_state(messages), config=run_config, version="v2"):
        kind = event["event"]
        # Some tools (extract_receipt's vision call) make their own, separate LLM
        # call from inside a tool function while the graph's ToolNode runs.
        # LangChain's ambient config propagation attaches this same tracer to that
        # nested call too, so it shows up in this event stream indistinguishable
        # from the graph's own model turn unless filtered out here — otherwise its
        # raw output streams to the user as if it were the assistant talking. Only
        # the graph's own "call_model" node's events count as assistant narration.
        is_call_model_node = event.get("metadata", {}).get("langgraph_node") == "call_model"

        if kind == "on_chat_model_stream" and is_call_model_node:
            chunk = event["data"]["chunk"]
            text = chunk.content if isinstance(chunk.content, str) else ""
            if text:
                state.assistant_text_parts.append(text)
                yield sse(None, {"type": "token", "text": text})

        elif kind == "on_chat_model_end":
            output = event["data"].get("output")
            usage = getattr(output, "usage_metadata", None)
            if usage:
                # Counted for every model call, including nested ones like vision
                # extraction — it's real spend against the user's token quota
                # either way.
                state.total_tokens_used += usage.get("total_tokens", 0)
            if not is_call_model_node:
                continue
            round_tool_calls = getattr(output, "tool_calls", None) or []
            for c in round_tool_calls:
                state.tool_calls_made.append(ToolCallRecord(id=c.get("id"), name=c.get("name"), args=c.get("args")))
            if round_tool_calls:
                # This round's streamed text (if any) was narration before a tool
                # call, not the final answer — e.g. "I'll export this now." Without
                # discarding it, it gets concatenated with the real answer that
                # follows the tool result, with no separator, reading as a garbled
                # double answer.
                state.assistant_text_parts.clear()
                yield sse("reset_pending", {"type": "reset_pending"})

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
            state.tool_results.append(ToolResult(name=name, tool_call_id=tool_call_id, result=parsed))

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
                yield sse(ui_event, payload)
