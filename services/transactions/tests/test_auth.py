import pytest
from fastapi import HTTPException

from app.auth import require_uid


class TestRequireUid:
    async def test_missing_bearer_prefix_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            await require_uid(authorization="not-a-bearer-token")
        assert exc_info.value.status_code == 401

    async def test_valid_token_returns_uid(self, monkeypatch):
        monkeypatch.setattr("app.auth.fb_auth.verify_id_token", lambda token: {"uid": "user-123"})
        uid = await require_uid(authorization="Bearer some.jwt.token")
        assert uid == "user-123"

    async def test_invalid_token_rejected(self, monkeypatch):
        def _raise(token):
            raise ValueError("bad token")

        monkeypatch.setattr("app.auth.fb_auth.verify_id_token", _raise)
        with pytest.raises(HTTPException) as exc_info:
            await require_uid(authorization="Bearer garbage")
        assert exc_info.value.status_code == 401
