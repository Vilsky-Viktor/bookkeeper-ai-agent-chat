"""add/edit/delete/query transaction tools — the agent's core CRUD surface against the
transactions service."""

from typing import Annotated, Callable, Optional

import httpx
from langchain_core.tools import BaseTool, InjectedToolCallId, tool


def build_crud_tools(http_client: Callable[[], httpx.AsyncClient]) -> list[BaseTool]:
    @tool
    async def add_transaction(
        occurred_on: str,
        type: str,
        amount: str,
        currency: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        description: Optional[str] = None,
    ) -> dict:
        """Add one transaction (expense or income). occurred_on is YYYY-MM-DD, amount
        is a decimal string like '12.50', currency is a 3-letter ISO 4217 code, type is
        'expense' or 'income'. Ask a clarifying question first if amount or currency is
        missing from the user's request. There is no category argument: the
        transactions service categorizes every row itself (past corrections first,
        then its own model), so pass description and let it decide.
        description should be a short, complete, human-readable phrase covering what it
        was for, including the merchant/vendor/service name whenever one is
        identifiable — not just the bare item name. E.g. for "I spent 5000 IDR for
        indomie in Indomart", set description to "indomie purchased in Indomart", not
        just "indomie"; for a subscription with no physical store, still name it, e.g.
        "Claude subscription payment". Corrections are matched against this exact text
        (loosely, via near-duplicate matching), so use the SAME short, consistent
        wording for the same recurring purchase every time (e.g. always "Claude
        subscription payment", never alternating with "Anthropic Claude payment") —
        inconsistent wording across separate adds makes past corrections less likely
        to reapply."""
        async with http_client() as c:
            resp = await c.post(
                "/api/transactions/transactions",
                json={
                    "transactions": [
                        {
                            "occurred_on": occurred_on,
                            "type": type,
                            "amount": amount,
                            "currency": currency,
                            "description": description,
                        }
                    ]
                },
                headers={"Idempotency-Key": tool_call_id},
            )
        resp.raise_for_status()
        return {"ui_event": "table_changed", **resp.json()["items"][0]}

    @tool
    async def edit_transaction(
        transaction_id: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        occurred_on: Optional[str] = None,
        type: Optional[str] = None,
        amount: Optional[str] = None,
        currency: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Edit fields on an existing transaction, identified by transaction_id.
        Resolve "that one" / "the coffee one" from recently referenced transactions or
        a prior query_transactions call — or from a "[transaction: <id>]" marker in the
        message, which takes priority when present. If the reference isn't something
        you've already seen this conversation, call query_transactions with
        description set to a distinctive word from what the user said (e.g. "bagel")
        to search the whole table before asking the user which one they mean. Only
        pass fields that change. If you set
        description, keep it a complete, human-readable phrase with context including
        the merchant/vendor name when relevant (e.g. "indomie purchased in Indomart"),
        not just an item name."""
        body = {
            k: v
            for k, v in {
                "occurred_on": occurred_on,
                "type": type,
                "amount": amount,
                "currency": currency,
                "category": category,
                "description": description,
            }.items()
            if v is not None
        }
        async with http_client() as c:
            resp = await c.patch(
                f"/api/transactions/transactions/{transaction_id}",
                json=body,
                headers={"Idempotency-Key": tool_call_id},
            )
        if resp.status_code == 404:
            return {"error": "transaction not found"}
        resp.raise_for_status()
        return {"ui_event": "table_changed", **resp.json()}

    @tool
    async def delete_transaction(transaction_id: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> dict:
        """Delete ONE transaction by id. For deleting more than one — "delete all",
        "clear the table", "remove my Starbucks purchases" — use
        delete_transactions_matching instead; it deletes in a single server-side
        operation instead of one id at a time. query_transactions only ever returns
        one page of results (up to 50), so looping delete_transaction over its output
        silently misses everything past the first page. "The last transaction"/"most
        recent" means current table state — resolve it with a fresh query_transactions
        call (newest-first) right before this, don't reuse an id from earlier in the
        conversation. If this returns an error, that transaction was NOT deleted — say
        so, don't report success anyway."""
        async with http_client() as c:
            resp = await c.delete(
                f"/api/transactions/transactions/{transaction_id}",
                headers={"Idempotency-Key": tool_call_id},
            )
        if resp.status_code == 404:
            return {"error": "transaction not found"}
        resp.raise_for_status()
        return {"ui_event": "table_changed", **resp.json()}

    @tool
    async def delete_transactions_matching(
        tool_call_id: Annotated[str, InjectedToolCallId],
        currency: Optional[str] = None,
        category: Optional[str] = None,
        type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_amount: Optional[str] = None,
        max_amount: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Delete every transaction matching these filters (same filters as
        query_transactions) in one operation — pass no filters to delete ALL of the
        user's transactions. This is irreversible: always confirm with the user
        exactly what will be deleted (and roughly how many, via query_transactions if
        unsure) before calling this. This is the right tool for "delete all my
        transactions", "clear the table", or deleting more than one transaction at
        once — never loop delete_transaction over query_transactions results, since
        that only sees one page and would leave the rest behind."""
        params = {
            k: v
            for k, v in {
                "currency": currency,
                "category": category,
                "type": type,
                "from": from_date,
                "to": to_date,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "description": description,
            }.items()
            if v is not None
        }
        async with http_client() as c:
            resp = await c.delete(
                "/api/transactions/transactions",
                params=params,
                headers={"Idempotency-Key": tool_call_id},
            )
        resp.raise_for_status()
        return {"ui_event": "table_changed", **resp.json()}

    @tool
    async def query_transactions(
        currency: Optional[str] = None,
        category: Optional[str] = None,
        type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_amount: Optional[str] = None,
        max_amount: Optional[str] = None,
        description: Optional[str] = None,
        aggregate: bool = False,
    ) -> dict:
        """List transactions matching filters, or (aggregate=true) sums by category and
        month per currency. Use aggregate=true for analysis or savings questions — never
        state a total from memory or from the conversation summary, always call this.
        description is a case-insensitive substring match against the transaction's
        description — use it to resolve a vague reference ("the bagel one", "that
        Starbucks purchase") against the whole table, not just transactions already
        mentioned earlier in this conversation; try a short, distinctive word from
        what the user said (e.g. "bagel"), not the full phrase."""
        params = {
            k: v
            for k, v in {
                "currency": currency,
                "category": category,
                "type": type,
                "from": from_date,
                "to": to_date,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "description": description,
            }.items()
            if v is not None
        }
        path = "/api/transactions/aggregates" if aggregate else "/api/transactions/transactions"
        async with http_client() as c:
            resp = await c.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    return [add_transaction, edit_transaction, delete_transaction, delete_transactions_matching, query_transactions]
