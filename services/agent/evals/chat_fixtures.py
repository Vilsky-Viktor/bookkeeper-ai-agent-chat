"""The chat eval's fake data: the user's transactions, canned tool results and
history rows in chat_db's shape."""

import datetime

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


def assistant(text: str, calls: tuple[tuple[str, str, dict], ...] = ()) -> dict:
    return {
        "role": "assistant",
        "compact": None,
        "content": {"text": text, "tool_calls": [{"id": i, "name": n, "args": a} for i, n, a in calls]},
    }


def tool(call_id: str, name: str, result: dict) -> dict:
    return {"role": "tool", "compact": None, "content": {"tool_call_id": call_id, "name": name, "result": result}}
