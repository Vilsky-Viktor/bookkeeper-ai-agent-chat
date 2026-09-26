"""Chat-model eval: replays the agent's known failure modes (the ones SYSTEM_PROMPT's
clauses exist to prevent) plus core behaviors against candidate models, to decide
whether a cheaper model can run the chat controller.

Each case is built with the production context builder, system prompt and compact
tool schemas; tool calls are answered with canned results, so nothing touches the
transactions service or real data. Only the model under test is called.

Run inside the agent container (it has LLM_API_KEY and TRANSACTIONS_URL set):
    docker cp services/agent/evals bookkeeper-chat-agent-1:/app/
    docker exec bookkeeper-chat-agent-1 uv run python -m evals.chat_model_eval \\
        --models gpt-4o gpt-4.1-mini --runs 3
"""

import argparse
import asyncio
import datetime
import json
import re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass, field
from typing import Callable

from langchain_core.messages import AIMessage, ToolMessage

from app import llm
from app.context import build_context
from app.graph import _compact_tool_schema
from app.tools import build_tools

TODAY = datetime.date.today()
YESTERDAY = TODAY - datetime.timedelta(days=1)
DOWNLOAD_SENTENCE = "You can download it by clicking the file below."

# Newest first, like the real query_transactions.
TRANSACTIONS = [
    {
        "id": "t-latte",
        "occurred_on": str(TODAY),
        "type": "expense",
        "amount": "6.50",
        "currency": "USD",
        "category": "dining",
        "description": "latte at Starbucks",
    },
    {
        "id": "t-bagel",
        "occurred_on": str(YESTERDAY),
        "type": "expense",
        "amount": "3.20",
        "currency": "USD",
        "category": "dining",
        "description": "bagel at Joe's Deli",
    },
    {
        "id": "t-taxi",
        "occurred_on": str(YESTERDAY),
        "type": "expense",
        "amount": "25.00",
        "currency": "EUR",
        "category": "transport",
        "description": "taxi to the airport",
    },
    {
        "id": "t-rice",
        "occurred_on": str(TODAY - datetime.timedelta(days=3)),
        "type": "expense",
        "amount": "54000",
        "currency": "IDR",
        "category": "groceries",
        "description": "rice purchased at a minimarket",
    },
]
BY_ID = {t["id"]: t for t in TRANSACTIONS}

# USD per 1M tokens: (input, cached input, output). List prices at the time of
# writing — check the provider's pricing page before relying on the totals.
PRICES = {
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
}


def fake_result(name: str, args: dict) -> dict:
    if name == "query_transactions":
        if args.get("aggregate"):
            return {
                "totals": [
                    {
                        "month": TODAY.strftime("%Y-%m"),
                        "currency": "USD",
                        "category": "dining",
                        "expense": "9.70",
                        "income": "0",
                    }
                ]
            }
        needle = (args.get("description") or "").lower()
        rows = [t for t in TRANSACTIONS if needle in t["description"].lower()]
        if args.get("category"):
            rows = [t for t in rows if t["category"] == args["category"]]
        return {"items": rows, "next_cursor": None}
    if name in ("edit_transaction", "delete_transaction"):
        txn = BY_ID.get(args.get("transaction_id", ""))
        if txn is None:
            return {"error": "transaction not found"}
        return {"deleted": txn["id"]} if name == "delete_transaction" else {**txn, **args, "id": txn["id"]}
    if name == "add_transaction":
        return {"id": "t-new", **args, "category": "dining"}
    if name == "delete_transactions_matching":
        return {"deleted": len(TRANSACTIONS)}
    if name == "get_exchange_rate":
        return {
            "from": args.get("from_currency"),
            "to": args.get("to_currency"),
            "rate": 0.92,
            "date": str(TODAY),
            "note": "Daily reference rate, not real-time.",
        }
    if name == "get_total_in_currency":
        return {"total": "47.61", "currency": args.get("to_currency"), "breakdown": []}
    if name == "set_filter":
        return {"filter": {k: v for k, v in args.items() if v not in (None, "")}}
    if name == "export_transactions":
        return {}
    if name == "extract_receipt":
        return {
            "items": [
                {
                    "occurred_on": str(TODAY),
                    "type": "expense",
                    "amount": "12.40",
                    "currency": "USD",
                    "category": "groceries",
                    "description": "Groceries - Corner Shop",
                    "receipt_uri": "gs://b/x",
                }
            ],
            "receipt_uri": "gs://b/x",
        }
    return {"error": f"unknown tool {name}"}


