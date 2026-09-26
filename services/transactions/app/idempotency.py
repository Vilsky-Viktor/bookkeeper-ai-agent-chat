"""Every write accepts an Idempotency-Key header. Same key + same request body ->
replay the stored response. Same key + different body -> 409. Keys are kept for
KEY_TTL; each new write also clears that user's expired ones."""

import hashlib
import json
from typing import Any, Awaitable, Callable

import asyncpg
from fastapi import HTTPException

KEY_TTL = "24 hours"


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def run_idempotent(
    conn: asyncpg.Connection,
    uid: str,
    key: str,
    payload: Any,
    handler: Callable[[], Awaitable[tuple[int, Any]]],
) -> tuple[int, Any, bool]:
    """Returns (status, response, replayed). `replayed=True` means the write did not
    happen this call — callers should skip side effects like the Firestore bump."""
    h = _hash(payload)
    existing = await conn.fetchrow(
        "SELECT request_hash, status, response FROM idempotency_keys WHERE uid=$1 AND key=$2",
        uid,
        key,
    )
    if existing:
        if existing["request_hash"] != h:
            raise HTTPException(status_code=409, detail="Idempotency-Key reused with a different request")
        return existing["status"], json.loads(existing["response"]), True

    status, response = await handler()
    await conn.execute(
        "INSERT INTO idempotency_keys (uid, key, request_hash, status, response) VALUES ($1,$2,$3,$4,$5)",
        uid,
        key,
        h,
        status,
        json.dumps(response, default=str),
    )
    # Cleanup piggybacks on writes: scoped to this user, so row-level security allows
    # it with the app's own role, and it needs no scheduler (which a scale-to-zero
    # Cloud Run service couldn't run reliably anyway).
    await conn.execute(f"DELETE FROM idempotency_keys WHERE uid=$1 AND created_at < now() - interval '{KEY_TTL}'", uid)
    return status, response, False
