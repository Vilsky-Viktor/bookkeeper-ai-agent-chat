from unittest.mock import AsyncMock, MagicMock

import pytest

from app.categorize import categorize, normalize_item, save_correction


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
