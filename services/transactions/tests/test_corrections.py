from unittest.mock import AsyncMock

from app.storage.corrections import LIST_LIMIT, list_corrections, normalize_item, save_correction


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
        assert args[1:] == ("uid-1", "coffee", "dining")

    async def test_skips_write_when_description_is_empty(self, mock_conn: AsyncMock):
        await save_correction(mock_conn, "uid-1", None, "dining")
        mock_conn.execute.assert_not_awaited()


class TestListCorrections:
    async def test_lists_the_users_most_recent_corrections_up_to_the_limit(self, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = [{"item_key": "coffee", "category": "dining"}]
        rows = await list_corrections(mock_conn, "uid-1")
        assert rows == [{"item_key": "coffee", "category": "dining"}]
        assert mock_conn.fetch.call_args.args[1:] == ("uid-1", LIST_LIMIT)
        assert "ORDER BY updated_at DESC" in mock_conn.fetch.call_args.args[0]


class TestCorrectionsEndpoint:
    def test_returns_the_corrections(self, client, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = [{"item_key": "3x camel white 20", "category": "Entertainment"}]
        res = client.get("/api/transactions/corrections")
        assert res.status_code == 200
        assert res.json() == {"items": [{"item_key": "3x camel white 20", "category": "Entertainment"}]}
