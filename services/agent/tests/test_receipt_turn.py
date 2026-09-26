import json

from langchain_core.tools import tool

from app.chat import receipt_turn
from app.chat.receipt_turn import _REPLIES
from app.graph import _compact_tool_schema
from app.models.turns import TurnState


def _fake_extract_receipt(result: dict):
    @tool
    async def extract_receipt(object_name: str) -> dict:
        """Fake."""
        return dict(result)

    return extract_receipt


def _events(chunks: list[bytes]) -> list[dict]:
    return [json.loads(c.decode().split("data: ", 1)[1]) for c in chunks]


PROPOSED = {
    "ui_event": "receipt_proposed",
    "items": [{"occurred_on": "2026-09-26", "amount": "84700", "currency": "IDR", "category": "dining"}],
    "receipt_uri": "gs://b/receipts/u1/x.jpg",
}


class TestRunReceiptTurn:
    async def test_emits_the_card_and_a_translated_one_line_reply_without_a_model(self):
        state = TurnState()
        chunks = [
            c
            async for c in receipt_turn.run_receipt_turn(
                [_fake_extract_receipt(PROPOSED)], "receipts/u1/x.jpg", "de", {}, state
            )
        ]

        card, reply = _events(chunks)
        assert card["type"] == "receipt_proposed"
        assert card["items"][0]["amount"] == "84700"
        assert reply == {"type": "token", "text": _REPLIES["de"]["proposed"].format(date="2026-09-26")}

    async def test_records_the_turn_like_a_model_driven_one(self):
        # finalize_turn persists from TurnState, so this is what makes the direct path
        # look identical in history to a graph turn that called extract_receipt.
        state = TurnState()
        async for _ in receipt_turn.run_receipt_turn(
            [_fake_extract_receipt(PROPOSED)], "receipts/u1/x.jpg", "en", {}, state
        ):
            pass

        (call,) = state.tool_calls_made
        (result,) = state.tool_results
        assert call.name == "extract_receipt" and call.args == {"object_name": "receipts/u1/x.jpg"}
        assert result.tool_call_id == call.id
        assert "ui_event" not in result.result
        assert state.assistant_text_parts == [_REPLIES["en"]["proposed"].format(date="2026-09-26")]

    async def test_not_a_receipt_gets_its_own_reply_and_no_card(self):
        state = TurnState()
        not_receipt = {"not_a_receipt": True, "message": "nope"}
        chunks = [
            c
            async for c in receipt_turn.run_receipt_turn(
                [_fake_extract_receipt(not_receipt)], "receipts/u1/x.jpg", "en", {}, state
            )
        ]

        assert _events(chunks) == [{"type": "token", "text": _REPLIES["en"]["not_a_receipt"]}]

    async def test_unknown_language_falls_back_to_english(self):
        state = TurnState()
        chunks = [
            c
            async for c in receipt_turn.run_receipt_turn(
                [_fake_extract_receipt({"error": "bad file"})], "receipts/u1/x.txt", "xx", {}, state
            )
        ]
        assert _events(chunks)[-1]["text"] == _REPLIES["en"]["error"]

    def test_every_language_has_every_reply(self):
        for replies in _REPLIES.values():
            assert set(replies) == set(_REPLIES["en"])
            assert "{date}" in replies["proposed"]


class TestCompactToolSchema:
    def test_collapses_whitespace_and_simplifies_optional_params(self):
        @tool
        def query(currency: str | None = None, limit: int = 5, name: str = "x") -> dict:
            """Find things.

            Second line,    indented."""
            return {}

        fn = _compact_tool_schema(query)["function"]

        assert fn["description"] == "Find things. Second line, indented."
        assert fn["parameters"]["properties"]["currency"] == {"type": "string"}
        assert fn["parameters"]["properties"]["limit"]["default"] == 5
        assert "currency" not in fn["parameters"].get("required", [])
