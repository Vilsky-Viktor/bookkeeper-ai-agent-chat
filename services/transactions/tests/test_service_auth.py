from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.service_auth import AUDIENCE, require_service_caller

_AGENT_EMAIL = "agent-sa@demo-project.iam.gserviceaccount.com"


class TestRequireServiceCaller:
    async def test_skipped_locally_when_flag_set(self, monkeypatch):
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "true")
        await require_service_caller(x_serverless_authorization=None)  # must not raise

    async def test_missing_token_rejected_when_not_skipped(self, monkeypatch):
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "false")
        with pytest.raises(HTTPException) as exc_info:
            await require_service_caller(x_serverless_authorization=None)
        assert exc_info.value.status_code == 401

    async def test_malformed_token_rejected(self, monkeypatch):
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "false")
        monkeypatch.setenv("AGENT_SERVICE_ACCOUNT", _AGENT_EMAIL)
        with pytest.raises(HTTPException) as exc_info:
            await require_service_caller(x_serverless_authorization="Bearer not-a-real-jwt")
        assert exc_info.value.status_code == 401
        assert "invalid service token" in exc_info.value.detail

    async def test_valid_token_from_expected_caller_is_accepted(self, monkeypatch):
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "false")
        monkeypatch.setenv("AGENT_SERVICE_ACCOUNT", _AGENT_EMAIL)
        monkeypatch.setattr(
            "app.service_auth.google_id_token.verify_oauth2_token",
            MagicMock(return_value={"email": _AGENT_EMAIL, "email_verified": True, "aud": AUDIENCE}),
        )
        await require_service_caller(x_serverless_authorization="Bearer some-valid-looking-jwt")  # must not raise

    async def test_valid_token_from_unexpected_caller_is_rejected(self, monkeypatch):
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "false")
        monkeypatch.setenv("AGENT_SERVICE_ACCOUNT", _AGENT_EMAIL)
        monkeypatch.setattr(
            "app.service_auth.google_id_token.verify_oauth2_token",
            MagicMock(return_value={"email": "someone-else@evil.iam.gserviceaccount.com", "email_verified": True}),
        )
        with pytest.raises(HTTPException) as exc_info:
            await require_service_caller(x_serverless_authorization="Bearer some-valid-looking-jwt")
        assert exc_info.value.status_code == 403

    async def test_unverified_email_claim_is_rejected(self, monkeypatch):
        monkeypatch.setenv("SKIP_SERVICE_AUTH", "false")
        monkeypatch.setenv("AGENT_SERVICE_ACCOUNT", _AGENT_EMAIL)
        monkeypatch.setattr(
            "app.service_auth.google_id_token.verify_oauth2_token",
            MagicMock(return_value={"email": _AGENT_EMAIL, "email_verified": False}),
        )
        with pytest.raises(HTTPException) as exc_info:
            await require_service_caller(x_serverless_authorization="Bearer some-valid-looking-jwt")
        assert exc_info.value.status_code == 403
