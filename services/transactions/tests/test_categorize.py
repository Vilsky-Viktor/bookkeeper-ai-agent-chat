from unittest.mock import AsyncMock, MagicMock

import pytest

from app.categorize import CATEGORIZE_MODEL, categorize, categorize_many, normalize_item, save_correction


class TestNormalizeItem:
    def test_strips_and_lowercases(self):
        assert normalize_item("  Coffee At Starbucks  ") == "coffee at starbucks"

    def test_none_returns_empty_string(self):
        assert normalize_item(None) == ""

    def test_empty_string_returns_empty_string(self):
        assert normalize_item("") == ""


class TestSaveCorrection:
    async def test_saves_normalized_key(self, mock_conn: AsyncMock):
        await save_correction(mock_conn, "uid-1", "  Coffee  ", "dining")
        mock_conn.execute.assert_awaited_once()
        args = mock_conn.execute.call_args.args
        assert args[1] == "uid-1"
        assert args[2] == "coffee"
        assert args[3] == "dining"

    async def test_skips_write_when_description_is_empty(self, mock_conn: AsyncMock):
        await save_correction(mock_conn, "uid-1", None, "dining")
        mock_conn.execute.assert_not_awaited()


class TestCategorize:
    async def test_income_short_circuits_without_touching_db(self, mock_conn: AsyncMock):
        category = await categorize(mock_conn, "uid-1", "salary", 500000, "USD", "income")
        assert category == "income"
        mock_conn.fetchrow.assert_not_awaited()

    async def test_returns_existing_correction_without_calling_llm(self, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetchrow.return_value = {"category": "dining"}
        mock_client = MagicMock()
        monkeypatch.setattr("app.categorize._get_client", lambda: mock_client)

        category = await categorize(mock_conn, "uid-1", "coffee at starbucks", 500, "USD", "expense")

        assert category == "dining"
        mock_client.chat.completions.create.assert_not_called()

    async def test_falls_back_to_llm_when_no_correction_matches(self, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetchrow.return_value = None  # no exact-key correction
        mock_conn.fetch.return_value = []  # no correction history

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="groceries"))]
        mock_create = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.chat.completions.create = mock_create
        monkeypatch.setattr("app.categorize._get_client", lambda: mock_client)

        category = await categorize(mock_conn, "uid-1", "rice and beans", 1000, "USD", "expense")

        assert category == "groceries"
        mock_create.assert_awaited_once()

    async def test_llm_reply_outside_allowed_list_falls_back_to_other(self, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetchrow.return_value = None
        mock_conn.fetch.return_value = []

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="not-a-real-category"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("app.categorize._get_client", lambda: mock_client)

        category = await categorize(mock_conn, "uid-1", "mystery item", 1000, "USD", "expense")

        assert category == "other"

    async def test_llm_matches_custom_category_from_history(self, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetchrow.return_value = None
        mock_conn.fetch.return_value = [{"item_key": "claude subscription", "category": "Work Tools"}]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="work tools"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("app.categorize._get_client", lambda: mock_client)

        category = await categorize(mock_conn, "uid-1", "Claude AI subscription payment", 2000, "USD", "expense")

        # The model replies with the lowercased custom category; categorize() maps it
        # back to the exact original casing the user typed.
        assert category == "Work Tools"

    async def test_llm_error_falls_back_to_other(self, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetchrow.return_value = None
        mock_conn.fetch.return_value = []

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))
        monkeypatch.setattr("app.categorize._get_client", lambda: mock_client)

        category = await categorize(mock_conn, "uid-1", "something", 1000, "USD", "expense")

        assert category == "other"

    async def test_prompt_steers_tobacco_away_from_groceries(self, mock_conn: AsyncMock, monkeypatch):
        # Regression: a minimarket receipt's cigarettes ("Camel White 20's") came back
        # categorized as "groceries" — the groceries definition covered food/household
        # consumables broadly enough that the model treated "sold at a grocery store"
        # as sufficient, rather than requiring the item itself to actually be food.
        mock_conn.fetchrow.return_value = None
        mock_conn.fetch.return_value = []

        captured = {}

        async def fake_create(**kwargs):
            captured["prompt"] = kwargs["messages"][0]["content"]
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="shopping"))]
            return response

        mock_client = MagicMock()
        mock_client.chat.completions.create = fake_create
        monkeypatch.setattr("app.categorize._get_client", lambda: mock_client)

        category = await categorize(mock_conn, "uid-1", "Camel White 20's - Indomaret", 34900, "IDR", "expense")

        assert category == "shopping"
        assert "tobacco" in captured["prompt"].lower()
        # Shown as a real amount, not "34900 minor units" (which reads as 349.00 for
        # a 2-decimal currency and is meaningless to the model either way).
        assert "Amount: 34900 IDR" in captured["prompt"]

    async def test_empty_description_skips_correction_lookup_but_still_calls_llm(
        self, mock_conn: AsyncMock, monkeypatch
    ):
        mock_conn.fetch.return_value = []
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="other"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("app.categorize._get_client", lambda: mock_client)

        category = await categorize(mock_conn, "uid-1", None, 1000, "USD", "expense")

        assert category == "other"
        mock_conn.fetchrow.assert_not_awaited()


def _json_client(content: str, captured: dict | None = None) -> MagicMock:
    async def fake_create(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=content))]
        return response

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=fake_create)
    return client


class TestCategorizeMany:
    async def test_one_model_call_for_all_uncorrected_items(self, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetch.side_effect = [
            [{"item_key": "shampoo - shop", "category": "health"}],  # exact corrections
            [],  # history for the prompt
        ]
        captured: dict = {}
        client = _json_client('{"categories": ["groceries", "shopping"]}', captured)
        monkeypatch.setattr("app.categorize._get_client", lambda: client)

        result = await categorize_many(mock_conn, "uid-1", ["Rice - Shop", "Shampoo - Shop", "Cigarettes - Shop"])

        assert result == ["groceries", "health", "shopping"]
        client.chat.completions.create.assert_awaited_once()
        prompt = captured["messages"][0]["content"]
        # Only the two uncorrected items are sent, numbered in order.
        assert "1. Rice - Shop" in prompt and "2. Cigarettes - Shop" in prompt
        assert "Shampoo" not in prompt
        assert captured["model"] == CATEGORIZE_MODEL

    async def test_no_model_call_when_every_item_has_a_correction(self, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetch.return_value = [{"item_key": "rice", "category": "groceries"}]
        client = _json_client("{}")
        monkeypatch.setattr("app.categorize._get_client", lambda: client)

        assert await categorize_many(mock_conn, "uid-1", ["Rice"]) == ["groceries"]
        client.chat.completions.create.assert_not_awaited()

    async def test_short_or_invalid_model_reply_falls_back_to_other(self, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetch.side_effect = [[], []]
        monkeypatch.setattr("app.categorize._get_client", lambda: _json_client('{"categories": ["not-a-category"]}'))

        assert await categorize_many(mock_conn, "uid-1", ["a", "b"]) == ["other", "other"]

    async def test_model_error_falls_back_to_other(self, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetch.side_effect = [[], []]
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))
        monkeypatch.setattr("app.categorize._get_client", lambda: client)

        assert await categorize_many(mock_conn, "uid-1", ["a"]) == ["other"]
