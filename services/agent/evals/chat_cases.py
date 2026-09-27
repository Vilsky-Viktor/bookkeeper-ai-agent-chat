"""The chat eval's cases and their checks."""

import datetime
import json
import re
from decimal import Decimal, InvalidOperation

from langchain_core.messages import AIMessage, ToolMessage

from app.tools import MUTATING_TOOLS

from .chat_fixtures import DOWNLOAD_SENTENCE, TODAY, assistant, fake_result, tool, user
from .chat_models import Case, Run


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


def _check_receipt_note_reply(r: Run) -> str | None:
    # The receipt workflow already read the receipt; the assistant must not restate
    # it (the card shows it), and must still answer the question asked with it.
    mutations = [n for n, _ in r.calls if n in MUTATING_TOOLS]

    if mutations:
        return f"changed data instead of leaving the receipt to its card: {mutations}"

    if "12.40" in r.text:
        return f"reply restates the card: {r.text!r}"

    return expect(
        bool(r.called("query_transactions") or r.called("get_total_in_currency")),
        f"didn't answer the question asked with the upload; calls={r.calls}",
    )


EXPORT_HISTORY = [
    user("Export my transactions"),
    assistant(f"Here's your export. {DOWNLOAD_SENTENCE}", (("call_exp1", "export_transactions", {}),)),
    tool("call_exp1", "export_transactions", {}),
]
RECEIPT_WORKFLOW_RESULT = [
    AIMessage(
        content="",
        tool_calls=[{"id": "call_r2", "name": "extract_receipt", "args": {"object_name": "receipts/u1/r2.jpg"}}],
    ),
    ToolMessage(
        content=json.dumps({k: v for k, v in fake_result("extract_receipt", {}).items() if k != "ui_event"}),
        tool_call_id="call_r2",
        name="extract_receipt",
    ),
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
        "receipt_note_reply",
        "This one is from yesterday. Also, how much did I spend on dining?\n\n[uploaded receipt: receipts/u1/r2.jpg]",
        _check_receipt_note_reply,
        workflow_messages=RECEIPT_WORKFLOW_RESULT,
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
