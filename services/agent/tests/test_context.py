import json

from langchain_core.messages import HumanMessage, SystemMessage

from app import context


def _user_row(text: str) -> dict:
    return {"role": "user", "content": json.dumps({"text": text}), "compact": None}


def _assistant_row(text: str, tool_calls: list | None = None) -> dict:
    return {"role": "assistant", "content": json.dumps({"text": text, "tool_calls": tool_calls or []}), "compact": None}


def _tool_row(name: str, result: dict, tool_call_id: str = "call-1") -> dict:
    return {
        "role": "tool",
        "content": json.dumps({"name": name, "tool_call_id": tool_call_id, "result": result}),
        "compact": json.dumps({"summary": f"{name}: compacted"}),
    }


class TestSystemPrompt:
    """Regression guards for specific anti-hallucination rules added after real
    failures — not exhaustive prompt coverage, just the ones that broke in practice."""

    def test_requires_calling_extract_receipt_every_upload(self):
        # Observed: the model described a fully-detailed "proposed transaction" for 3
        # different receipt uploads in a row while its stored tool_calls was empty —
        # it copied an earlier successful extraction's numbers instead of actually
        # calling extract_receipt again, so no UI event fired and no card ever showed.
        assert "MUST call extract_receipt" in context.SYSTEM_PROMPT
        assert "every single time" in context.SYSTEM_PROMPT

    def test_forbids_describing_a_proposal_without_a_real_tool_call(self):
        assert "without having actually called extract_receipt" in context.SYSTEM_PROMPT


class TestCountTokens:
    def test_empty_string_is_zero_tokens(self):
        assert context.count_tokens("") == 0

    def test_none_is_zero_tokens(self):
        assert context.count_tokens(None) == 0

    def test_nonempty_text_has_tokens(self):
        assert context.count_tokens("hello world") > 0


class TestCompactToolResult:
    def test_query_transactions_summarized_by_row_count(self):
        result = context.compact_tool_result("query_transactions", {"items": [{"id": "1"}, {"id": "2"}]})
        assert "2 rows" in result["summary"]

    def test_add_transaction_summarized_by_id(self):
        result = context.compact_tool_result("add_transaction", {"id": "txn-123"})
        assert "txn-123" in result["summary"]

    def test_extract_receipt_summarized_by_item_count(self):
        result = context.compact_tool_result("extract_receipt", {"items": [{"description": "milk"}]})
        assert "1 receipt line items" in result["summary"]

    def test_unknown_tool_falls_back_to_truncated_json(self):
        result = context.compact_tool_result("get_exchange_rate", {"rate": 1.23, "from": "USD", "to": "EUR"})
        assert "rate" in result["summary"]

    def test_long_result_gets_truncated_with_ellipsis(self):
        big_result = {"data": "x" * 500}
        result = context.compact_tool_result("some_tool", big_result)
        assert result["summary"].endswith("...")
        assert len(result["summary"]) < 500


class TestBuildContext:
    def test_minimal_context_has_system_and_human_message(self):
        messages = context.build_context({}, None, [], "hello")
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[-1], HumanMessage)
        assert messages[-1].content == "hello"

    def test_images_produce_multipart_human_message(self):
        messages = context.build_context({}, None, [], "what's this?", current_images=["http://x/img.png"])
        last = messages[-1]
        assert isinstance(last.content, list)
        assert last.content[0] == {"type": "text", "text": "what's this?"}
        assert last.content[1]["image_url"]["url"] == "http://x/img.png"

    def test_default_currency_preference_included_in_system_prompt(self):
        messages = context.build_context({}, {"default_currency": "EUR"}, [], "hi")
        assert "EUR" in messages[0].content

    def test_language_preference_included_in_system_prompt(self):
        messages = context.build_context({}, {"language": "fr"}, [], "hi")
        assert "French" in messages[0].content

    def test_unknown_language_defaults_to_english(self):
        messages = context.build_context({}, {"language": "xx"}, [], "hi")
        assert "English" in messages[0].content

    def test_working_set_included_in_system_prompt(self):
        thread = {"working_set": {"txn-1": "coffee, 5.00 USD, 2026-01-01"}}
        messages = context.build_context(thread, None, [], "hi")
        assert "txn-1" in messages[0].content

    def test_working_set_as_json_string_is_parsed(self):
        thread = {"working_set": json.dumps({"txn-1": "coffee"})}
        messages = context.build_context(thread, None, [], "hi")
        assert "txn-1" in messages[0].content

    def test_summary_included_in_system_prompt(self):
        thread = {"summary": "user reviewing September dining expenses"}
        messages = context.build_context(thread, None, [], "hi")
        assert "September dining" in messages[0].content

    def test_recent_turn_included_in_output(self):
        rows = [_user_row("add coffee"), _assistant_row("added it")]
        messages = context.build_context({}, None, rows, "what else?")
        texts = [m.content for m in messages if isinstance(m, HumanMessage)]
        assert "add coffee" in texts

    def test_tool_call_and_result_stay_in_same_turn(self):
        rows = [
            _user_row("add coffee"),
            _assistant_row("adding", tool_calls=[{"name": "add_transaction", "id": "call-1", "args": {}}]),
            _tool_row("add_transaction", {"id": "txn-1"}),
        ]
        messages = context.build_context({}, None, rows, "thanks")
        roles = [type(m).__name__ for m in messages]
        assert "AIMessage" in roles
        assert "ToolMessage" in roles

    def test_orphaned_leading_tool_row_is_dropped(self, monkeypatch):
        # A tool-result row with no preceding user message (the assistant's
        # tool_calls message fell outside the fetched window) must not surface as a
        # turn on its own — OpenAI rejects a tool message with no matching tool_calls.
        rows = [_tool_row("add_transaction", {"id": "orphan"}), _user_row("next turn")]
        messages = context.build_context({}, None, rows, "hi")
        tool_messages = [m for m in messages if type(m).__name__ == "ToolMessage"]
        assert tool_messages == []

    def test_turns_beyond_budget_are_dropped_oldest_first(self, monkeypatch):
        # Force a tiny budget so only the newest turn fits.
        monkeypatch.setattr(context, "CONTEXT_WINDOW", 200)
        monkeypatch.setattr(context, "OUTPUT_RESERVE_FRACTION", 0.0)
        rows = []
        for i in range(20):
            rows.append(_user_row(f"message number {i} " + "padding " * 20))
            rows.append(_assistant_row(f"reply {i} " + "padding " * 20))
        messages = context.build_context({}, None, rows, "current question")
        human_texts = [m.content for m in messages if isinstance(m, HumanMessage)]
        # The oldest turn ("message number 0") should have been trimmed out; the most
        # recent one should have survived.
        assert not any("message number 0 " in t for t in human_texts if t != "current question")
