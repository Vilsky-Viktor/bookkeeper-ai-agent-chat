"""Chat DB rows to API response models (main.py)."""

import json

from .models.api import MessageOut


def message_out(row) -> MessageOut:
    content = row["content"]
    content = json.loads(content) if isinstance(content, str) else content

    return MessageOut(
        seq=row["seq"],
        role=row["role"],
        content=content,
        created_at=row["created_at"].isoformat(),
    )
