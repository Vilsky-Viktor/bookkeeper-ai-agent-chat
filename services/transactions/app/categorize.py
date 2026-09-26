"""Categorization: category_corrections first, LLM second. Shared by POST /transactions
(when category is omitted) and the internal POST /categorize endpoint.

There's no separate merchant field — a merchant/place name, when relevant, lives inside
description itself (e.g. "coffee at Starbucks"), so corrections are keyed purely on the
normalized description. That does mean a correction only reliably reapplies to a
near-identical description; unlike an old merchant-keyed fallback, it can't generalize
"everything from this merchant" across differently-worded items on its own — the LLM
fallback below covers that gap by matching near-duplicate descriptions semantically
against the user's correction history instead of requiring an exact key match."""

import json
import logging
import os
from typing import NamedTuple

import asyncpg
from openai import AsyncOpenAI

from .money import to_decimal_string

CATEGORIES = [
    "groceries",
    "dining",
    "transport",
    "housing",
    "utilities",
    "entertainment",
    "health",
    "shopping",
    "travel",
    "income",
    "fees",
    "other",
]

# Short definitions so an ambiguous single item (e.g. toothpaste from a minimarket
# that also sells food) lands on the right bucket instead of defaulting to whatever
# category the merchant is best known for.
CATEGORY_DEFINITIONS = {
    "groceries": "raw/packaged food and household consumables bought to prepare or stock at home (rice, produce, snacks, cooking oil, cleaning supplies) — food and consumables ONLY: tobacco and alcohol bought from a grocery store or minimarket are not food, so they belong in shopping instead, not groceries just because of where they were bought",
    "dining": "prepared food and drink consumed out or ordered in (restaurants, cafes, takeout, delivery)",
    "transport": "getting from place to place (fuel, rideshare, public transit, parking, tolls)",
    "housing": "rent, mortgage, home repairs and furnishings",
    "utilities": "recurring service bills (electricity, water, gas, internet, phone plan)",
    "entertainment": "leisure and media (movies, games, streaming, hobbies, events)",
    "health": "pharmacy, medical care, and personal care/hygiene items (toothpaste, soap, medicine, doctor visits)",
    "shopping": "clothing, electronics, tobacco, alcohol, and other general retail goods not covered above",
    "travel": "flights, hotels, and trip-specific costs",
    "fees": "bank fees, service charges, interest, penalties",
    "other": "anything that genuinely doesn't fit the categories above",
}

log = logging.getLogger("categorize")

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
        uid,
        item_key,
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
        uid,
        item_key,
        category,
    )


def _log_usage(kind: str, resp) -> None:
    # This service isn't traced in LangSmith (the agent is), so its spend is visible
    # only through this log line.
    usage = getattr(resp, "usage", None)
    if usage:
        log.info("%s tokens: in=%s out=%s model=%s", kind, usage.prompt_tokens, usage.completion_tokens, resp.model)


# Its own setting, independent of the agent's LLM_MODEL (both read the same .env).
# gpt-4o by default: side by side on real receipt items, the mini models misfiled
# brand-only names (e.g. "Laurier" sanitary pads as groceries) that gpt-4o got right.
# Cost is contained instead by categorize_many's one call per receipt; set this to
# gpt-4o-mini to trade that accuracy for a ~16x cheaper call.
CATEGORIZE_MODEL = os.environ.get("LLM_CATEGORIZE_MODEL", "gpt-4o")

_MATCHING_RULES = (
    "If a description clearly describes the same purchase as one of those "
    "corrections — even worded differently, abbreviated, or naming the merchant/place "
    'slightly differently (e.g. "coffee at Starbucks" and "Starbucks latte" are the '
    'same kind of purchase; "claude subscription" and "Claude AI subscription '
    "payment\" are the same purchase) — use that correction's category, even if it's "
    "a custom one not in the list above. Otherwise classify based on what the item "
    "itself is — the same place can sell items across several categories in one "
    "purchase (e.g. a minimarket receipt where rice is groceries but toothpaste from "
    "the same receipt is health, not groceries), so don't assume every item from a "
    "given place shares one category."
)


