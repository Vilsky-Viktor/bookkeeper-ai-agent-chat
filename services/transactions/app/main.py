import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from .routers import aggregates, categorize as categorize_router, transactions

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("transactions")


async def _purge_idempotency_keys_loop() -> None:
    # Stand-in for the daily scheduled purge job (see Production readiness, item on
    # cleaning idempotency_keys). Runs hourly in-process; harmless if it's a no-op.
    while True:
        await asyncio.sleep(3600)
        try:
            async with db._pool.acquire() as conn:  # type: ignore[union-attr]
                await conn.execute(
                    "DELETE FROM idempotency_keys WHERE created_at < now() - interval '24 hours'"
                )
        except Exception:
            log.exception("idempotency purge failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    purge_task = asyncio.create_task(_purge_idempotency_keys_loop())
    try:
        yield
    finally:
        purge_task.cancel()
        await db.close_pool()


app = FastAPI(title="transactions-service", lifespan=lifespan)

app.include_router(transactions.router, prefix="/api/transactions")
app.include_router(aggregates.router, prefix="/api/transactions")
app.include_router(categorize_router.router, prefix="/api/transactions")


@app.get("/healthz")
async def healthz():
    return {"ok": True}
