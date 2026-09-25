"""The `messages.content` JSON column's shape, keyed by the row's own `role` column
(not a self-describing discriminated union — role already lives in a separate DB
column, so the caller picks the right model the same way it already picks branches on
role: str == "user"/"assistant"/"tool")."""

from typing import Any

from pydantic import BaseModel, Field

from .turns import ToolCallRecord


class UserMessageContent(BaseModel):
    text: str


class AssistantMessageContent(BaseModel):
    text: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


class ToolMessageContent(BaseModel):
    tool_call_id: str
    name: str
    result: dict[str, Any]