class _Context(NamedTuple):
    category_list: str
    history_text: str
    custom_category_map: dict[str, str]
    allowed: set[str]


async def _classification_context(conn: asyncpg.Connection, uid: str) -> _Context:
    # An exact-key lookup only catches identical description text — an LLM add rarely
    # reproduces the exact same wording twice ("Claude subscription" vs "Claude AI
    # subscription payment"). Hand the model the user's past corrections directly so
    # it can recognize that kind of near-duplicate itself.
    history_rows = await conn.fetch(
        "SELECT item_key, category FROM category_corrections WHERE uid=$1 LIMIT 200",
        uid,
    )
    history_text = (
        "\n".join(f'- "{r["item_key"]}" -> {r["category"]}' for r in history_rows) if history_rows else "(none yet)"
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
    return _Context(category_list, history_text, custom_category_map, allowed)


def _resolve(guess: str, ctx: _Context) -> str:
    guess = guess.strip().lower()
    if guess in ctx.custom_category_map:
        return ctx.custom_category_map[guess]
    return guess if guess in ctx.allowed else "other"


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

    ctx = await _classification_context(conn, uid)
    prompt = (
        "Classify this single line item into exactly one of these categories:\n"
        f"{ctx.category_list}\n\n"
        f"Item / description: {description or ''}\n"
        f"Amount: {to_decimal_string(amount_minor, currency)} {currency}\n\n"
        "The user has previously corrected these categorizations:\n"
        f"{ctx.history_text}\n\n"
        f"{_MATCHING_RULES} Reply with only the category word, nothing else."
    )
    try:
        resp = await _get_client().chat.completions.create(
            model=CATEGORIZE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10,
        )
        _log_usage("categorize", resp)
        return _resolve(resp.choices[0].message.content or "", ctx)
    except Exception:
        return "other"


async def categorize_many(conn: asyncpg.Connection, uid: str, descriptions: list[str]) -> list[str]:
    """Categorizes several expense descriptions (a receipt's items) with at most ONE
    model call: exact corrections are applied first, and everything left goes into a
    single prompt instead of one call per item, so the category definitions and
    correction history are sent once."""
    keys = [normalize_item(d) for d in descriptions]
    rows = await conn.fetch(
        "SELECT item_key, category FROM category_corrections WHERE uid=$1 AND item_key = ANY($2::text[])",
        uid,
        [k for k in keys if k],
    )
    corrected = {r["item_key"]: r["category"] for r in rows}
    results: list[str | None] = [corrected.get(k) if k else None for k in keys]
    pending = [i for i, r in enumerate(results) if r is None]
    if not pending:
        return [r or "other" for r in results]

    ctx = await _classification_context(conn, uid)
    numbered = "\n".join(f"{n + 1}. {descriptions[i]}" for n, i in enumerate(pending))
    prompt = (
        "Classify each of these line items into exactly one of these categories:\n"
        f"{ctx.category_list}\n\n"
        f"Items:\n{numbered}\n\n"
        "The user has previously corrected these categorizations:\n"
        f"{ctx.history_text}\n\n"
        f"{_MATCHING_RULES} Reply with JSON only, in this shape: "
        '{"categories": ["<category word for item 1>", "<category word for item 2>", ...]} '
        "— exactly one entry per item, in the same order."
    )
    try:
        resp = await _get_client().chat.completions.create(
            model=CATEGORIZE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=12 * len(pending) + 20,
            response_format={"type": "json_object"},
        )
        _log_usage("categorize_batch", resp)
        guesses = json.loads(resp.choices[0].message.content or "{}").get("categories", [])
    except Exception:
        guesses = []
    for n, i in enumerate(pending):
        results[i] = _resolve(guesses[n], ctx) if n < len(guesses) and isinstance(guesses[n], str) else "other"
    return [r or "other" for r in results]