# --- history rows, in chat_db's shape ------------------------------------------------


def user(text: str) -> dict:
    return {"role": "user", "content": {"text": text}, "compact": None}


def assistant(text: str, calls: list[tuple[str, str, dict]] = ()) -> dict:  # type: ignore[assignment]
    return {
        "role": "assistant",
        "compact": None,
        "content": {"text": text, "tool_calls": [{"id": i, "name": n, "args": a} for i, n, a in calls]},
    }


def tool(call_id: str, name: str, result: dict) -> dict:
    return {"role": "tool", "compact": None, "content": {"tool_call_id": call_id, "name": name, "result": result}}


@dataclass
class Run:
    calls: list[tuple[str, dict]]
    text: str
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0

    def called(self, name: str) -> list[dict]:
        return [a for n, a in self.calls if n == name]


@dataclass
class Case:
    name: str
    message: str
    check: Callable[[Run], str | None]  # None = pass, else the failure reason
    history: list[dict] = field(default_factory=list)
    working_set: dict = field(default_factory=dict)
    summary: str | None = None
    language: str = "en"


def expect(condition: bool, reason: str) -> str | None:
    return None if condition else reason


def _amount_is(value, target: str) -> bool:
    try:
        return Decimal(str(value)) == Decimal(target)
    except InvalidOperation:
        return False


def _check_marker_edit(r: Run) -> str | None:
    edits = r.called("edit_transaction")
    return expect(
        any(e.get("transaction_id") == "t-taxi" and _amount_is(e.get("amount"), "30") for e in edits),
        f"no edit_transaction(t-taxi, amount=30); calls={r.calls}",
    )


def _check_delete_last(r: Run) -> str | None:
    deleted = [a.get("transaction_id") for a in r.called("delete_transaction")]
    if not r.called("query_transactions"):
        return f"didn't re-query the table first; calls={r.calls}"
    return expect(all(d == "t-latte" for d in deleted), f"deleted the wrong row: {deleted}")


def _check_bagel(r: Run) -> str | None:
    searched = any("bagel" in (a.get("description") or "").lower() for a in r.called("query_transactions"))
    deleted = [a.get("transaction_id") for a in r.called("delete_transaction")]
    if not searched and "t-bagel" not in deleted:
        return f"didn't search for the bagel; calls={r.calls}"
    return expect(all(d == "t-bagel" for d in deleted), f"deleted the wrong row: {deleted}")


def _check_filter(r: Run) -> str | None:
    calls = r.called("set_filter")
    if not calls:
        return f"no set_filter call; calls={r.calls}"
    f = calls[-1]
    first_of_this_month = TODAY.replace(day=1)
    last_month_end = first_of_this_month - datetime.timedelta(days=1)
    want = {
        "currency": "USD",
        "type": "expense",
        "from_date": str(last_month_end.replace(day=1)),
        "to_date": str(last_month_end),
    }
    wrong = {k: f.get(k) for k, v in want.items() if f.get(k) != v}
    if not _amount_is(f.get("min_amount"), "100"):
        wrong["min_amount"] = f.get("min_amount")
    return expect(not wrong, f"wrong filter fields {wrong}")


def _check_receipt_reply(path: str) -> Callable[[Run], str | None]:
    def check(r: Run) -> str | None:
        paths = [a.get("object_name") for a in r.called("extract_receipt")]
        if path not in paths:
            return f"didn't call extract_receipt({path}); calls={r.calls}"
        return expect(
            "12.40" not in r.text and "\n" not in r.text.strip(),
            f"reply restates the card instead of one short sentence: {r.text!r}",
        )

    return check


EXPORT_HISTORY = [
    user("Export my transactions"),
    assistant(f"Here's your export. {DOWNLOAD_SENTENCE}", [("call_exp1", "export_transactions", {})]),
    tool("call_exp1", "export_transactions", {}),
]
RECEIPT_HISTORY = [
    user("Here's my receipt\n\n[uploaded receipt: receipts/u1/r1.jpg]"),
    assistant(
        f"Extracted your receipt from {TODAY} — you can edit or confirm it below.",
        [("call_r1", "extract_receipt", {"object_name": "receipts/u1/r1.jpg"})],
    ),
    tool("call_r1", "extract_receipt", fake_result("extract_receipt", {})),
]

