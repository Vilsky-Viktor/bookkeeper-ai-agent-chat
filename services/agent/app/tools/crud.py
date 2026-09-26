"""add/edit/delete/query transaction tools — the agent's core CRUD surface against the
transactions service."""

from typing import Annotated, Callable, Optional

import httpx
from langchain_core.tools import BaseTool, InjectedToolCallId, tool

from ..models.tool_results import TableChangedResult, ToolError
from .filters import filter_params


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
        """Add one transaction. occurred_on is YYYY-MM-DD, amount a decimal string
        like '12.50', currency a 3-letter ISO 4217 code, type 'expense' or 'income'.
        There's no category argument: the transactions service categorizes each row
        itself. description is a short, human-readable phrase naming what it was for,
        plus the merchant/service when identifiable (e.g. "noodles purchased at
        7-Eleven", "Claude subscription payment"), not just the bare item. Past
        category corrections match on this text, so reuse the same wording for the
        same recurring purchase every time."""
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
        return TableChangedResult(**resp.json()["items"][0]).model_dump()

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
        """Edit an existing transaction by transaction_id; pass only the fields that
        change. Take the id from a "[transaction: <id>]" marker (it takes priority),
        from recently referenced transactions, or from a prior query_transactions
        result; if none match, search with query_transactions(description=<a
        distinctive word>) before asking the user. A new description follows
        add_transaction's style."""
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
            return ToolError(error="transaction not found").model_dump()
        resp.raise_for_status()
        return TableChangedResult(**resp.json()).model_dump()

    @tool
    async def delete_transaction(transaction_id: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> dict:
        """Delete ONE transaction by id; for more than one, use
        delete_transactions_matching. If this returns an error, the transaction was NOT
        deleted."""
        async with http_client() as c:
            resp = await c.delete(
                f"/api/transactions/transactions/{transaction_id}",
                headers={"Idempotency-Key": tool_call_id},
            )
        if resp.status_code == 404:
            return ToolError(error="transaction not found").model_dump()
        resp.raise_for_status()
        return TableChangedResult(**resp.json()).model_dump()

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
        """Delete every transaction matching these filters (same as
        query_transactions) in one irreversible operation; no filters deletes ALL of
        the user's transactions. Confirm with the user what will be deleted first."""
        params = filter_params(
            currency=currency,
            category=category,
            type=type,
            from_date=from_date,
            to_date=to_date,
            min_amount=min_amount,
            max_amount=max_amount,
            description=description,
        )
        async with http_client() as c:
            resp = await c.delete(
                "/api/transactions/transactions",
                params=params,
                headers={"Idempotency-Key": tool_call_id},
            )
        resp.raise_for_status()
        return TableChangedResult(**resp.json()).model_dump()

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
        """List transactions matching the filters (newest first, one page of up to
        50), or with aggregate=true, sums by category and month per currency.
        description is a case-insensitive substring match: to find a vaguely
        referenced transaction ("the bagel one"), pass one short distinctive word, not
        the full phrase."""
        params = filter_params(
            currency=currency,
            category=category,
            type=type,
            from_date=from_date,
            to_date=to_date,
            min_amount=min_amount,
            max_amount=max_amount,
            description=description,
        )
        path = "/api/transactions/aggregates" if aggregate else "/api/transactions/transactions"
        async with http_client() as c:
            resp = await c.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    return [add_transaction, edit_transaction, delete_transaction, delete_transactions_matching, query_transactions]
