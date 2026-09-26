import datetime
import uuid
from unittest.mock import AsyncMock

TXN_ID = str(uuid.uuid4())


def _row(**overrides) -> dict:
    row = {
        "id": TXN_ID,
        "uid": "test-uid",
        "occurred_on": datetime.date(2026, 1, 15),
        "type": "expense",
        "amount_minor": 1250,
        "currency": "USD",
        "category": "dining",
        "description": "coffee",
        "receipt_uri": None,
        "batch_id": None,
        "created_at": datetime.datetime(2026, 1, 15, 12, 0, 0),
    }
    row.update(overrides)
    return row


class TestListTransactions:
    def test_success_returns_items_and_no_next_cursor_under_a_full_page(self, client, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = [_row()]

        res = client.get("/api/transactions/transactions")

        assert res.status_code == 200
        body = res.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["amount"] == "12.50"
        assert body["next_cursor"] is None

    def test_next_cursor_present_when_page_is_full(self, client, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = [_row()]

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


class TestCreateTransactions:
    def test_success_creates_and_returns_item(self, client, mock_conn: AsyncMock, patch_signal: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, _row()]  # idempotency miss, then INSERT...RETURNING

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
        patch_signal.assert_awaited_once()

    def _confirm_receipt(self, client, mock_conn: AsyncMock, category: str, suggested: str):
        mock_conn.fetchrow.side_effect = [None, _row(receipt_uri="gs://b/r.jpg", category=category)]
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
        self, client, mock_conn: AsyncMock, patch_signal: AsyncMock, monkeypatch
    ):
        save = AsyncMock()
        monkeypatch.setattr("app.routers.transactions.create.save_correction", save)

        res = self._confirm_receipt(client, mock_conn, category="groceries", suggested="groceries")

        assert res.status_code == 201
        save.assert_not_awaited()

    def test_confirmed_receipt_with_changed_category_saves_a_correction(
        self, client, mock_conn: AsyncMock, patch_signal: AsyncMock, monkeypatch
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
                    }
                ]
            },
            headers={"Idempotency-Key": "key-1"},
        )
        assert res.status_code == 400

    def test_missing_idempotency_key_returns_422(self, client):
        res = client.post(
            "/api/transactions/transactions",
            json={"transactions": [{"occurred_on": "2026-01-15", "type": "expense", "amount": "1", "currency": "USD"}]},
        )
        assert res.status_code == 422

    def test_replayed_idempotent_request_does_not_bump_signal(
        self, client, mock_conn: AsyncMock, patch_signal: AsyncMock
    ):
        from app.idempotency import _hash

        payload = [
            {
                "occurred_on": "2026-01-15",
                "type": "expense",
                "amount": "12.50",
                "currency": "USD",
                "category": None,
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
                        "description": "coffee",
                    }
                ]
            },
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 201
        patch_signal.assert_not_awaited()


class TestPatchTransaction:
    def test_success(self, client, mock_conn: AsyncMock, patch_signal: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, _row(), _row(category="groceries")]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"category": "groceries"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 200
        assert res.json()["category"] == "groceries"
        patch_signal.assert_awaited_once()

    def test_not_found_returns_404(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, None]  # idempotency miss, then no existing row

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"category": "groceries"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 404

    def test_invalid_amount_returns_400(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, _row()]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"amount": "not-a-number"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 400

    def test_currency_change_without_amount_rescales_amount_minor(self, client, mock_conn: AsyncMock, patch_signal):
        # Regression: currency changed alone (no new "amount") used to leave
        # amount_minor untouched, so the old currency's minor units got read back
        # under the new currency's exponent — a JPY (0-decimal) amount_minor of 1500
        # reused as-is under USD (2-decimal) would silently become $15.00 instead of
        # the equivalent $1,500.00.
        mock_conn.fetchrow.side_effect = [None, _row(currency="JPY", amount_minor=1500), _row()]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"currency": "USD"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 200
        update_call = mock_conn.fetchrow.call_args_list[2]
        assert update_call.args[3] == 150000  # amount_minor: rescaled, not the raw 1500
        assert update_call.args[4] == "USD"

    def test_currency_change_that_would_lose_precision_returns_400(self, client, mock_conn: AsyncMock):
        # The existing amount ("12.50" USD) can't be represented losslessly in a
        # 0-decimal currency — reject it rather than silently rounding.
        mock_conn.fetchrow.side_effect = [None, _row(currency="USD", amount_minor=1250)]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"currency": "JPY"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 400

    def test_currency_change_with_explicit_amount_uses_new_amount_not_rescaling(
        self, client, mock_conn: AsyncMock, patch_signal
    ):
        mock_conn.fetchrow.side_effect = [None, _row(currency="JPY", amount_minor=1500), _row()]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"currency": "USD", "amount": "20.00"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 200
        update_call = mock_conn.fetchrow.call_args_list[2]
        assert update_call.args[3] == 2000
        assert update_call.args[4] == "USD"

    def test_same_currency_keeps_amount_minor_unchanged(self, client, mock_conn: AsyncMock, patch_signal):
        mock_conn.fetchrow.side_effect = [None, _row(currency="USD", amount_minor=1250), _row()]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"category": "groceries"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 200
        update_call = mock_conn.fetchrow.call_args_list[2]
        assert update_call.args[3] == 1250


class TestDeleteTransaction:
    def test_success(self, client, mock_conn: AsyncMock, patch_signal: AsyncMock):
        mock_conn.fetchrow.return_value = None  # idempotency miss
        mock_conn.execute.return_value = "DELETE 1"

        res = client.delete(f"/api/transactions/transactions/{TXN_ID}", headers={"Idempotency-Key": "key-1"})

        assert res.status_code == 200
        assert res.json()["deleted"] == TXN_ID
        patch_signal.assert_awaited_once()

    def test_not_found_returns_404(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = None
        mock_conn.execute.return_value = "DELETE 0"

        res = client.delete(f"/api/transactions/transactions/{TXN_ID}", headers={"Idempotency-Key": "key-1"})

        assert res.status_code == 404


class TestDeleteTransactionsBulk:
    def test_success_reports_deleted_count(self, client, mock_conn: AsyncMock, patch_signal: AsyncMock):
        mock_conn.fetchrow.return_value = None
        mock_conn.execute.return_value = "DELETE 7"

        res = client.delete("/api/transactions/transactions", headers={"Idempotency-Key": "key-1"})

        assert res.status_code == 200
        assert res.json()["deleted_count"] == 7
        patch_signal.assert_awaited_once()

    def test_invalid_amount_filter_returns_400(self, client):
        res = client.delete("/api/transactions/transactions?min_amount=garbage", headers={"Idempotency-Key": "key-1"})
        assert res.status_code == 400
