"""Env vars must be set before any `app.*` module is imported, since a few of them
(auth.py's firebase_admin.initialize_app(), db.py/signal.py reading os.environ at call
time) touch the environment at import or call time. pytest imports conftest.py before
collecting test modules, so this runs first."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("FIREBASE_AUTH_EMULATOR_HOST", "localhost:9099")
os.environ.setdefault("SKIP_SERVICE_AUTH", "true")

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
def patch_uid_conn(monkeypatch, mock_conn: AsyncMock):
    """Makes every `db.uid_conn(uid)` in the app return `mock_conn` instead of opening
    a real pool connection — the routers only ever use it as `async with
    db.uid_conn(uid) as conn`, so a plain async context manager stand-in is enough."""
    from app import db

    @asynccontextmanager
    async def _fake_uid_conn(uid: str):
        yield mock_conn

    monkeypatch.setattr(db, "uid_conn", _fake_uid_conn)
    return mock_conn


@pytest.fixture
def patch_signal(monkeypatch):
    """Avoids real Firestore calls from signal.bump_async during router tests."""
    from app import signal

    mock = AsyncMock()
    monkeypatch.setattr(signal, "bump_async", mock)
    return mock


@pytest.fixture
def client(patch_uid_conn, patch_signal):
    """A TestClient wired to a fresh FastAPI app mounting every router — built without
    main.py's lifespan (which opens a real Postgres pool on startup) and with
    require_uid overridden to a fixed test uid, so requests never touch a real DB,
    Firestore, or Firebase Auth."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth import require_uid
    from app.routers import aggregates
    from app.routers import categorize as categorize_router
    from app.routers import transactions

    app = FastAPI()
    app.include_router(transactions.router, prefix="/api/transactions")
    app.include_router(aggregates.router, prefix="/api/transactions")
    app.include_router(categorize_router.router, prefix="/api/transactions")
    app.dependency_overrides[require_uid] = lambda: "test-uid"

    return TestClient(app)
