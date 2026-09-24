import uuid
from unittest.mock import AsyncMock

from app import chat_db


def _msg_row(seq: int) -> dict:
    return {"seq": seq, "role": "user", "content": "{}", "compact": None, "token_count": 1}


class TestMessagesPage:
    async def test_first_page_no_more_when_under_limit(self, mock_conn: AsyncMock):
        # 3 rows returned for a query_limit of 6 (limit=5, +1 sentinel) -> nothing left.
        mock_conn.fetch.return_value = [_msg_row(3), _msg_row(2), _msg_row(1)]

        rows, has_more = await chat_db.messages_page(mock_conn, "uid-1", "thread-1", None, limit=5)

        assert has_more is False
        assert [r["seq"] for r in rows] == [1, 2, 3]  # reversed to oldest-first

    async def test_has_more_true_when_extra_sentinel_row_present(self, mock_conn: AsyncMock):
        # limit=2 -> query_limit=3; 3 rows back means there's more beyond this page.
        mock_conn.fetch.return_value = [_msg_row(5), _msg_row(4), _msg_row(3)]

        rows, has_more = await chat_db.messages_page(mock_conn, "uid-1", "thread-1", None, limit=2)

        assert has_more is True
        assert len(rows) == 2
        assert [r["seq"] for r in rows] == [4, 5]  # sentinel row (seq 3) dropped

    async def test_before_seq_none_uses_latest_query(self, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = []
        await chat_db.messages_page(mock_conn, "uid-1", "thread-1", None, limit=10)
        sql = mock_conn.fetch.call_args.args[0]
        assert "seq <" not in sql
        assert "ORDER BY seq DESC" in sql

    async def test_before_seq_set_filters_older_than_it(self, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = []
        await chat_db.messages_page(mock_conn, "uid-1", "thread-1", before_seq=42, limit=10)
        call = mock_conn.fetch.call_args
        assert "seq < $3" in call.args[0]
        assert call.args[3] == 42

    async def test_empty_thread_returns_no_more(self, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = []
        rows, has_more = await chat_db.messages_page(mock_conn, "uid-1", "thread-1", None, limit=10)
        assert rows == []
        assert has_more is False


class TestRecentMessages:
    async def test_reverses_to_oldest_first(self, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = [_msg_row(3), _msg_row(2), _msg_row(1)]
        rows = await chat_db.recent_messages(mock_conn, "uid-1", "thread-1", 40)
        assert [r["seq"] for r in rows] == [1, 2, 3]


class TestInsertMessage:
    async def test_generates_no_client_msg_id_when_none_given(self, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = {"seq": 1}
        await chat_db.insert_message(mock_conn, "uid-1", "thread-1", "user", {"text": "hi"}, 3)
        args = mock_conn.fetchrow.call_args.args
        assert args[-1] is None  # client_msg_id positional arg

    async def test_parses_client_msg_id_as_uuid(self, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = {"seq": 1}
        cid = str(uuid.uuid4())
        await chat_db.insert_message(mock_conn, "uid-1", "thread-1", "user", {"text": "hi"}, 3, client_msg_id=cid)
        args = mock_conn.fetchrow.call_args.args
        assert args[-1] == uuid.UUID(cid)

    async def test_returns_none_on_conflict(self, mock_conn: AsyncMock):
        # ON CONFLICT ... DO NOTHING with no RETURNING match -> fetchrow returns None.
        mock_conn.fetchrow.return_value = None
        result = await chat_db.insert_message(mock_conn, "uid-1", "thread-1", "user", {"text": "hi"}, 3)
        assert result is None


class TestUpdateWorkingSet:
    async def test_serializes_working_set_to_json(self, mock_conn: AsyncMock):
        await chat_db.update_working_set(mock_conn, "uid-1", "thread-1", {"txn-1": "coffee, 5.00 USD"})
        args = mock_conn.execute.call_args.args
        assert '"txn-1"' in args[1]
