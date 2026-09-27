"""Category corrections: a category the user chose for a description, reused the next
time that purchase comes up. Keyed purely on the normalized description (there's no
separate merchant field; a merchant name lives inside the description). The agent
reads them (GET /corrections) to categorize; this service only stores them."""

import asyncpg

# How many corrections the agent gets, for its categorization prompt — the most
# recently made ones, so newer choices win once a user has more than this.
LIST_LIMIT = 200


def normalize_item(description: str | None) -> str:
    return description.strip().lower() if description else ""


async def save_correction(conn: asyncpg.Connection, uid: str, description: str | None, category: str) -> None:
    item_key = normalize_item(description)
    if not item_key:
        return
    await conn.execute(
        """
        INSERT INTO category_corrections (uid, item_key, category)
        VALUES ($1,$2,$3)
        ON CONFLICT (uid, item_key) DO UPDATE SET category = EXCLUDED.category, updated_at = now()
        """,
        uid,
        item_key,
        category,
    )


async def list_corrections(conn: asyncpg.Connection, uid: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT item_key, category FROM category_corrections WHERE uid=$1 ORDER BY updated_at DESC LIMIT $2",
        uid,
        LIST_LIMIT,
    )
