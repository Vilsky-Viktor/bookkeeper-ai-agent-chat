"""Listing transactions (routers/transactions/list.py)."""

from unittest.mock import AsyncMock

from row_helpers import row


class TestListTransactions:
    def test_success_returns_items_and_no_next_cursor_under_a_full_page(self, client, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = [row()]

        res = client.get("/api/transactions/transactions")

        assert res.status_code == 200
        body = res.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["amount"] == "12.50"
        assert body["next_cursor"] is None

    def test_next_cursor_present_when_page_is_full(self, client, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = [row()]

        res = client.get("/api/transactions/transactions?limit=1")

        assert res.status_code == 200
        assert res.json()["next_cursor"] is not None

    def test_invalid_min_amount_returns_400(self, client, mock_conn: AsyncMock):
        res = client.get("/api/transactions/transactions?min_amount=not-a-number")
        assert res.status_code == 400

    def test_invalid_cursor_returns_400(self, client):
        res = client.get("/api/transactions/transactions?cursor=garbage")
        assert res.status_code == 400

    def test_missing_auth_header_returns_422(self):
        # No `client` fixture (which overrides require_uid) here — hits the real
        # dependency, which requires an Authorization header at all.
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers import transactions

        app = FastAPI()
        app.include_router(transactions.router, prefix="/api/transactions")
        res = TestClient(app).get("/api/transactions/transactions")
        assert res.status_code == 422
