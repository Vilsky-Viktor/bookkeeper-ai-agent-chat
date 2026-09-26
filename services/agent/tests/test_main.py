import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app import context
from app import llm as llm_module
from app import tools as tools_module
from app.chat import streaming, turns
from app.graph import build_graph
from app.models.turns import ToolCallRecord, TurnState

_RealAsyncClient = httpx.AsyncClient  # captured before any monkeypatching below


class _ScriptedChatModel(BaseChatModel):
    """A minimal real BaseChatModel (not a mock) that returns pre-queued responses in
    order — needed because GenericFakeChatModel doesn't implement bind_tools(), and a
    Mock/AsyncMock standing in for the model wouldn't exercise LangGraph's actual
    message-handling machinery (the add_messages reducer, state shape, etc.), which
    is exactly what the regression below needs a real run through."""

    responses: list[AIMessage]

    def bind_tools(self, tools, **kwargs):
        return self

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError

    @property
    def _llm_type(self) -> str:
        return "scripted"


class TestRunTurnAgainstARealGraph:
    async def test_drives_a_tool_call_to_completion_without_state_shape_errors(self, monkeypatch):
        # Regression: messages were wrapped with initial_state() by the caller AND
        # again inside run_graph_turn, double-nesting the graph's state into
        # {"messages": {"messages": [...]}} — this broke every single chat turn in
        # production (not just the marker-retry path) with "Message dict must
        # contain 'role' and 'content' keys". A test that mocks the model or the
        # graph away wouldn't touch LangGraph's real add_messages reducer, so it
        # wouldn't have caught this; only a real astream_events run does.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": [], "next_cursor": None})

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return _RealAsyncClient(*args, **kwargs)

        monkeypatch.setattr(tools_module.httpx, "AsyncClient", factory)
        tools = tools_module.build_tools("test-jwt", None, "en")

        tool_call_msg = AIMessage(
            content="",
            tool_calls=[{"name": "query_transactions", "args": {}, "id": "call-1", "type": "tool_call"}],
        )
        final_msg = AIMessage(content="Here are your transactions.")
        scripted = _ScriptedChatModel(responses=[tool_call_msg, final_msg])
        monkeypatch.setattr(llm_module, "primary_model", lambda: scripted)
        monkeypatch.setattr(llm_module, "fallback_model", lambda: scripted)

        compiled_graph = build_graph(tools)
        messages = [SystemMessage(content="you are a test agent"), HumanMessage(content="show my transactions")]
        state = TurnState()

        chunks = [c async for c in streaming.run_graph_turn(compiled_graph, messages, {}, state)]

        assert chunks  # some SSE bytes were actually produced
        # The real regression-guard: the graph ran end to end (through ToolNode and
        # back to call_model) without the state-shape crash, and the tool call the
        # scripted model queued up actually landed in the recorded state. Text-token
        # streaming isn't asserted here since _ScriptedChatModel only implements
        # non-streaming _agenerate, not _astream — that's orthogonal to this bug.
        assert state.tool_calls_made == [ToolCallRecord(id="call-1", name="query_transactions", args={})]


class TestTransactionMarkerRe:
    def test_extracts_single_id(self):
        assert context.TRANSACTION_MARKER_RE.findall("Change amount [transaction: abc-123] to 5") == ["abc-123"]

    def test_extracts_multiple_ids(self):
        text = "Delete [transaction: id-1] and [transaction: id-2]"
        assert context.TRANSACTION_MARKER_RE.findall(text) == ["id-1", "id-2"]

    def test_no_marker_returns_empty(self):
        assert context.TRANSACTION_MARKER_RE.findall("Change amount of the coffee one to 5") == []


class TestRecordTurnFailure:
    # Regression: an unhandled crash left the user's message in a thread with no
    # assistant reply ever inserted — every later turn in that thread then saw two
    # consecutive human messages with no assistant turn between them, which turned
    # out to be a much stronger source of model confusion than ordinary variance
    # (traced to a real incident: repeated, otherwise-inexplicable failures retrying
    # the same edit, all in one thread that had this exact orphaned message).
    async def test_inserts_an_assistant_message_with_the_given_note(self, patch_chat_uid_conn):
        await turns.record_turn_failure("uid-1", "thread-1", "Sorry, something went wrong.")

        patch_chat_uid_conn.fetchrow.assert_awaited_once()
        args = patch_chat_uid_conn.fetchrow.await_args.args
        assert args[1] == "thread-1"
        assert args[2] == "uid-1"
        assert args[3] == "assistant"
        assert '"text": "Sorry, something went wrong."' in args[4]

    async def test_swallows_its_own_failure_instead_of_raising(self, patch_chat_uid_conn):
        patch_chat_uid_conn.fetchrow.side_effect = RuntimeError("db unreachable")

        # Must not raise — this runs from inside an except block handling a turn
        # that already failed; a second exception here would replace the real error
        # response the client is waiting for.
        await turns.record_turn_failure("uid-1", "thread-1", "Sorry, something went wrong.")


class TestMarkerCallMissing:
    # This is the exact decision logic behind the retry: a "[transaction: <id>]"
    # marker turn is only trusted if a real edit_transaction/delete_transaction call
    # was made against that specific id — never inferred from the assistant's text.
    def test_true_when_no_tool_calls_at_all(self):
        assert turns.marker_call_missing([], ["abc-123"]) is True

    def test_false_when_edit_transaction_matches_the_marker_id(self):
        tool_calls = [ToolCallRecord(name="edit_transaction", args={"transaction_id": "abc-123", "amount": "5"})]
        assert turns.marker_call_missing(tool_calls, ["abc-123"]) is False

    def test_false_when_delete_transaction_matches_the_marker_id(self):
        tool_calls = [ToolCallRecord(name="delete_transaction", args={"transaction_id": "abc-123"})]
        assert turns.marker_call_missing(tool_calls, ["abc-123"]) is False

    def test_true_when_tool_call_is_for_a_different_id(self):
        tool_calls = [ToolCallRecord(name="edit_transaction", args={"transaction_id": "other-id", "amount": "5"})]
        assert turns.marker_call_missing(tool_calls, ["abc-123"]) is True

    def test_true_when_only_an_unrelated_tool_was_called(self):
        # e.g. the model called query_transactions instead of actually editing —
        # still counts as a miss, since nothing was actually changed.
        tool_calls = [ToolCallRecord(name="query_transactions", args={"description": "coffee"})]
        assert turns.marker_call_missing(tool_calls, ["abc-123"]) is True

    def test_false_when_any_of_multiple_marker_ids_matches(self):
        tool_calls = [ToolCallRecord(name="edit_transaction", args={"transaction_id": "id-2", "amount": "5"})]
        assert turns.marker_call_missing(tool_calls, ["id-1", "id-2"]) is False
