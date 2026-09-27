"""CRUD tools: add, edit, delete, delete-matching and query."""

import json

import httpx
import pytest
from tool_helpers import stub_categorize, tool_by_name


class TestAddTransaction:
    async def test_categorizes_then_creates_with_the_category(self, build, monkeypatch):
        calls = stub_categorize(monkeypatch, {"coffee": "dining"})
        created = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer test-jwt"

            if request.url.path == "/api/transactions/corrections":
                return httpx.Response(200, json={"items": [{"item_key": "tea", "category": "dining"}]})
            created.append(json.loads(request.content)["transactions"][0])

            return httpx.Response(201, json={"items": [{"id": "txn-1", "amount": "12.50"}]})

        add_transaction = tool_by_name(build(handler), "add_transaction")
        result = await add_transaction.coroutine(
            occurred_on="2026-01-01",
            type="expense",
            amount="12.50",
            currency="USD",
            tool_call_id="call-1",
            description="coffee",
        )

        assert result == {"ui_event": "table_changed", "id": "txn-1", "amount": "12.50"}
        assert created[0]["category"] == "dining" and created[0]["amount"] == "12.50"
        assert [c.item_key for c in calls[0][1]] == ["tea"]  # the user's corrections were used

    async def test_income_is_not_categorized(self, build, monkeypatch):
        calls = stub_categorize(monkeypatch, {})
        created = []

        def handler(request: httpx.Request) -> httpx.Response:
            created.append(json.loads(request.content)["transactions"][0])

            return httpx.Response(201, json={"items": [{"id": "txn-1"}]})

        add_transaction = tool_by_name(build(handler), "add_transaction")
        await add_transaction.coroutine(
            occurred_on="2026-01-01",
            type="income",
            amount="100",
            currency="USD",
            tool_call_id="c",
            description="salary",
        )

        assert created[0]["category"] == "income"
        assert calls == []

    async def test_server_error_raises(self, build, monkeypatch):
        stub_categorize(monkeypatch, {})

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "boom"})

        add_transaction = tool_by_name(build(handler), "add_transaction")

        with pytest.raises(httpx.HTTPStatusError):
            await add_transaction.coroutine(
                occurred_on="2026-01-01", type="expense", amount="12.50", currency="USD", tool_call_id="call-1"
            )


class TestEditTransaction:
    async def test_success(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": "txn-1", "category": "groceries"})

        edit_transaction = tool_by_name(build(handler), "edit_transaction")
        result = await edit_transaction.coroutine(transaction_id="txn-1", tool_call_id="call-1", category="groceries")
        assert result == {"ui_event": "table_changed", "id": "txn-1", "category": "groceries"}

    async def test_not_found_returns_error_dict_not_exception(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "not found"})

        edit_transaction = tool_by_name(build(handler), "edit_transaction")
        result = await edit_transaction.coroutine(transaction_id="missing", tool_call_id="call-1", category="x")
        assert result == {"error": "transaction not found"}


class TestDeleteTransaction:
    async def test_success(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"deleted": "txn-1"})

        delete_transaction = tool_by_name(build(handler), "delete_transaction")
        result = await delete_transaction.coroutine(transaction_id="txn-1", tool_call_id="call-1")
        assert result == {"ui_event": "table_changed", "deleted": "txn-1"}

    async def test_not_found_returns_error_dict(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "not found"})

        delete_transaction = tool_by_name(build(handler), "delete_transaction")
        result = await delete_transaction.coroutine(transaction_id="missing", tool_call_id="call-1")
        assert result == {"error": "transaction not found"}


class TestDeleteTransactionsMatching:
    async def test_success_passes_filters_as_query_params(self, build):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)

            return httpx.Response(200, json={"deleted_count": 3})

        tool = tool_by_name(build(handler), "delete_transactions_matching")
        result = await tool.coroutine(tool_call_id="call-1", currency="USD", category="dining")

        assert result == {"ui_event": "table_changed", "deleted_count": 3}
        assert captured["params"] == {"currency": "USD", "category": "dining"}

    async def test_server_error_raises(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        tool = tool_by_name(build(handler), "delete_transactions_matching")

        with pytest.raises(httpx.HTTPStatusError):
            await tool.coroutine(tool_call_id="call-1")


class TestQueryTransactions:
    async def test_list_mode_hits_transactions_endpoint(self, build):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path

            return httpx.Response(200, json={"items": [], "next_cursor": None})

        tool = tool_by_name(build(handler), "query_transactions")
        result = await tool.coroutine(description="bagel")

        assert captured["path"] == "/api/transactions/transactions"
        assert result == {"items": [], "next_cursor": None}

    async def test_aggregate_mode_hits_aggregates_endpoint(self, build):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path

            return httpx.Response(200, json={"items": []})

        tool = tool_by_name(build(handler), "query_transactions")
        await tool.coroutine(aggregate=True)

        assert captured["path"] == "/api/transactions/aggregates"

    async def test_error_response_raises(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        tool = tool_by_name(build(handler), "query_transactions")

        with pytest.raises(httpx.HTTPStatusError):
            await tool.coroutine()
