"""Tools the agent calls (architecture doc, Agent service > Tool table, p. 7). Every
tool forwards the user's JWT to the transactions service — the agent never asserts
"act as uid X" with its own identity. Built per-request via build_tools() so each
closure carries this turn's JWT/X-Client-Id without leaking across requests."""

import os

import httpx
from langchain_core.tools import BaseTool

from . import crud, currency, receipts, utility

TRANSACTIONS_URL = os.environ["TRANSACTIONS_URL"]

__all__ = ["build_tools"]


def build_tools(jwt: str, x_client_id: str | None, language: str = "en") -> list[BaseTool]:
    headers = {"Authorization": f"Bearer {jwt}"}
    if x_client_id:
        headers["X-Client-Id"] = x_client_id

    def http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=TRANSACTIONS_URL, headers=headers, timeout=30)

    return [
        *crud.build_crud_tools(http_client),
        *currency.build_currency_tools(http_client),
        *utility.build_utility_tools(),
        *receipts.build_receipt_tools(http_client, language),
    ]
