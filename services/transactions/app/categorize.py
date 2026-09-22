"""Categorization: category_corrections first, LLM second. Shared by POST /transactions
(when category is omitted) and the internal POST /categorize endpoint.

There's no separate merchant field — a merchant/place name, when relevant, lives inside
description itself (e.g. "coffee at Starbucks"), so corrections are keyed purely on the
normalized description. That does mean a correction only reliably reapplies to a
near-identical description; unlike an old merchant-keyed fallback, it can't generalize
"everything from this merchant" across differently-worded items on its own — the LLM
fallback below covers that gap by matching near-duplicate descriptions semantically
against the user's correction history instead of requiring an exact key match."""

import os

import asyncpg
from openai import AsyncOpenAI

CATEGORIES = [
    "groceries", "dining", "transport", "housing", "utilities", "entertainment",
    "health", "shopping", "travel", "income", "fees", "other",
]

# Short definitions so an ambiguous single item (e.g. toothpaste from a minimarket
# that also sells food) lands on the right bucket instead of defaulting to whatever
# category the merchant is best known for.
CATEGORY_DEFINITIONS = {
    "groceries": "raw/packaged food and household consumables bought to prepare or stock at home (rice, produce, snacks, cooking oil, cleaning supplies)",
    "dining": "prepared food and drink consumed out or ordered in (restaurants, cafes, takeout, delivery)",
    "transport": "getting from place to place (fuel, rideshare, public transit, parking, tolls)",
    "housing": "rent, mortgage, home repairs and furnishings",
    "utilities": "recurring service bills (electricity, water, gas, internet, phone plan)",
    "entertainment": "leisure and media (movies, games, streaming, hobbies, events)",
    "health": "pharmacy, medical care, and personal care/hygiene items (toothpaste, soap, medicine, doctor visits)",
    "shopping": "clothing, electronics and other general retail goods not covered above",
    "travel": "flights, hotels, and trip-specific costs",
    "fees": "bank fees, service charges, interest, penalties",
    "other": "anything that genuinely doesn't fit the categories above",
}

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ["LLM_API_KEY"])
    return _client


def normalize_item(description: str | None) -> str:
    return description.strip().lower() if description else ""


async def _lookup_correction(conn: asyncpg.Connection, uid: str, item_key: str) -> str | None:
    row = await conn.fetchrow(
        "SELECT category FROM category_corrections WHERE uid=$1 AND item_key=$2",
        uid, item_key,
    )
    return row["category"] if row else None


async def save_correction(conn: asyncpg.Connection, uid: str, description: str | None, category: str) -> None:
    item_key = normalize_item(description)
    if not item_key:
        return

    await conn.execute(
        """
        INSERT INTO category_corrections (uid, item_key, category)
        VALUES ($1,$2,$3)
        ON CONFLICT (uid, item_key) DO UPDATE SET category = EXCLUDED.category
        """,
        uid, item_key, category,
    )


async def categorize(
    conn: asyncpg.Connection,
    uid: str,
    description: str | None,
    amount_minor: int,
    currency: str,
    txn_type: str,
) -> str:
    if txn_type == "income":
        return "income"

    item_key = normalize_item(description)

    if item_key:
        category = await _lookup_correction(conn, uid, item_key)
        if category:
            return category

    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    # Exact-key lookup above already missed, but that only catches identical
    # description text — an LLM add rarely reproduces the exact same wording twice
    # ("Claude subscription" vs "Claude AI subscription payment", "coffee at
    # Starbucks" vs "Starbucks latte"). Hand the model the user's past corrections
    # directly so it can recognize that kind of near-duplicate itself.
    history_rows = await conn.fetch(
        "SELECT item_key, category FROM category_corrections WHERE uid=$1 LIMIT 200",
        uid,
    )
    history_text = (
        "\n".join(f'- "{r["item_key"]}" -> {r["category"]}' for r in history_rows)
        if history_rows
        else "(none yet)"
    )

    # The category list is a starting point, not a hard enum: the user can type any
    # free-text category via a correction (the table's category cell has no fixed
    # list), and a past correction's category must stay usable here even when it
    # isn't one of the built-in ones — otherwise the model recognizes the match but
    # is structurally unable to apply it, and silently falls back to "other".
    # Keyed by lowercase so the model's (lowercased) answer can be mapped straight
    # back to the exact original casing the user typed — otherwise a reply of "work"
    # would get stored as "work" even when the user's own category is "Work",
    # fragmenting the table into near-duplicate categories over time.
    custom_category_map = {
        r["category"].lower(): r["category"] for r in history_rows if r["category"] not in CATEGORIES
    }
    category_list = "\n".join(f"- {c}: {CATEGORY_DEFINITIONS[c]}" for c in CATEGORIES if c != "income")
    if custom_category_map:
        category_list += "\n" + "\n".join(
            f"- {c}: a category the user created via a past correction (see below) — use it for anything that matches that correction"
            for c in sorted(custom_category_map.values())
        )
    allowed = {c.lower() for c in CATEGORIES if c != "income"} | set(custom_category_map.keys())

    prompt = (
        "Classify this single line item into exactly one of these categories:\n"
        f"{category_list}\n\n"
        f"Item / description: {description or ''}\n"
        f"Amount: {amount_minor} minor units {currency}\n\n"
        "The user has previously corrected these categorizations:\n"
        f"{history_text}\n\n"
        "If this transaction's description clearly describes the same purchase as one "
        "of those corrections — even worded differently, abbreviated, or naming the "
        "merchant/place slightly differently (e.g. \"coffee at Starbucks\" and "
        "\"Starbucks latte\" are the same kind of purchase; \"claude subscription\" "
        "and \"Claude AI subscription payment\" are the same purchase) — use that "
        "correction's category, even if it's a custom one not in the list above. "
        "Otherwise classify based on what the item itself is — the same place can "
        "sell items across several categories in one purchase (e.g. a minimarket "
        "receipt where rice is groceries but toothpaste from the same receipt is "
        "health, not groceries), so don't assume every item from a given place shares "
        "one category. Reply with only the category word, nothing else."
    )
    try:
        resp = await _get_client().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10,
        )
        guess = (resp.choices[0].message.content or "").strip().lower()
        if guess in custom_category_map:
            return custom_category_map[guess]
        return guess if guess in allowed else "other"
    except Exception:
        return "other"
