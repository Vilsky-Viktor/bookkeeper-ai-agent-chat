"""Creating transactions (routers/transactions/create.py)."""

from unittest.mock import AsyncMock

from row_helpers import row


class TestCreateTransactions:
    def test_success_creates_and_returns_item(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, row()]  # idempotency miss, then INSERT...RETURNING

        res = client.post(
            "/api/transactions/transactions",
            json={
                "transactions": [
                    {
                        "occurred_on": "2026-01-15",
                        "type": "expense",
                        "amount": "12.50",
                        "currency": "USD",
                        "category": "dining",
                        "description": "coffee",
                    }
                ]
            },
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 201
        assert res.json()["items"][0]["amount"] == "12.50"

    def _confirm_receipt(self, client, mock_conn: AsyncMock, category: str, suggested: str):
        mock_conn.fetchrow.side_effect = [None, row(receipt_uri="gs://b/r.jpg", category=category)]

        return client.post(
            "/api/transactions/transactions",
            json={
                "transactions": [
                    {
                        "occurred_on": "2026-01-15",
                        "type": "expense",
                        "amount": "12.50",
                        "currency": "USD",
                        "category": category,
                        "suggested_category": suggested,
                        "description": "Rice, eggs and 2 more - Shop",
                        "receipt_uri": "gs://b/r.jpg",
                    }
                ]
            },
            headers={"Idempotency-Key": "key-r"},
        )

    def test_confirmed_receipt_with_unchanged_category_saves_no_correction(
        self, client, mock_conn: AsyncMock, monkeypatch
    ):
        save = AsyncMock()
        monkeypatch.setattr("app.routers.transactions.create.save_correction", save)

        res = self._confirm_receipt(client, mock_conn, category="groceries", suggested="groceries")

        assert res.status_code == 201
        save.assert_not_awaited()

    def test_confirmed_receipt_with_changed_category_saves_a_correction(
        self, client, mock_conn: AsyncMock, monkeypatch
    ):
        save = AsyncMock()
        monkeypatch.setattr("app.routers.transactions.create.save_correction", save)

        res = self._confirm_receipt(client, mock_conn, category="shopping", suggested="groceries")

        assert res.status_code == 201
        save.assert_awaited_once()
        assert save.await_args.args[2:] == ("Rice, eggs and 2 more - Shop", "shopping")

    def test_empty_batch_returns_400(self, client):
        res = client.post(
            "/api/transactions/transactions",
            json={"transactions": []},
            headers={"Idempotency-Key": "key-1"},
        )
        assert res.status_code == 400

    def test_invalid_amount_returns_400(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = None  # idempotency miss

        res = client.post(
            "/api/transactions/transactions",
            json={
                "transactions": [
                    {
                        "occurred_on": "2026-01-15",
                        "type": "expense",
                        "amount": "not-a-number",
                        "currency": "USD",
                        "category": "dining",
                    }
                ]
            },
            headers={"Idempotency-Key": "key-1"},
        )
        assert res.status_code == 400

    def test_category_is_required(self, client):
        # The agent categorizes before creating; this service no longer does.
        res = client.post(
            "/api/transactions/transactions",
            json={"transactions": [{"occurred_on": "2026-01-15", "type": "expense", "amount": "1", "currency": "USD"}]},
            headers={"Idempotency-Key": "key-1"},
        )
        assert res.status_code == 422

    def test_missing_idempotency_key_returns_422(self, client):
        res = client.post(
            "/api/transactions/transactions",
            json={"transactions": [{"occurred_on": "2026-01-15", "type": "expense", "amount": "1", "currency": "USD"}]},
        )
        assert res.status_code == 422

    def test_replayed_idempotent_request_returns_the_stored_response(self, client, mock_conn: AsyncMock):
        from app.storage.idempotency import _hash

        payload = [
            {
                "occurred_on": "2026-01-15",
                "type": "expense",
                "amount": "12.50",
                "currency": "USD",
                "category": "dining",
                "description": "coffee",
                "receipt_uri": None,
                "batch_id": None,
                "suggested_category": None,
            }
        ]
        mock_conn.fetchrow.return_value = {
            "request_hash": _hash(payload),
            "status": 201,
            "response": '{"items": []}',
        }

        res = client.post(
            "/api/transactions/transactions",
            json={
                "transactions": [
                    {
                        "occurred_on": "2026-01-15",
                        "type": "expense",
                        "amount": "12.50",
                        "currency": "USD",
                        "category": "dining",
                        "description": "coffee",
                    }
                ]
            },
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 201
        assert res.json() == {"items": []}  # the stored response, not a new write
