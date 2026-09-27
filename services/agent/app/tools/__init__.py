"""The bookkeeping assistant's tools. Every tool forwards the user's JWT to the
transactions service — the agent never asserts "act as uid X" with its own identity.
Built per request, so each closure carries this turn's JWT without leaking across
requests."""

import os
from typing import Callable

import httpx
from langchain_core.tools import BaseTool

from . import crud, currency, utility

TRANSACTIONS_URL = os.environ["TRANSACTIONS_URL"]

__all__ = ["MUTATING_TOOLS", "build_tools", "transactions_client"]

# Tools that change the user's data — left out wherever an agent should only look.
MUTATING_TOOLS = {"add_transaction", "edit_transaction", "delete_transaction", "delete_transactions_matching"}


def transactions_client(jwt: str) -> Callable[[], httpx.AsyncClient]:
    """A factory for clients to the transactions service, authenticated as the user."""
    headers = {"Authorization": f"Bearer {jwt}"}
    return lambda: httpx.AsyncClient(base_url=TRANSACTIONS_URL, headers=headers, timeout=30)


def build_tools(http_client: Callable[[], httpx.AsyncClient], categorize_graph) -> list[BaseTool]:
    return [
        *crud.build_crud_tools(http_client, categorize_graph),
        *currency.build_currency_tools(http_client),
        *utility.build_utility_tools(),
    ]
