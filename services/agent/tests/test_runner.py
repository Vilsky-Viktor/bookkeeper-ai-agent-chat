import json
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.chat import runner
from app.models.api import ChatRequest
from app.models.turns import ToolCallRecord

THREAD = {"id": "thread-1", "working_set": {}, "summarized_through": 0}


def _events(chunks: list[bytes]) -> list[tuple[str | None, dict]]:
    out = []
    for chunk in chunks:
        lines = chunk.decode().strip().split("\n")
        event = lines[0].removeprefix("event: ") if lines[0].startswith("event: ") else None
        out.append((event, json.loads(lines[-1].removeprefix("data: "))))
    return out


def _prepared(user_text: str = "hi", trimmed_before_seq: int | None = None) -> runner._PreparedTurn:
    return runner._PreparedTurn(
        user_text=user_text, user_tokens=1, language="en", messages=[], trimmed_before_seq=trimmed_before_seq
    )


@pytest.fixture
def seams(monkeypatch, patch_chat_uid_conn):
    """Replaces everything around the runner's decisions with recorders."""
    graph_runs: list[str] = []
    graph_tool_calls: list[list[ToolCallRecord]] = []  # per graph run, consumed in order

    async def fake_graph_turn(compiled_graph, messages, run_config, state):
        graph_runs.append(compiled_graph)
        calls = graph_tool_calls.pop(0) if graph_tool_calls else []
        state.tool_calls_made.extend(calls)
        state.assistant_text_parts.append(f"graph reply {len(graph_runs)}")
        yield runner.sse(None, {"type": "token", "text": f"graph reply {len(graph_runs)}"})

    async def fake_receipt_turn(tools, object_name, language, run_config, state):
        state.assistant_text_parts.append("receipt reply")
        yield runner.sse(None, {"type": "token", "text": "receipt reply"})

    @contextmanager
    def fake_traced_turn(*args, **kwargs):
        yield {}

    s = {
        "open_thread": AsyncMock(return_value=THREAD),
        "prepare": AsyncMock(return_value=_prepared()),
        "finalize": AsyncMock(),
        "record_failure": AsyncMock(),
        "graph_runs": graph_runs,
        "graph_tool_calls": graph_tool_calls,
    }
    monkeypatch.setattr(runner, "_open_thread", s["open_thread"])
    monkeypatch.setattr(runner, "_prepare_turn", s["prepare"])
    monkeypatch.setattr(runner, "build_tools", lambda *a: [])
    monkeypatch.setattr(runner, "build_graph", lambda tools: "graph")
    monkeypatch.setattr(runner, "traced_turn", fake_traced_turn)
    monkeypatch.setattr(runner.streaming, "run_graph_turn", fake_graph_turn)
    monkeypatch.setattr(runner.receipt_turn, "run_receipt_turn", fake_receipt_turn)
    monkeypatch.setattr(runner.turns, "finalize_turn", s["finalize"])
    monkeypatch.setattr(runner.turns, "record_turn_failure", s["record_failure"])
    monkeypatch.setattr(runner.signal, "bump_async", AsyncMock())
    return s


async def _run(message: str = "hi", receipt_object: str | None = None) -> list[tuple[str | None, dict]]:
    body = ChatRequest(message=message, receipt_object=receipt_object, thread_id=None)
    return _events([c async for c in runner.stream_chat_turn(body, "uid-1", "jwt", None, "https://agent")])


class TestStreamChatTurn:
    async def test_normal_turn_streams_the_graph_then_finishes(self, seams):
        events = await _run("how much did I spend?")

        assert events == [(None, {"type": "token", "text": "graph reply 1"}), ("done", {"thread_id": "thread-1"})]
        seams["finalize"].assert_awaited_once()

    async def test_bare_receipt_upload_skips_the_model(self, seams):
        seams["prepare"].return_value = _prepared("\n\n[uploaded receipt: receipts/u/r.jpg]")

        events = await _run("", receipt_object="receipts/u/r.jpg")

        assert events[0] == (None, {"type": "token", "text": "receipt reply"})
        assert seams["graph_runs"] == []

    async def test_receipt_with_typed_text_goes_through_the_model(self, seams):
        seams["prepare"].return_value = _prepared("from yesterday\n\n[uploaded receipt: receipts/u/r.jpg]")

        await _run("from yesterday", receipt_object="receipts/u/r.jpg")

        assert seams["graph_runs"] == ["graph"]

    async def test_marker_turn_without_the_matching_call_is_retried_once_silently(self, seams):
        seams["prepare"].return_value = _prepared("[transaction: t-1] delete this")
        seams["graph_tool_calls"].extend(
            [[], [ToolCallRecord(id="c1", name="delete_transaction", args={"transaction_id": "t-1"})]]
        )

        events = await _run("[transaction: t-1] delete this")

        assert len(seams["graph_runs"]) == 2
        # Only the retry's output reaches the client, and it's what gets persisted.
        assert [e for e in events if e[0] is None] == [(None, {"type": "token", "text": "graph reply 2"})]
        persisted_state = seams["finalize"].await_args.args[3]
        assert persisted_state.tool_calls_made[0].name == "delete_transaction"

    async def test_marker_turn_with_the_matching_call_is_not_retried(self, seams):
        seams["prepare"].return_value = _prepared("[transaction: t-1] delete this")
        seams["graph_tool_calls"].append(
            [ToolCallRecord(id="c1", name="delete_transaction", args={"transaction_id": "t-1"})]
        )

        await _run("[transaction: t-1] delete this")

        assert len(seams["graph_runs"]) == 1

    async def test_duplicate_message_gets_an_error_and_nothing_runs(self, seams):
        seams["prepare"].return_value = None

        events = await _run()

        assert events == [("error", {"message": runner.ALREADY_SENT})]
        assert seams["graph_runs"] == []
        seams["finalize"].assert_not_awaited()

    async def test_trimmed_history_boundary_is_passed_to_finalize(self, seams):
        seams["prepare"].return_value = _prepared(trimmed_before_seq=42)

        await _run()

        assert seams["finalize"].await_args.kwargs["trimmed_before_seq"] == 42

    async def test_quota_error_shows_its_own_message_and_is_recorded(self, seams):
        seams["prepare"].side_effect = HTTPException(status_code=429, detail="Daily limit reached.")

        events = await _run()

        assert events == [("error", {"message": "Daily limit reached.", "status": 429})]
        seams["record_failure"].assert_awaited_once_with("uid-1", "thread-1", "Daily limit reached.")

    async def test_other_http_errors_show_a_plain_message(self, seams):
        seams["open_thread"].side_effect = HTTPException(status_code=404, detail="thread not found")

        events = await _run()

        assert events == [("error", {"message": runner.COULDNT_DO_THAT, "status": 404})]
        seams["record_failure"].assert_not_awaited()  # no thread to record into

    async def test_unexpected_crash_is_recorded_and_reported(self, seams):
        seams["finalize"].side_effect = RuntimeError("db down")

        events = await _run()

        assert events[-1] == ("error", {"message": runner.CRASHED})
        seams["record_failure"].assert_awaited_once_with("uid-1", "thread-1", runner.CRASHED)