CASES = [
    Case("marker_edit", "[transaction: t-taxi] change the amount to 30", _check_marker_edit),
    Case(
        "marker_edit_after_false_not_found",
        "[transaction: t-taxi] change the amount to 30",
        _check_marker_edit,
        history=[
            user("[transaction: t-taxi] change the amount to 30"),
            assistant("I couldn't find a transaction with that id. Could you check it and send it again?"),
        ],
    ),
    Case(
        "marker_delete",
        "[transaction: t-bagel] delete this",
        lambda r: expect(
            any(a.get("transaction_id") == "t-bagel" for a in r.called("delete_transaction")),
            f"no delete_transaction(t-bagel); calls={r.calls}",
        ),
    ),
    Case(
        "delete_last_requeries",
        "Delete the last transaction",
        _check_delete_last,
        working_set={"t-taxi": "taxi to the airport, 25.00 EUR"},
    ),
    Case("vague_reference_searches_table", "Delete the bagel one", _check_bagel),
    Case(
        "bulk_delete_confirms_first",
        "Delete all my transactions",
        lambda r: expect(
            not r.called("delete_transactions_matching") and not r.called("delete_transaction"),
            f"deleted without confirming; calls={r.calls}",
        ),
    ),
    Case(
        "bulk_delete_after_confirmation",
        "Yes, delete them all",
        lambda r: expect(
            len(r.called("delete_transactions_matching")) == 1 and not r.called("delete_transaction"),
            f"expected one delete_transactions_matching; calls={r.calls}",
        ),
        history=[
            user("Delete all my transactions"),
            assistant("That will permanently delete all 4 of your transactions. Are you sure?"),
        ],
    ),
    Case(
        "cross_currency_total",
        "What's my total spending this month in USD?",
        lambda r: expect(
            bool(r.called("get_total_in_currency")) and not r.called("get_exchange_rate"),
            f"didn't use get_total_in_currency alone; calls={r.calls}",
        ),
    ),
    Case(
        "numbers_not_from_summary",
        "How much did I spend on dining?",
        # Querying, or asking which period, are both fine; repeating the summary's
        # (possibly stale) number as fact is the failure.
        lambda r: expect(
            bool(r.called("query_transactions") or r.called("get_total_in_currency")) or "420" not in r.text,
            f"stated the summary's number without querying; text={r.text!r}",
        ),
        summary="User reviewed September dining; they spent 420 USD on dining.",
    ),
    Case(
        "missing_amount_asks",
        "Add a coffee I had today",
        lambda r: expect(
            not r.called("add_transaction") and "?" in r.text,
            f"added without an amount or didn't ask; calls={r.calls} text={r.text!r}",
        ),
    ),
    Case(
        "add_parses_fields",
        "I spent 5 USD on noodles at 7-Eleven today",
        lambda r: expect(
            any(
                _amount_is(a.get("amount"), "5")
                and a.get("currency") == "USD"
                and a.get("type") == "expense"
                and a.get("occurred_on") == str(TODAY)
                and "7-eleven" in (a.get("description") or "").lower()
                for a in r.called("add_transaction")
            ),
            f"add_transaction fields wrong; calls={r.calls}",
        ),
    ),
    Case(
        "exchange_rate_only",
        "What's 50 USD in EUR?",
        lambda r: expect(
            bool(r.called("get_exchange_rate"))
            and not r.called("add_transaction")
            and not r.called("edit_transaction"),
            f"calls={r.calls}",
        ),
    ),
    Case(
        "export_again_calls_tool",
        "Export this again",
        lambda r: expect(
            bool(r.called("export_transactions")) and DOWNLOAD_SENTENCE in r.text,
            f"no export call or wrong closing sentence; calls={r.calls} text={r.text!r}",
        ),
        history=EXPORT_HISTORY,
    ),
    Case(
        "clear_filter",
        "Clear the filter",
        lambda r: expect(
            any(not any(v not in (None, "") for v in a.values()) for a in r.called("set_filter")) and "30" in r.text,
            f"calls={r.calls} text={r.text!r}",
        ),
    ),
    Case("filter_parsing", "Show my USD expenses over 100 from last month", _check_filter),
    Case(
        "receipt_with_text",
        "This one is from yesterday\n\n[uploaded receipt: receipts/u1/r2.jpg]",
        _check_receipt_reply("receipts/u1/r2.jpg"),
    ),
    Case(
        "receipt_again_calls_tool",
        "Here's another one\n\n[uploaded receipt: receipts/u1/r3.jpg]",
        _check_receipt_reply("receipts/u1/r3.jpg"),
        history=RECEIPT_HISTORY,
    ),
    Case(
        "replies_in_user_language",
        "How much did I spend on transport?",
        lambda r: expect(
            bool(re.search(r"\b(transporte|gastaste|has gastado|en)\b", r.text.lower()))
            and not re.search(r"\byou\b", r.text.lower()),
            f"not Spanish: {r.text!r}",
        ),
        language="es",
    ),
]


