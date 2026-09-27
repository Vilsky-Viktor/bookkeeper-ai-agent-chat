"""Deleting transactions (routers/transactions/delete.py)."""

from unittest.mock import AsyncMock

from row_helpers import TXN_ID


class TestDeleteTransaction:
    def test_success(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = None  # idempotency miss
        mock_conn.execute.return_value = "DELETE 1"

        res = client.delete(f"/api/transactions/transactions/{TXN_ID}", headers={"Idempotency-Key": "key-1"})

        assert res.status_code == 200
        assert res.json()["deleted"] == TXN_ID

    def test_not_found_returns_404(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = None
        mock_conn.execute.return_value = "DELETE 0"

        res = client.delete(f"/api/transactions/transactions/{TXN_ID}", headers={"Idempotency-Key": "key-1"})

        assert res.status_code == 404


class TestDeleteTransactionsBulk:
    def test_success_reports_deleted_count(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = None
        mock_conn.execute.return_value = "DELETE 7"

        res = client.delete("/api/transactions/transactions", headers={"Idempotency-Key": "key-1"})

        assert res.status_code == 200
        assert res.json()["deleted_count"] == 7

    def test_invalid_amount_filter_returns_400(self, client):
        res = client.delete("/api/transactions/transactions?min_amount=garbage", headers={"Idempotency-Key": "key-1"})
        assert res.status_code == 400
