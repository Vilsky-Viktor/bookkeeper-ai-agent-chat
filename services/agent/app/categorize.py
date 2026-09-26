"""Categorization: the user's saved corrections first, the model second, for every
expense the agent creates (add_transaction) or proposes (extract_receipt) — one item
or a whole receipt, always in at most one model call.

Corrections are stored by the transactions service; this module only reads them.
They're keyed on the normalized description (a merchant name lives inside the
description; there's no separate merchant field). An exact match applies directly;
for near-duplicates ("Claude subscription" vs "Claude AI subscription payment") the
model sees the user's corrections and decides."""

import json
import logging

import httpx
from langchain_core.messages import HumanMessage

from . import llm
from .models.categorize import Correction

log = logging.getLogger("categorize")

# Also the web app's category keys (web/src/lib/i18n/locales/en.ts);
# tests/test_contracts.py fails if they drift.
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

# Short definitions so an ambiguous item (e.g. toothpaste from a minimarket that also
# sells food) lands on the right bucket instead of the merchant's usual one. "income"
# has none: it's never guessed, only set for income transactions.
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


def normalize_item(description: str | None) -> str:
    return description.strip().lower() if description else ""


async def fetch_corrections(client: httpx.AsyncClient) -> list[Correction]:
    """The user's corrections (the client carries their JWT). Best effort: without
    them categorization still works, just without the user's history."""
    try:
        resp = await client.get("/api/transactions/corrections")
        resp.raise_for_status()
        return [Correction.model_validate(item) for item in resp.json().get("items", [])]
    except (httpx.HTTPError, ValueError):
        log.warning("couldn't load category corrections; categorizing without them", exc_info=True)
        return []


async def classify(descriptions: list[str], corrections: list[Correction], model: str | None = None) -> list[str]:
    """One model call for all descriptions. Raises if the call fails or the reply
    doesn't parse; categorize() turns that into "other"."""
    # Custom categories from corrections are allowed answers too, or the model could
    # recognize a match but never apply it. Keyed by lowercase so its (lowercased)
    # reply maps back to the user's own casing ("work" -> "Work").
    custom = {c.category.lower(): c.category for c in corrections if c.category not in CATEGORIES}
    category_list = "\n".join(f"- {c}: {CATEGORY_DEFINITIONS[c]}" for c in CATEGORIES if c != "income")
    if custom:
        category_list += "\n" + "\n".join(
            f"- {c}: a category the user created via a past correction (see below) — use it for anything that matches that correction"
            for c in sorted(custom.values())
        )
    history = "\n".join(f'- "{c.item_key}" -> {c.category}' for c in corrections) or "(none yet)"
    numbered = "\n".join(f"{n + 1}. {d}" for n, d in enumerate(descriptions))
    prompt = (
        "Classify each of these line items into exactly one of these categories:\n"
        f"{category_list}\n\n"
        f"Items:\n{numbered}\n\n"
        "The user has previously corrected these categorizations:\n"
        f"{history}\n\n"
        f"{_MATCHING_RULES} Reply with JSON only, in this shape: "
        '{"categories": ["<category word for item 1>", "<category word for item 2>", ...]} '
        "— exactly one entry per item, in the same order."
    )
    response = await llm.categorize_model(len(descriptions), model).ainvoke(
        [HumanMessage(content=prompt)], config={"run_name": "categorize", "tags": ["categorize"]}
    )
    text = response.content if isinstance(response.content, str) else str(response.content)
    guesses = json.loads(text or "{}").get("categories", [])

    allowed = {c for c in CATEGORIES if c != "income"}
    resolved = []
    for n in range(len(descriptions)):
        guess = guesses[n].strip().lower() if n < len(guesses) and isinstance(guesses[n], str) else ""
        resolved.append(custom.get(guess) or (guess if guess in allowed else "other"))
    return resolved


async def categorize(descriptions: list[str], corrections: list[Correction]) -> list[str]:
    """A category per description: an exact correction when there is one, the model
    (one call) for the rest, "other" if that call fails."""
    exact = {c.item_key: c.category for c in corrections}
    results: list[str | None] = [exact.get(normalize_item(d)) if normalize_item(d) else None for d in descriptions]
    pending = [i for i, r in enumerate(results) if r is None]
    if pending:
        try:
            guesses = await classify([descriptions[i] for i in pending], corrections)
        except Exception:
            log.warning("categorization failed; using 'other'", exc_info=True)
            guesses = ["other"] * len(pending)
        for n, i in enumerate(pending):
            results[i] = guesses[n]
    return [r or "other" for r in results]
