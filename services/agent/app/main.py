import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .models.api import HealthzResponse
from .routers import chat, internal, preferences, threads, transcribe, uploads
from .storage import chat_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await chat_db.init_pool()

    try:
        yield
    finally:
        await chat_db.close_pool()


app = FastAPI(title="agent-service", lifespan=lifespan)

app.include_router(threads.router, prefix="/api/chat")
app.include_router(preferences.router, prefix="/api/chat")
app.include_router(uploads.router, prefix="/api/chat")
app.include_router(transcribe.router, prefix="/api/chat")
app.include_router(chat.router, prefix="/api/chat")
app.include_router(internal.router, prefix="/internal")


@app.get("/healthz", response_model=HealthzResponse)
async def healthz():
    return HealthzResponse(ok=True)
