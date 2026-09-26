import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from .models.api import HealthzResponse
from .routers import aggregates
from .routers import categorize as categorize_router
from .routers import transactions

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("transactions")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    try:
        yield
    finally:
        await db.close_pool()


app = FastAPI(title="transactions-service", lifespan=lifespan)

app.include_router(transactions.router, prefix="/api/transactions")
app.include_router(aggregates.router, prefix="/api/transactions")
app.include_router(categorize_router.router, prefix="/api/transactions")


@app.get("/healthz", response_model=HealthzResponse)
async def healthz():
    return HealthzResponse(ok=True)
