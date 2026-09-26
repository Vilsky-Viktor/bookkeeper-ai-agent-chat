"""Categorizer eval: accuracy and cost of candidate models on labeled items, through
the real classify() — one item per call (as when a chat add is categorized) and six
per call (a receipt).

Two groups: plain items (what the model knows on its own: brands, languages,
tobacco/alcohol, ambiguous ones), and items judged against a correction history (it
should reuse a matching correction, but not copy one onto an unrelated item from the
same shop).

Run inside the agent container (it has LLM_API_KEY and mounts this folder):
    docker compose exec agent uv run python -m evals.categorize_eval \\
        --models gpt-4o gpt-4o-mini --runs 3
"""

import argparse
import asyncio
from collections import defaultdict

from langchain_core.callbacks import get_usage_metadata_callback

from app.categorize import classify
from app.models.categorize import Correction

# (description, acceptable categories). Descriptions are shaped like the agent sends
# them: item name plus " - merchant" when one is known.
PLAIN: list[tuple[str, set[str]]] = [
    # groceries
    ("Rice 5kg - Indomaret", {"groceries"}),
    ("Fresh milk 1L - Carrefour", {"groceries"}),
    ("Eggs 12pcs - Tesco", {"groceries"}),
    ("Indomie goreng x5 - Alfamart", {"groceries"}),
    ("Dish soap 750ml - Walmart", {"groceries"}),
    ("Susu UHT 1L - Indomaret", {"groceries"}),
    ("Pan integral - Mercadona", {"groceries"}),
    ("Olive oil - Lidl", {"groceries"}),
    # dining
    ("Nasi goreng - Warung Jakarta", {"dining"}),
    ("Latte - Starbucks", {"dining"}),
    ("Big Mac meal - McDonald's", {"dining"}),
    ("Food delivery order - Warung Jakarta, Tabanan", {"dining"}),
    ("Dinner for two - Trattoria Roma", {"dining"}),
    ("Кофе латте - Coffee Bean", {"dining"}),
    # transport
    ("Grab ride to airport", {"transport"}),
    ("Pertamax 20L - Pertamina", {"transport"}),
    ("Parking fee - Mall parking", {"transport"}),
    ("Metro card top-up", {"transport"}),
    # health (incl. brand-only personal care)
    ("Laurier Rlx 30cm 24s - Indomaret", {"health"}),
    ("Pantene shampoo 170ml - Alfamart", {"health"}),
    ("Paracetamol 500mg - Guardian", {"health"}),
    ("Colgate toothpaste - Watsons", {"health"}),
    ("Always Ultra pads - CVS", {"health"}),
    ("Obat batuk - Apotek K24", {"health"}),
    ("Dental checkup - Smile Clinic", {"health"}),
    # shopping (incl. tobacco/alcohol, per CATEGORY_DEFINITIONS)
    ("Camel White 20's - Indomaret", {"shopping"}),
    ("Marlboro Red - 7-Eleven", {"shopping"}),
    ("Heineken 6-pack - Circle K", {"shopping"}),
    ("Nike running shoes", {"shopping"}),
    ("USB-C cable - Anker", {"shopping"}),
    ("Uniqlo t-shirt", {"shopping"}),
    # entertainment
    ("Netflix monthly subscription", {"entertainment"}),
    ("Cinema tickets - CGV", {"entertainment"}),
    ("Steam game purchase", {"entertainment"}),
    ("Spotify Premium", {"entertainment"}),
    # utilities
    ("PLN electricity token", {"utilities"}),
    ("Internet bill - IndiHome", {"utilities"}),
    ("Phone plan - Telkomsel", {"utilities"}),
    # housing
    ("Monthly rent - Ashana Village", {"housing"}),
    ("IKEA bookshelf", {"housing", "shopping"}),
    ("Plumber repair visit", {"housing"}),
    # travel
    ("Hotel booking - Agoda", {"travel"}),
    ("Flight Denpasar-Jakarta - Garuda", {"travel"}),
    # fees
    ("Bank transfer fee - BCA", {"fees"}),
    ("Late payment fee - credit card", {"fees"}),
    ("ATM withdrawal fee", {"fees"}),
]

