"""Categorizer eval: accuracy and cost of candidate models on labeled items, through
the real categorize() (one item, as when the agent adds a transaction) and
categorize_many() (a receipt's items in one call) — with the database mocked, so
only the model is called.

Two groups: plain items (what the model knows on its own: brands, languages,
tobacco/alcohol, ambiguous ones), and items judged against a correction history (it
should reuse a matching correction, but not copy one onto an unrelated item from the
same shop).

Run inside the transactions container (it has LLM_API_KEY and mounts this folder):
    docker compose exec transactions uv run python -m evals.categorize_eval \\
        --models gpt-4o gpt-4o-mini --runs 3
"""

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

from openai import RateLimitError

from app import categorize as cat

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

RECEIPT_SIZE = 6  # items per categorize_many() call

# USD per 1M tokens (input, output) — list prices at the time of writing.
PRICES = {"gpt-4o": (2.50, 10.00), "gpt-4o-mini": (0.15, 0.60), "gpt-4.1-mini": (0.40, 1.60)}


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_mode: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0, 0]))  # calls, in, out


def _install_client_spy(usage: Usage, mode: dict) -> None:
    """Counts tokens per call and retries 429s: categorize() turns any exception into
    "other", so an unretried rate limit would silently count as a wrong answer."""
    client = cat._get_client()
    real_create = client.chat.completions.create

    async def create(**kwargs):
        for attempt in range(10):
            try:
                resp = await real_create(**kwargs)
                break
            except RateLimitError:
                await asyncio.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError("still rate-limited after retries")
        u = resp.usage
        usage.calls += 1
        usage.input_tokens += u.prompt_tokens
        usage.output_tokens += u.completion_tokens
        m = usage.by_mode[mode["name"]]
        m[0] += 1
        m[1] += u.prompt_tokens
        m[2] += u.completion_tokens
        return resp

    client.chat.completions.create = create  # type: ignore[method-assign]


def _conn(history: list[tuple[str, str]]) -> AsyncMock:
    """No exact-match correction (so the model is always asked); `history` is what
    the prompt's correction list contains."""
    rows = [{"item_key": k, "category": c} for k, c in history]
    conn = AsyncMock()
    conn.fetchrow.return_value = None

    async def fetch(sql, *args):
        return [] if "ANY(" in sql else rows

    conn.fetch.side_effect = fetch
    return conn


async def _single(description: str, history: list[tuple[str, str]]) -> str:
    return await cat.categorize(_conn(history), "eval", description, 10000, "IDR", "expense")


async def run_model(model: str, runs: int, concurrency: int) -> dict:
    cat.CATEGORIZE_MODEL = model
    usage = Usage()
    mode = {"name": ""}
    _install_client_spy(usage, mode)
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, list[tuple[str, str, set[str]]]] = defaultdict(list)  # mode -> (desc, got, ok)

    async def one_single(desc, history, ok, group):
        async with sem:
            results[group].append((desc, await _single(desc, history), ok))

    for _ in range(runs):
        mode["name"] = "single"
        await asyncio.gather(*(one_single(d, [], ok, "single") for d, ok in PLAIN))
        mode["name"] = "history"
        await asyncio.gather(*(one_single(d, h, ok, "history") for h, d, ok in WITH_HISTORY))
        mode["name"] = "batch"
        for i in range(0, len(PLAIN), RECEIPT_SIZE):
            chunk = PLAIN[i : i + RECEIPT_SIZE]
            got = await cat.categorize_many(_conn([]), "eval", [d for d, _ in chunk])
            results["batch"] += [(d, g, ok) for (d, ok), g in zip(chunk, got)]
    return {"results": results, "usage": usage}


def _cost(model: str, calls_in_out: list[int]) -> float | None:
    if model not in PRICES:
        return None
    p_in, p_out = PRICES[model]
    return (calls_in_out[1] * p_in + calls_in_out[2] * p_out) / 1_000_000


async def main(models: list[str], runs: int, concurrency: int) -> None:
    report = {m: await run_model(m, runs, concurrency) for m in models}
    groups = [("single", "one item (chat add)"), ("history", "with corrections"), ("batch", "receipt batch")]
    print(f"\n{'':24}" + "".join(f"{m:>16}" for m in models))
    for key, label in groups:
        cells = []
        for m in models:
            rs = report[m]["results"][key]
            correct = sum(1 for _, got, ok in rs if got in ok)
            cells.append(f"{correct}/{len(rs)} {100 * correct / len(rs):3.0f}%".rjust(16))
        print(f"{label:24}" + "".join(cells))
    for key, label in (("single", "cost per call, single"), ("batch", "cost per receipt call")):
        cells = []
        for m in models:
            c = report[m]["usage"].by_mode[key]
            cost = _cost(m, c)
            cells.append((f"${cost / c[0]:.5f}" if cost is not None and c[0] else "n/a").rjust(16))
        print(f"{label:24}" + "".join(cells))

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
