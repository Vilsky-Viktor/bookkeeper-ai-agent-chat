import pytest
from fastapi import HTTPException

from app.service_auth import require_service_caller


class TestRequireServiceCaller:
    async def test_skipped_locally_when_flag_set(self, monkeypatch):
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "true")
        await require_service_caller(x_serverless_authorization=None)  # must not raise

    async def test_missing_token_rejected_when_not_skipped(self, monkeypatch):
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "false")
        with pytest.raises(HTTPException) as exc_info:
            await require_service_caller(x_serverless_authorization=None)
        assert exc_info.value.status_code == 401

    async def test_present_token_hits_not_implemented_locally(self, monkeypatch):
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "false")
        with pytest.raises(HTTPException) as exc_info:
            await require_service_caller(x_serverless_authorization="some-token")
        assert exc_info.value.status_code == 501
