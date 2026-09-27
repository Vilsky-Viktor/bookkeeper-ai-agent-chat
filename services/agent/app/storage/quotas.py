"""Per-user daily quotas, counted in the chat DB so every instance sees the same
count."""

import os

import asyncpg
from fastapi import HTTPException

from ..models.notices import NoticeKey

DAILY_TURN_LIMIT = int(os.environ.get("DAILY_TURN_LIMIT", "200"))
DAILY_RECEIPT_LIMIT = int(os.environ.get("DAILY_RECEIPT_LIMIT", "50"))


class LimitReached(HTTPException):
    """A 429 whose user-facing wording is the web app's, by `notice_key`."""

    def __init__(self, notice_key: NoticeKey, detail: str):
        super().__init__(status_code=429, detail=detail)
        self.notice_key: NoticeKey = notice_key


async def increment_and_check_turn(conn: asyncpg.Connection, uid: str) -> None:
    row = await conn.fetchrow(
        """
        INSERT INTO usage_counters (uid, day, turns) VALUES ($1, current_date, 1)
        ON CONFLICT (uid, day) DO UPDATE SET turns = usage_counters.turns + 1
        RETURNING turns
        """,
        uid,
    )

    if row["turns"] > DAILY_TURN_LIMIT:
        raise LimitReached("turnLimitReached", "daily chat turn limit reached")


async def increment_receipt(conn: asyncpg.Connection, uid: str) -> None:
    row = await conn.fetchrow(
        """
        INSERT INTO usage_counters (uid, day, receipts) VALUES ($1, current_date, 1)
        ON CONFLICT (uid, day) DO UPDATE SET receipts = usage_counters.receipts + 1
        RETURNING receipts
        """,
        uid,
    )

    if row["receipts"] > DAILY_RECEIPT_LIMIT:
        raise LimitReached("receiptLimitReached", "daily receipt limit reached")


async def add_tokens(conn: asyncpg.Connection, uid: str, tokens: int) -> None:
    await conn.execute(
        """
        INSERT INTO usage_counters (uid, day, tokens) VALUES ($1, current_date, $2)
        ON CONFLICT (uid, day) DO UPDATE SET tokens = usage_counters.tokens + $2
        """,
        uid,
        tokens,
    )
