"""Request/response models for main.py's endpoints."""

import datetime
from typing import Any, Literal

from pydantic import BaseModel


class ChatRequest(BaseModel):
    thread_id: str | None = None
    message: str
    client_msg_id: str | None = None
    receipt_object: str | None = None  # gs object path from a just-completed upload


class PreferencesUpdate(BaseModel):
    language: str


class SummarizeRequest(BaseModel):
    uid: str
    thread_id: str
    through_seq: int


class HealthzResponse(BaseModel):
    ok: bool


class ThreadSummary(BaseModel):
    """Matches chat_db.list_threads' SELECT column list exactly — narrower than
    ThreadOut below, which is what create_thread_endpoint returns (the full row)."""

    id: str
    title: str | None
    summary: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ThreadsListResponse(BaseModel):
    items: list[ThreadSummary]


class ThreadOut(BaseModel):
    """The full `threads` row create_thread_endpoint returns today via `{**thread,
    "id": str(thread["id"])}` — every column, not narrowed, so response_model= here
    can't silently drop a field the frontend currently receives."""

    id: str
    uid: str
    title: str | None
    summary: str | None
    summarized_through: int | None
    working_set: dict[str, str]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class MessageOut(BaseModel):
    seq: int
    role: str
    content: dict[str, Any]  # role-specific shape, see models/message_content.py
    created_at: str


class MessagesPageResponse(BaseModel):
    items: list[MessageOut]
    has_more: bool


class PreferencesOut(BaseModel):
    language: str
    default_currency: str | None


class UploadTargetRequest(BaseModel):
    # The browser converts photos to JPEG before uploading; PDFs go as-is. The signed
    # URL is only valid for this exact Content-Type.
    content_type: Literal["image/jpeg", "application/pdf"] = "image/jpeg"


class UploadTargetOut(BaseModel):
    method: Literal["POST", "PUT"]
    object: str
    url: str


class TranscribeResponse(BaseModel):
    text: str
