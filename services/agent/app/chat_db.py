import contextlib
import json
import os
import uuid

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        os.environ["CHAT_DATABASE_URL"], min_size=1, max_size=3, max_inactive_connection_lifetime=300
    )


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


@contextlib.asynccontextmanager
async def uid_conn(uid: str):
    """A connection whose transaction has app.uid set, so RLS scopes every query in
    the block to this user."""
    assert _pool is not None, "pool not initialized"
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.uid', $1, true)", uid)
            yield conn


# --- threads ---------------------------------------------------------------

async def create_thread(conn: asyncpg.Connection, uid: str, title: str | None = None) -> dict:
    row = await conn.fetchrow(
        "INSERT INTO threads (uid, title) VALUES ($1, $2) RETURNING *", uid, title
    )
    return dict(row)


async def get_thread(conn: asyncpg.Connection, uid: str, thread_id: str) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM threads WHERE uid=$1 AND id=$2", uid, thread_id)


async def list_threads(conn: asyncpg.Connection, uid: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT id, title, summary, created_at, updated_at FROM threads WHERE uid=$1 ORDER BY updated_at DESC",
        uid,
    )


async def touch_thread(conn: asyncpg.Connection, uid: str, thread_id: str) -> None:
    await conn.execute(
        "UPDATE threads SET updated_at = now() WHERE uid=$1 AND id=$2", uid, thread_id
    )


async def update_working_set(conn: asyncpg.Connection, uid: str, thread_id: str, working_set: dict) -> None:
    await conn.execute(
        "UPDATE threads SET working_set = $1, updated_at = now() WHERE uid=$2 AND id=$3",
        json.dumps(working_set), uid, thread_id,
    )


# --- messages ----------------------------------------------------------------

async def insert_message(
    conn: asyncpg.Connection,
    uid: str,
    thread_id: str,
    role: str,
    content: object,
    token_count: int,
    client_msg_id: str | None = None,
    compact: object | None = None,
) -> asyncpg.Record | None:
    """Returns the inserted row, or None if client_msg_id already exists (dedup)."""
    return await conn.fetchrow(
        """
        INSERT INTO messages (thread_id, uid, role, content, compact, token_count, client_msg_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (thread_id, client_msg_id) WHERE client_msg_id IS NOT NULL DO NOTHING
        RETURNING *
        """,
        thread_id, uid, role, json.dumps(content), json.dumps(compact) if compact is not None else None,
        token_count, uuid.UUID(client_msg_id) if client_msg_id else None,
    )


async def recent_messages(conn: asyncpg.Connection, uid: str, thread_id: str, limit: int) -> list[asyncpg.Record]:
    rows = await conn.fetch(
        "SELECT * FROM messages WHERE uid=$1 AND thread_id=$2 ORDER BY seq DESC LIMIT $3",
        uid, thread_id, limit,
    )
    return list(reversed(rows))  # oldest-first for display / prompt assembly


async def all_messages(conn: asyncpg.Connection, uid: str, thread_id: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM messages WHERE uid=$1 AND thread_id=$2 ORDER BY seq ASC", uid, thread_id
    )


async def messages_since(conn: asyncpg.Connection, uid: str, thread_id: str, after_seq: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM messages WHERE uid=$1 AND thread_id=$2 AND seq > $3 ORDER BY seq ASC",
        uid, thread_id, after_seq,
    )


# --- preferences ---------------------------------------------------------------

async def get_preferences(conn: asyncpg.Connection, uid: str) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM user_preferences WHERE uid=$1", uid)


async def set_language(conn: asyncpg.Connection, uid: str, language: str) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO user_preferences (uid, language) VALUES ($1, $2)
        ON CONFLICT (uid) DO UPDATE SET language = EXCLUDED.language
        RETURNING *
        """,
        uid, language,
    )
