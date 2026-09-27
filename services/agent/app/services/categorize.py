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

from ..constants.categories import CATEGORIES
from ..integrations import llm
from ..models.categorize import Correction
from ..prompts.categorize import CATEGORIZE_PROMPT, CATEGORY_DEFINITIONS, MATCHING_RULES

log = logging.getLogger("categorize")


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
    prompt = CATEGORIZE_PROMPT.format(
        category_list=category_list, items=numbered, history=history, matching_rules=MATCHING_RULES
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
