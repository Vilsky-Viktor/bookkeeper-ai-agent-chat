import contextlib
import os

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"], min_size=1, max_size=5, max_inactive_connection_lifetime=300
    )


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


@contextlib.asynccontextmanager
async def uid_conn(uid: str):
    """A connection whose transaction has app.uid set, so RLS policies scope every
    query in the block to this user."""
    assert _pool is not None, "pool not initialized"
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.uid', $1, true)", uid)
            yield conn
