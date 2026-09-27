import datetime
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

    graph_inputs: list[dict] = []

    async def fake_graph_turn(compiled_graph, inputs, run_config, state):
        graph_runs.append(compiled_graph)
        graph_inputs.append(inputs)
        calls = graph_tool_calls.pop(0) if graph_tool_calls else []
        state.tool_calls_made.extend(calls)
        state.assistant_text_parts.append(f"graph reply {len(graph_runs)}")
        yield runner.sse(None, {"type": "token", "text": f"graph reply {len(graph_runs)}"})

    built_graph_with: list = []

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
        "graph_inputs": graph_inputs,
        "built_graph_with": built_graph_with,
    }
    monkeypatch.setattr(runner, "_open_thread", s["open_thread"])
    monkeypatch.setattr(runner, "_prepare_turn", s["prepare"])
    monkeypatch.setattr(runner, "build_main_graph", lambda *a: built_graph_with.append(a) or "graph")
    monkeypatch.setattr(runner, "traced_turn", fake_traced_turn)
    monkeypatch.setattr(runner.streaming, "run_graph_turn", fake_graph_turn)
    monkeypatch.setattr(runner.turns, "finalize_turn", s["finalize"])
    monkeypatch.setattr(runner.turns, "record_turn_failure", s["record_failure"])
    return s


async def _run(
    message: str = "hi", receipt_object: str | None = None, timezone: str | None = None
) -> list[tuple[str | None, dict]]:
    body = ChatRequest(message=message, receipt_object=receipt_object, thread_id=None, timezone=timezone)
    return _events([c async for c in runner.stream_chat_turn(body, "uid-1", "jwt", "https://agent")])


class TestStreamChatTurn:
    async def test_normal_turn_streams_the_graph_then_finishes(self, seams):
        events = await _run("how much did I spend?")

        assert events == [(None, {"type": "token", "text": "graph reply 1"}), ("done", {"thread_id": "thread-1"})]
        seams["finalize"].assert_awaited_once()

    async def test_an_upload_goes_to_the_graph_with_its_receipt_and_note(self, seams):
        # Routing (receipt workflow and/or assistant) is the main graph's job; the
        # runner hands it everything it needs to decide.
        seams["prepare"].return_value = _prepared("from yesterday\n\n[uploaded receipt: receipts/u/r.jpg]")

        await _run("from yesterday", receipt_object="receipts/u/r.jpg")

        (inputs,) = seams["graph_inputs"]
        assert inputs["receipt_object"] == "receipts/u/r.jpg"
        assert inputs["note"] == "from yesterday"

    async def test_a_marker_with_an_upload_is_not_treated_as_a_marker_turn(self, seams):
        seams["prepare"].return_value = _prepared("[transaction: t-1]\n\n[uploaded receipt: receipts/u/r.jpg]")

        await _run("[transaction: t-1]", receipt_object="receipts/u/r.jpg")

        assert len(seams["graph_runs"]) == 1  # streamed once, no marker retry

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

    async def test_the_users_timezone_sets_today_for_context_and_tools(self, seams, monkeypatch):
        monkeypatch.setattr(runner, "user_today", lambda tz: {"Asia/Makassar": datetime.date(2026, 9, 27)}[tz])

        await _run("what did I spend today?", timezone="Asia/Makassar")

        assert seams["prepare"].await_args.args[4] == datetime.date(2026, 9, 27)
        assert seams["built_graph_with"][0][2] == datetime.date(2026, 9, 27)
