"""Chat threads: listing, creating, a thread's messages, and recording a confirmed
receipt card."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_uid
from ..helpers.serializers import message_out
from ..models.api import MessagesPageResponse, ReceiptSavedRequest, ThreadOut, ThreadsListResponse, ThreadSummary
from ..models.message_content import AssistantMessageContent
from ..models.notices import Notice
from ..storage import chat_db

router = APIRouter()


@router.get("/threads", response_model=ThreadsListResponse)
async def list_threads(uid: str = Depends(require_uid)):
    async with chat_db.uid_conn(uid) as conn:
        rows = await chat_db.list_threads(conn, uid)

    # asyncpg decodes the uuid column as a real uuid.UUID, not str — ThreadSummary.id
    # is str (matching what the wire format has always been), so this needs the same
    # explicit str() conversion create_thread_endpoint below already does.
    return ThreadsListResponse(items=[ThreadSummary(**{**dict(r), "id": str(r["id"])}) for r in rows])


@router.post("/threads", status_code=201, response_model=ThreadOut)
async def create_thread_endpoint(uid: str = Depends(require_uid)):
    async with chat_db.uid_conn(uid) as conn:
        thread = await chat_db.create_thread(conn, uid)
    # asyncpg doesn't decode jsonb columns on its own — working_set comes back as the
    # raw JSON text, same as context/__init__.py's build_context() already has to
    # handle defensively.
    working_set = thread["working_set"]

    if isinstance(working_set, str):
        working_set = json.loads(working_set) if working_set else {}

    return ThreadOut(**{**thread, "id": str(thread["id"]), "working_set": working_set})


@router.get("/threads/{thread_id}/messages", response_model=MessagesPageResponse)
async def get_messages(
    thread_id: str,
    before_seq: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    uid: str = Depends(require_uid),
):
    async with chat_db.uid_conn(uid) as conn:
        thread = await chat_db.get_thread(conn, uid, thread_id)

        if thread is None:
            raise HTTPException(status_code=404, detail="thread not found")
        rows, has_more = await chat_db.messages_page(conn, uid, thread_id, before_seq, limit)

    return MessagesPageResponse(items=[message_out(r) for r in rows], has_more=has_more)


@router.post("/threads/{thread_id}/receipt-saved", status_code=204)
async def receipt_saved(thread_id: uuid.UUID, body: ReceiptSavedRequest, uid: str = Depends(require_uid)):
    """The user confirmed a receipt card; the web app saved it straight to the
    transactions service. Recorded in the thread so the confirmation survives a reload
    and the model knows the receipt was saved."""
    notice = Notice(key="savedTransactions", params={"n": str(body.count)})

    async with chat_db.uid_conn(uid) as conn:
        if await chat_db.get_thread(conn, uid, str(thread_id)) is None:
            raise HTTPException(status_code=404, detail="thread not found")

        await chat_db.insert_message(
            conn, uid, str(thread_id), "assistant", AssistantMessageContent(text="", notice=notice).model_dump(), 0
        )
