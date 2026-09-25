import json

from langchain_core.messages import HumanMessage, SystemMessage

from app import context
from app.context import tokens as tokens_module


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

    def test_requires_short_reply_after_receipt_extraction(self):
        # Observed twice: after a successful extraction, the model fully re-narrated
        # every item/amount/category in prose immediately above the proposed-items
        # card, which already shows all of that — pure duplication. A first, softer
        # instruction ("keep your reply to one short sentence") didn't stop it; this
        # guards the stronger, example-anchored version instead. Also guards against
        # "in the UI" wording, since the card renders inline in the same chat, not in
        # some other UI surface.
        assert "reply with ONLY one short" in context.SYSTEM_PROMPT
        assert "Do NOT add a numbered or bulleted list" in context.SYSTEM_PROMPT
        assert "in the UI" not in context.SYSTEM_PROMPT

    def test_requires_calling_edit_delete_for_a_transaction_marker(self):
        # Observed: given a "[transaction: <id>]" marker (from the table's # reference
        # button, so the id is known to exist), the model replied "couldn't find the
        # transaction" three times in a row with an empty tool_calls list each time —
        # it never actually called edit_transaction at all, just fabricated a
        # plausible-looking failure instead of trying.
        assert "You MUST actually" in context.SYSTEM_PROMPT
        assert 'claiming "not found" without ever calling the tool is a fabrication' in context.SYSTEM_PROMPT

    def test_forbids_anchoring_on_a_prior_unfounded_not_found_reply(self):
        # This one is subtle and was only caught with a live model call: the softer
        # instruction above worked in a fresh conversation but NOT in the real failing
        # thread, which already had several rounds of the exact same user message
        # met with a fabricated "couldn't find" reply — the model kept repeating its
        # own prior (never tool-backed) answer instead of trying again. Verified with
        # a live call reproducing that exact poisoned history: without this
        # instruction the model repeats the fabrication; with it, it calls the tool.
        assert "even if an earlier turn in this same conversation already replied" in context.SYSTEM_PROMPT


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

    def test_working_set_framed_as_incomplete_not_authoritative(self):
        # First attempt at the root cause below: the working set is capped at 20
        # entries, so an older transaction id silently falls off it while still being
        # perfectly valid, and the model was treating a marker id's absence from
        # this list as evidence it didn't exist. This text-only caveat measurably
        # helped but did NOT reliably fix it on its own (still failed most of the
        # time on a real, repeatedly-reproduced case) — see
        # test_marker_id_always_injected_into_working_set below for the fix that
        # actually did.
        thread = {"working_set": {"txn-1": "coffee, 5.00 USD, 2026-01-01"}}
        messages = context.build_context(thread, None, [], "hi")
        assert "NOT the full set of valid transactions" in messages[0].content
        assert "is not evidence that id is wrong or doesn't exist" in messages[0].content

    def test_marker_id_always_injected_into_working_set(self):
        # The actual fix: don't just tell the model an absent id is still valid —
        # make sure it's never absent in the first place. Every marker edit whose id
        # happened to still be in the working set succeeded immediately, every time;
        # the one whose id had been evicted kept failing regardless of the caveat
        # above. So a "[transaction: <id>]" marker's id is now force-included in the
        # rendered list even when it fell off the real working set.
        thread = {"working_set": {"txn-1": "coffee, 5.00 USD, 2026-01-01"}}
        user_text = "Change amount [transaction: evicted-id] to 5"
        messages = context.build_context(thread, None, [], user_text)
        assert "evicted-id" in messages[0].content

    def test_marker_injection_does_not_override_a_real_cached_label(self):
        thread = {"working_set": {"txn-1": "coffee, 5.00 USD, 2026-01-01"}}
        user_text = "Change amount [transaction: txn-1] to 5"
        messages = context.build_context(thread, None, [], user_text)
        assert "txn-1: coffee, 5.00 USD, 2026-01-01" in messages[0].content

    def test_marker_injection_does_not_mutate_the_thread_dict(self):
        # build_context must not leak a per-turn placeholder label back into the
        # caller's thread object — it's not real cached data, just a stopgap for
        # this one prompt render.
        thread = {"working_set": {"txn-1": "coffee, 5.00 USD, 2026-01-01"}}
        context.build_context(thread, None, [], "Change amount [transaction: evicted-id] to 5")
        assert "evicted-id" not in thread["working_set"]

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
        monkeypatch.setattr(tokens_module, "CONTEXT_WINDOW", 200)
        monkeypatch.setattr(tokens_module, "OUTPUT_RESERVE_FRACTION", 0.0)
        rows = []
        for i in range(20):
            rows.append(_user_row(f"message number {i} " + "padding " * 20))
            rows.append(_assistant_row(f"reply {i} " + "padding " * 20))
        messages = context.build_context({}, None, rows, "current question")
        human_texts = [m.content for m in messages if isinstance(m, HumanMessage)]
        # The oldest turn ("message number 0") should have been trimmed out; the most
        # recent one should have survived.
        assert not any("message number 0 " in t for t in human_texts if t != "current question")
