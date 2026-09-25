from unittest.mock import AsyncMock


class TestAggregates:
    def test_success_formats_totals_as_decimal_strings(self, client, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = [
            {"currency": "USD", "category": "dining", "month": "2026-01", "total_minor": 5000, "count": 3},
        ]

        res = client.get("/api/transactions/aggregates")

        assert res.status_code == 200
        items = res.json()["items"]
        assert items == [{"currency": "USD", "category": "dining", "month": "2026-01", "total": "50.00", "count": 3}]

    def test_empty_result_set(self, client, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = []
        res = client.get("/api/transactions/aggregates")
        assert res.status_code == 200
        assert res.json()["items"] == []

    def test_category_filter_is_applied(self, client, mock_conn: AsyncMock):
        # Regression: this endpoint used to silently ignore a category filter (it
        # wasn't a declared query param at all, so FastAPI just dropped it) —
        # query_transactions(aggregate=true, category=...) looked like it worked but
        # actually returned the unfiltered total across every category.
        mock_conn.fetch.return_value = []

        res = client.get("/api/transactions/aggregates?category=groceries")

        assert res.status_code == 200
        sql, params = mock_conn.fetch.call_args.args[0], mock_conn.fetch.call_args.args[1:]
        assert "category = $2" in sql
        assert "groceries" in params

    def test_description_filter_uses_ilike(self, client, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = []

        res = client.get("/api/transactions/aggregates?description=bagel")

        assert res.status_code == 200
        sql, params = mock_conn.fetch.call_args.args[0], mock_conn.fetch.call_args.args[1:]
        assert "description ILIKE" in sql
        assert "%bagel%" in params

    def test_min_and_max_amount_filters_are_applied(self, client, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = []

        res = client.get("/api/transactions/aggregates?currency=USD&min_amount=10&max_amount=100")

        assert res.status_code == 200
        sql, params = mock_conn.fetch.call_args.args[0], mock_conn.fetch.call_args.args[1:]
        assert "amount_minor >= " in sql
        assert "amount_minor <= " in sql
        assert 1000 in params  # $10.00 -> 1000 minor units
        assert 10000 in params  # $100.00 -> 10000 minor units

    def test_invalid_min_amount_returns_400(self, client, mock_conn: AsyncMock):
        res = client.get("/api/transactions/aggregates?min_amount=not-a-number")
        assert res.status_code == 400

    def test_missing_auth_returns_422(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers import aggregates

        app = FastAPI()
        app.include_router(aggregates.router, prefix="/api/transactions")
        res = TestClient(app).get("/api/transactions/aggregates")
        assert res.status_code == 422
