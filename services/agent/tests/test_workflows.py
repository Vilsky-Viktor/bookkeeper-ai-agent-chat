import datetime
import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph

from app.models.tool_results import ReceiptExtraction
from app.tools.schema import compact_tool_schema
from app.workflows import main as main_module
from app.workflows import receipt as receipt_module
from app.workflows.receipt import build_receipt_graph
from app.workflows.state import CategorizeState, ChatState

TODAY = datetime.date(2026, 9, 27)


def _fake_categorize_graph(categories: dict[str, str], calls: list):
    """Stands in for the categorize subgraph (its own tests are in test_categorize.py)."""

    def classify(state: CategorizeState) -> CategorizeState:
        calls.append(state["descriptions"])

        return {"categories": [categories.get(d, "other") for d in state["descriptions"]]}

    g = StateGraph(CategorizeState)
    g.add_node("classify", classify)
    g.add_edge(START, "classify")
    g.add_edge("classify", END)

    return g.compile(name="categorize")


async def _run_receipt(monkeypatch, extraction, content_type="image/jpeg", note="", categories=None):
    """Runs the real receipt workflow with storage and the vision call faked; returns
    (custom events by name, final state, categorize calls)."""
    monkeypatch.setattr(receipt_module.storage, "read_bytes", lambda name: (b"img", content_type))
    monkeypatch.setattr(receipt_module.images, "shrink_for_vision", lambda data, ct: (data, ct))
    monkeypatch.setattr(receipt_module.receipts, "read_receipt", AsyncMock(return_value=extraction))
    calls: list = []
    graph = build_receipt_graph(_fake_categorize_graph(categories or {}, calls), "en", TODAY)
    events: dict[str, list] = {}
    final = None

    async for ev in graph.astream_events({"receipt_object": "receipts/u1/r.jpg", "note": note}, version="v2"):
        if ev["event"] == "on_custom_event":
            events.setdefault(ev["name"], []).append(ev["data"])

        if ev["event"] == "on_chain_end" and ev["name"] == "receipt_workflow":
            final = ev["data"]["output"]

    return events, final, calls


GROCERY_RECEIPT = ReceiptExtraction(
    is_receipt=True,
    merchant="Alfamart",
    occurred_on="2026-09-26",
    currency="idr",
    total_paid="164100",
    description="Rice, eggs and 1 more item",
    items=["Rice 1kg", "Eggs", "Shampoo"],
)


class TestReceiptWorkflow:
    async def test_proposes_one_transaction_with_the_majority_category(self, monkeypatch):
        categories = {
            "Rice 1kg - Alfamart": "groceries",
            "Eggs - Alfamart": "groceries",
            "Shampoo - Alfamart": "health",
        }
        events, final, calls = await _run_receipt(monkeypatch, GROCERY_RECEIPT, categories=categories)

        # All items categorized in one call, each with the merchant attached.
        assert calls == [["Rice 1kg - Alfamart", "Eggs - Alfamart", "Shampoo - Alfamart"]]
        (card,) = events["ui_event"]
        assert card["event"] == "receipt_proposed"
        (item,) = card["payload"]["items"]
        assert (item["amount"], item["currency"], item["category"]) == ("164100", "IDR", "groceries")
        assert item["description"] == "Rice, eggs and 1 more item - Alfamart"

    async def test_a_bare_upload_gets_the_fixed_reply_and_a_history_record(self, monkeypatch):
        events, final, _ = await _run_receipt(monkeypatch, GROCERY_RECEIPT)

        # A key, not a sentence: the web app words it in the user's language.
        assert events["notice"] == [{"key": "receiptProposed", "params": {"date": "2026-09-26"}}]
        (record,) = events["tool_record"]
        assert record["name"] == "extract_receipt" and record["args"] == {"object_name": "receipts/u1/r.jpg"}
        assert "ui_event" not in record["result"]

    async def test_with_a_note_the_reply_is_left_to_the_assistant(self, monkeypatch):
        events, final, _ = await _run_receipt(monkeypatch, GROCERY_RECEIPT, note="this was yesterday")

        assert "notice" not in events
        # The note reached the reader...
        receipt_module.receipts.read_receipt.assert_awaited_once()
        assert receipt_module.receipts.read_receipt.await_args.args[4] == "this was yesterday"
        # ...and the assistant will see the result as an extract_receipt tool call.
        ai, tool_msg = final["messages"][-2:]
        assert isinstance(ai, AIMessage) and ai.tool_calls[0]["name"] == "extract_receipt"
        assert isinstance(tool_msg, ToolMessage) and json.loads(tool_msg.content)["items"][0]["amount"] == "164100"

    async def test_not_a_receipt_skips_categorizing(self, monkeypatch):
        events, _, calls = await _run_receipt(monkeypatch, ReceiptExtraction(is_receipt=False))

        assert calls == []
        assert "ui_event" not in events
        assert events["notice"] == [{"key": "notAReceipt", "params": {}}]

    async def test_an_unsupported_file_never_reaches_the_reader(self, monkeypatch):
        events, _, calls = await _run_receipt(monkeypatch, GROCERY_RECEIPT, content_type="text/html")

        receipt_module.receipts.read_receipt.assert_not_awaited()
        assert calls == []
        assert "text/html" in events["tool_record"][0]["result"]["error"]
        assert events["notice"] == [{"key": "receiptUnreadable", "params": {}}]


