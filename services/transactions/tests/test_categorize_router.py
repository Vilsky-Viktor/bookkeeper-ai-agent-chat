from unittest.mock import AsyncMock, MagicMock


class TestCategorizeBatchEndpoint:
    def test_returns_one_category_per_description(self, client, monkeypatch):
        monkeypatch.setattr("app.routers.categorize.categorize_many", AsyncMock(return_value=["groceries", "health"]))
        res = client.post("/api/transactions/categorize/batch", json={"descriptions": ["rice", "soap"]})
        assert res.status_code == 200
        assert res.json() == {"categories": ["groceries", "health"]}

    def test_empty_list_is_rejected(self, client):
        res = client.post("/api/transactions/categorize/batch", json={"descriptions": []})
        assert res.status_code == 422


class TestCategorizeEndpoint:
    def test_success(self, client, mock_conn: AsyncMock, monkeypatch):
        mock_conn.fetchrow.return_value = {"category": "dining"}

        res = client.post(
            "/api/transactions/categorize",
            json={"description": "coffee", "amount": "5.00", "currency": "USD"},
        )

        assert res.status_code == 200
        assert res.json() == {"category": "dining"}

    def test_invalid_amount_returns_400(self, client):
        res = client.post(
            "/api/transactions/categorize",
            json={"description": "coffee", "amount": "not-a-number", "currency": "USD"},
        )
        assert res.status_code == 400

    def test_service_caller_gate_blocks_without_header_when_not_skipped(self, monkeypatch):
        # SKIP_SERVICE_AUTH is read at call time (os.getenv), so flipping it here
        # takes effect without re-importing the module.
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "false")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.auth import require_uid
        from app.routers import categorize as categorize_router

        app = FastAPI()
        app.include_router(categorize_router.router, prefix="/api/transactions")
        app.dependency_overrides[require_uid] = lambda: "test-uid"

        res = TestClient(app).post(
            "/api/transactions/categorize",
            json={"description": "coffee", "amount": "5.00", "currency": "USD"},
        )
        assert res.status_code == 401
