"""Editing a transaction (routers/transactions/patch.py)."""

from unittest.mock import AsyncMock

from row_helpers import TXN_ID, row


class TestPatchTransaction:
    def test_success(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, row(), row(category="groceries")]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"category": "groceries"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 200
        assert res.json()["category"] == "groceries"

    def test_not_found_returns_404(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, None]  # idempotency miss, then no existing row

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"category": "groceries"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 404

    def test_invalid_amount_returns_400(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, row()]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"amount": "not-a-number"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 400

    def test_currency_change_without_amount_rescales_amount_minor(self, client, mock_conn: AsyncMock):
        # Regression: currency changed alone (no new "amount") used to leave
        # amount_minor untouched, so the old currency's minor units got read back
        # under the new currency's exponent — a JPY (0-decimal) amount_minor of 1500
        # reused as-is under USD (2-decimal) would silently become $15.00 instead of
        # the equivalent $1,500.00.
        mock_conn.fetchrow.side_effect = [None, row(currency="JPY", amount_minor=1500), row()]

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
        mock_conn.fetchrow.side_effect = [None, row(currency="USD", amount_minor=1250)]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"currency": "JPY"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 400

    def test_currency_change_with_explicit_amount_uses_new_amount_not_rescaling(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, row(currency="JPY", amount_minor=1500), row()]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"currency": "USD", "amount": "20.00"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 200
        update_call = mock_conn.fetchrow.call_args_list[2]
        assert update_call.args[3] == 2000
        assert update_call.args[4] == "USD"

    def test_same_currency_keeps_amount_minor_unchanged(self, client, mock_conn: AsyncMock):
        mock_conn.fetchrow.side_effect = [None, row(currency="USD", amount_minor=1250), row()]

        res = client.patch(
            f"/api/transactions/transactions/{TXN_ID}",
            json={"category": "groceries"},
            headers={"Idempotency-Key": "key-1"},
        )

        assert res.status_code == 200
        update_call = mock_conn.fetchrow.call_args_list[2]
        assert update_call.args[3] == 1250