def _recording_subgraph(name: str, visits: list, state_schema=MessagesState):
    def visit(state):
        visits.append(name)

        return {}

    g = StateGraph(state_schema)
    g.add_node("visit", visit)
    g.add_edge(START, "visit")
    g.add_edge("visit", END)

    return g.compile(name=name)


def _named_tool(name: str):
    return type("FakeTool", (), {"name": name})()


class TestMainGraphRouting:
    @pytest.fixture
    def seams(self, monkeypatch):
        """Real main graph; each subgraph replaced by a recorder of visits and of the
        tools it was built with."""
        s: dict = {"visits": [], "tools": {}}
        tools = [_named_tool(n) for n in ("add_transaction", "edit_transaction", "query_transactions")]
        monkeypatch.setattr(main_module, "transactions_client", lambda jwt: None)
        monkeypatch.setattr(main_module, "build_categorize_graph", lambda http: None)
        monkeypatch.setattr(main_module, "build_tools", lambda http, cat: tools)
        monkeypatch.setattr(
            main_module,
            "build_receipt_graph",
            lambda cat, lang, today: _recording_subgraph("receipt", s["visits"], ChatState),
        )

        def fake_assistant(tools, name="assistant", instructions=None):
            s["tools"][name] = [t.name for t in tools]
            s.setdefault("instructions", {})[name] = instructions

            return _recording_subgraph(name, s["visits"])

        monkeypatch.setattr(main_module, "build_assistant_graph", fake_assistant)

        return s

    async def _run(self, receipt_object=None, note=""):
        graph = main_module.build_main_graph("jwt", "en", TODAY)

        return await graph.ainvoke(
            {"messages": [HumanMessage(content=note or "x")], "receipt_object": receipt_object, "note": note}
        )

    async def test_a_plain_message_goes_to_the_assistant(self, seams):
        final = await self._run(note="how much did I spend?")
        assert seams["visits"] == ["assistant"] and final["route"] == "assistant"

    async def test_a_bare_upload_only_runs_the_receipt_workflow(self, seams):
        final = await self._run(receipt_object="receipts/u/r.jpg")
        assert seams["visits"] == ["receipt"] and final["route"] == "receipt"

    async def test_an_upload_with_a_note_runs_the_receipt_workflow_then_the_followup(self, seams):
        await self._run(receipt_object="receipts/u/r.jpg", note="this was yesterday")
        assert seams["visits"] == ["receipt", "receipt_followup"]

    async def test_the_followup_can_only_look_not_change(self, seams):
        # Regression (live tests): with add_transaction in reach, the model saved the
        # receipt itself, bypassing the confirm card; without it, it reached for
        # edit/delete instead. The follow-up gets read-only tools and its own role.
        main_module.build_main_graph("jwt", "en", TODAY)
        assert seams["tools"]["assistant"] == ["add_transaction", "edit_transaction", "query_transactions"]
        assert seams["tools"]["receipt_followup"] == ["query_transactions"]
        assert seams["instructions"]["receipt_followup"] and seams["instructions"]["assistant"] is None


class TestCompactToolSchema:
    def test_collapses_whitespace_and_simplifies_optional_params(self):
        @tool
        def query(currency: str | None = None, limit: int = 5, name: str = "x") -> dict:
            """Find things.

            Second line,    indented."""

            return {}

        fn = compact_tool_schema(query)["function"]

        assert fn["description"] == "Find things. Second line, indented."
        assert fn["parameters"]["properties"]["currency"] == {"type": "string"}
        assert fn["parameters"]["properties"]["limit"]["default"] == 5
        assert "currency" not in fn["parameters"].get("required", [])