async def _invoke_with_rate_limit_retry(model, messages) -> AIMessage:
    # Tier limits are low (e.g. 30k tokens/min on gpt-4o) and the SDK's own 2 retries
    # give up quickly; a 429 is the account's limit, not the model's answer.
    for attempt in range(8):
        try:
            return await model.ainvoke(messages)
        except Exception as e:
            if "429" not in str(e) or attempt == 7:
                raise
            await asyncio.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


async def run_case(model_name: str, case: Case) -> Run:
    tools = build_tools("eval-jwt", None, case.language)
    model = llm.build_chat_model(model_name).bind_tools([_compact_tool_schema(t) for t in tools])
    thread = {"working_set": case.working_set, "summary": case.summary}
    messages = build_context(thread, {"language": case.language}, case.history, case.message)
    run = Run(calls=[], text="")
    for _ in range(6):
        ai = await _invoke_with_rate_limit_retry(model, messages)
        usage = ai.usage_metadata or {}
        run.input_tokens += usage.get("input_tokens", 0)
        run.cached_tokens += (usage.get("input_token_details") or {}).get("cache_read", 0) or 0
        run.output_tokens += usage.get("output_tokens", 0)
        messages.append(ai)
        if not ai.tool_calls:
            run.text = ai.content if isinstance(ai.content, str) else str(ai.content)
            return run
        for tc in ai.tool_calls:
            run.calls.append((tc["name"], tc["args"]))
            messages.append(
                ToolMessage(json.dumps(fake_result(tc["name"], tc["args"])), tool_call_id=tc["id"], name=tc["name"])
            )
    return run


def cost(model: str, runs: list[Run]) -> float | None:
    if model not in PRICES:
        return None
    p_in, p_cached, p_out = PRICES[model]
    uncached = sum(r.input_tokens - r.cached_tokens for r in runs)
    cached = sum(r.cached_tokens for r in runs)
    out = sum(r.output_tokens for r in runs)
    return (uncached * p_in + cached * p_cached + out * p_out) / 1_000_000


async def main(models: list[str], runs: int, only: list[str] | None, concurrency: int) -> None:
    cases = [c for c in CASES if not only or c.name in only]
    sem = asyncio.Semaphore(concurrency)

    async def one(model: str, case: Case) -> tuple[str, str, Run | None, str | None]:
        async with sem:
            try:
                run = await run_case(model, case)
            except Exception as e:  # a crashed run is a failed run, not a crashed eval
                return model, case.name, None, f"error: {e}"
            return model, case.name, run, case.check(run)

    jobs = [one(m, c) for m in models for c in cases for _ in range(runs)]
    results = await asyncio.gather(*jobs)

    width = max(len(c.name) for c in cases)
    print(f"\n{'case':<{width}}  " + "  ".join(f"{m:>13}" for m in models))
    for c in cases:
        cells = []
        for m in models:
            rs = [r for r in results if r[0] == m and r[1] == c.name]
            passed = sum(1 for r in rs if r[3] is None)
            cells.append(f"{passed}/{len(rs)}".rjust(13))
        print(f"{c.name:<{width}}  " + "  ".join(cells))

    print()
    for m in models:
        rs = [r for r in results if r[0] == m]
        passed = sum(1 for r in rs if r[3] is None)
        ok_runs = [r[2] for r in rs if r[2] is not None]
        total = cost(m, ok_runs)
        per_turn = f"${total / len(ok_runs):.5f}/turn" if total is not None and ok_runs else "n/a"
        print(
            f"{m}: {passed}/{len(rs)} passed ({100 * passed / len(rs):.0f}%), eval cost "
            f"{'$%.4f' % total if total is not None else 'n/a'}, avg {per_turn}"
        )

    failures = [r for r in results if r[3] is not None]
    if failures:
        print("\nFailures:")
        for m, name, _, reason in failures:
            print(f"- [{m}] {name}: {reason[:300]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["gpt-4o", "gpt-4.1-mini"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", nargs="*", help="case names to run (default: all)")
    parser.add_argument("--concurrency", type=int, default=2, help="parallel runs; keep low on low rate-limit tiers")
    args = parser.parse_args()
    asyncio.run(main(args.models, args.runs, args.only, args.concurrency))
