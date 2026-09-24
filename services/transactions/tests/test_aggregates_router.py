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

    def test_missing_auth_returns_422(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers import aggregates

        app = FastAPI()
        app.include_router(aggregates.router, prefix="/api/transactions")
        res = TestClient(app).get("/api/transactions/aggregates")
        assert res.status_code == 422
