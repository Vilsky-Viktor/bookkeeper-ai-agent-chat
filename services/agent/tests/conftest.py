"""Env vars must be set before any `app.*` module is imported, since several of them
read os.environ at import time: auth.py's firebase_admin.initialize_app(), tools.py's
TRANSACTIONS_URL/LLM_API_KEY, storage.py's RECEIPTS_BUCKET. pytest imports conftest.py
before collecting test modules, so this runs first."""

import os

os.environ.setdefault("CHAT_DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("TRANSACTIONS_URL", "http://transactions.test")
os.environ.setdefault("RECEIPTS_BUCKET", "test-bucket")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("FIREBASE_AUTH_EMULATOR_HOST", "localhost:9099")
os.environ.setdefault("SKIP_SERVICE_AUTH", "true")
os.environ.setdefault("TASKS_MODE", "local")

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_conn() -> AsyncMock:
    """A stand-in for an asyncpg.Connection — configure .fetchrow/.fetch/.execute's
    return_value or side_effect per test."""
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    conn.fetch.return_value = []
    conn.execute.return_value = ""
    return conn


@pytest.fixture
def patch_chat_uid_conn(monkeypatch, mock_conn: AsyncMock):
    """Makes every `chat_db.uid_conn(uid)` in the app return `mock_conn` instead of
    opening a real pool connection."""
    from app import chat_db

    @asynccontextmanager
    async def _fake_uid_conn(uid: str):
        yield mock_conn

    monkeypatch.setattr(chat_db, "uid_conn", _fake_uid_conn)
    return mock_conn