# (correction history as (item_key, category), description, acceptable categories)
WITH_HISTORY: list[tuple[list[tuple[str, str]], str, set[str]]] = [
    ([("claude subscription", "Work Tools")], "Claude AI subscription payment", {"Work Tools"}),
    ([("3x camel white 20", "entertainment")], "Camel Act.P Mint 20s - Indomaret", {"entertainment"}),
    ([("coffee at starbucks", "dining")], "Starbucks caramel latte", {"dining"}),
    ([("fitness first membership", "health")], "Fitness First monthly fee", {"health"}),
    # Same shop, unrelated item: the correction must not be copied over.
    ([("rice - indomaret", "Household")], "Laurier pads - Indomaret", {"health"}),
    ([("uber eats order", "Takeaway")], "Uber ride to office", {"transport"}),
]

RECEIPT_SIZE = 6  # items per call in the "receipt batch" group

# USD per 1M tokens (input, output) — list prices at the time of writing.
PRICES = {"gpt-4o": (2.50, 10.00), "gpt-4o-mini": (0.15, 0.60), "gpt-4.1-mini": (0.40, 1.60)}


async def _classify(model: str, descriptions: list[str], history: list[tuple[str, str]], usage: dict) -> list[str]:
    """classify() with 429 retries: low rate-limit tiers would otherwise fail runs."""
    corrections = [Correction(item_key=k, category=c) for k, c in history]
    for attempt in range(10):
        try:
            with get_usage_metadata_callback() as cb:
                result = await classify(descriptions, corrections, model)
            for u in cb.usage_metadata.values():
                usage["calls"] += 1
                usage["in"] += u.get("input_tokens", 0)
                usage["out"] += u.get("output_tokens", 0)
            return result
        except Exception as e:
            if "429" not in str(e):
                raise
            await asyncio.sleep(5 * (attempt + 1))
    raise RuntimeError("still rate-limited after retries")


async def run_model(model: str, runs: int, concurrency: int) -> dict:
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, list[tuple[str, str, set[str]]]] = defaultdict(list)
    usage: dict[str, dict] = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0})

    async def one(group: str, items: list[tuple[str, set[str]]], history: list[tuple[str, str]]):
        async with sem:
            got = await _classify(model, [d for d, _ in items], history, usage[group])
        results[group] += [(d, g, ok) for (d, ok), g in zip(items, got)]

    jobs = []
    for _ in range(runs):
        jobs += [one("single", [(d, ok)], []) for d, ok in PLAIN]
        jobs += [one("history", [(d, ok)], h) for h, d, ok in WITH_HISTORY]
        jobs += [one("batch", PLAIN[i : i + RECEIPT_SIZE], []) for i in range(0, len(PLAIN), RECEIPT_SIZE)]
    await asyncio.gather(*jobs)
    return {"results": results, "usage": usage}


def _cost_per_call(model: str, usage: dict) -> str:
    if model not in PRICES or not usage["calls"]:
        return "n/a"
    p_in, p_out = PRICES[model]
    return f"${(usage['in'] * p_in + usage['out'] * p_out) / 1_000_000 / usage['calls']:.5f}"


async def main(models: list[str], runs: int, concurrency: int) -> None:
    report = {m: await run_model(m, runs, concurrency) for m in models}
    groups = [("single", "one item per call"), ("history", "with corrections"), ("batch", "receipt (6 per call)")]
    print(f"\n{'':24}" + "".join(f"{m:>16}" for m in models))
    for key, label in groups:
        cells = []
        for m in models:
            rs = report[m]["results"][key]
            correct = sum(1 for _, got, ok in rs if got in ok)
            cells.append(f"{correct}/{len(rs)} {100 * correct / len(rs):3.0f}%".rjust(16))
        print(f"{label:24}" + "".join(cells))
    for key, label in (("single", "cost per call, 1 item"), ("batch", "cost per call, 6 items")):
        print(f"{label:24}" + "".join(_cost_per_call(m, report[m]["usage"][key]).rjust(16) for m in models))

    print("\nMisses (description: got -> expected):")
    for m in models:
        misses: dict[tuple[str, str], int] = defaultdict(int)
        for key, _ in groups:
            for desc, got, ok in report[m]["results"][key]:
                if got not in ok:
                    misses[(f"[{key}] {desc}", f"{got} -> {'/'.join(sorted(ok))}")] += 1
        print(f"  {m}: {'none' if not misses else ''}")
        for (desc, detail), n in sorted(misses.items()):
            print(f"    {desc}: {detail} (x{n})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["gpt-4o", "gpt-4o-mini"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(main(args.models, args.runs, args.concurrency))
