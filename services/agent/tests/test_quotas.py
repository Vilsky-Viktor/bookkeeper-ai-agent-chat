from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import quotas


class TestIncrementAndCheckTurn:
    async def test_under_limit_does_not_raise(self, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = {"turns": 1}
        await quotas.increment_and_check_turn(mock_conn, "uid-1")  # must not raise

    async def test_at_limit_does_not_raise(self, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = {"turns": quotas.DAILY_TURN_LIMIT}
        await quotas.increment_and_check_turn(mock_conn, "uid-1")

    async def test_over_limit_raises_429(self, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = {"turns": quotas.DAILY_TURN_LIMIT + 1}
        with pytest.raises(HTTPException) as exc_info:
            await quotas.increment_and_check_turn(mock_conn, "uid-1")
        assert exc_info.value.status_code == 429


class TestIncrementReceipt:
    async def test_under_limit_does_not_raise(self, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = {"receipts": 1}
        await quotas.increment_receipt(mock_conn, "uid-1")

    async def test_over_limit_raises_429(self, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = {"receipts": quotas.DAILY_RECEIPT_LIMIT + 1}
        with pytest.raises(HTTPException) as exc_info:
            await quotas.increment_receipt(mock_conn, "uid-1")
        assert exc_info.value.status_code == 429


class TestAddTokens:
    async def test_calls_execute_with_uid_and_tokens(self, mock_conn: AsyncMock):
        await quotas.add_tokens(mock_conn, "uid-1", 150)
        mock_conn.execute.assert_awaited_once()
        args = mock_conn.execute.call_args.args
        assert args[1] == "uid-1"
        assert args[2] == 150
