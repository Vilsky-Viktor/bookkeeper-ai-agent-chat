import json

import httpx
import pytest

from app import categorize as categorize_module
from app import tools as tools_module
from app.workflows.categorize import build_categorize_graph

_RealAsyncClient = httpx.AsyncClient  # captured before any monkeypatching below


def _tool_by_name(built, name):
    return next(t for t in built if t.name == name)


@pytest.fixture
def build(monkeypatch):
    """Builds the tool set with a given httpx handler mocked in for every
    httpx.AsyncClient constructed anywhere under app/tools/ (build_tools' own
    http_client() closure, plus currency.py's bare client for exchange-rate lookups)
    — patching httpx.AsyncClient here works across every submodule since `import
    httpx` everywhere binds the same cached module object, not a per-file copy."""

    def _build(handler):
        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return _RealAsyncClient(*args, **kwargs)

        monkeypatch.setattr(tools_module.httpx, "AsyncClient", factory)
        http_client = tools_module.transactions_client("test-jwt")
        # The real categorize subgraph, as the main graph wires it (tests stub only
        # the model call inside it — see _stub_categorize).
        return tools_module.build_tools(http_client, build_categorize_graph(http_client))

    return _build


def _stub_categorize(monkeypatch, categories: dict[str, str]) -> list:
    """Replaces the model-backed categorizer; returns the recorded (descriptions,
    corrections) calls."""
    calls: list = []

    async def fake(descriptions, corrections):
        calls.append((descriptions, corrections))
        return [categories.get(d, "other") for d in descriptions]

    monkeypatch.setattr(categorize_module, "categorize", fake)
    return calls


class TestAddTransaction:
    async def test_categorizes_then_creates_with_the_category(self, build, monkeypatch):
        calls = _stub_categorize(monkeypatch, {"coffee": "dining"})
        created = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer test-jwt"
            if request.url.path == "/api/transactions/corrections":
                return httpx.Response(200, json={"items": [{"item_key": "tea", "category": "dining"}]})
            created.append(json.loads(request.content)["transactions"][0])
            return httpx.Response(201, json={"items": [{"id": "txn-1", "amount": "12.50"}]})

        add_transaction = _tool_by_name(build(handler), "add_transaction")
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
        calls = _stub_categorize(monkeypatch, {})
        created = []

        def handler(request: httpx.Request) -> httpx.Response:
            created.append(json.loads(request.content)["transactions"][0])
            return httpx.Response(201, json={"items": [{"id": "txn-1"}]})

        add_transaction = _tool_by_name(build(handler), "add_transaction")
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
        _stub_categorize(monkeypatch, {})

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "boom"})

        add_transaction = _tool_by_name(build(handler), "add_transaction")
        with pytest.raises(httpx.HTTPStatusError):
            await add_transaction.coroutine(
                occurred_on="2026-01-01", type="expense", amount="12.50", currency="USD", tool_call_id="call-1"
            )


class TestEditTransaction:
    async def test_success(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": "txn-1", "category": "groceries"})

        edit_transaction = _tool_by_name(build(handler), "edit_transaction")
        result = await edit_transaction.coroutine(transaction_id="txn-1", tool_call_id="call-1", category="groceries")
        assert result == {"ui_event": "table_changed", "id": "txn-1", "category": "groceries"}

    async def test_not_found_returns_error_dict_not_exception(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "not found"})

        edit_transaction = _tool_by_name(build(handler), "edit_transaction")
        result = await edit_transaction.coroutine(transaction_id="missing", tool_call_id="call-1", category="x")
        assert result == {"error": "transaction not found"}


class TestDeleteTransaction:
    async def test_success(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"deleted": "txn-1"})

        delete_transaction = _tool_by_name(build(handler), "delete_transaction")
        result = await delete_transaction.coroutine(transaction_id="txn-1", tool_call_id="call-1")
        assert result == {"ui_event": "table_changed", "deleted": "txn-1"}

    async def test_not_found_returns_error_dict(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "not found"})

        delete_transaction = _tool_by_name(build(handler), "delete_transaction")
        result = await delete_transaction.coroutine(transaction_id="missing", tool_call_id="call-1")
        assert result == {"error": "transaction not found"}


class TestDeleteTransactionsMatching:
    async def test_success_passes_filters_as_query_params(self, build):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"deleted_count": 3})

        tool = _tool_by_name(build(handler), "delete_transactions_matching")
        result = await tool.coroutine(tool_call_id="call-1", currency="USD", category="dining")

        assert result == {"ui_event": "table_changed", "deleted_count": 3}
        assert captured["params"] == {"currency": "USD", "category": "dining"}

    async def test_server_error_raises(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        tool = _tool_by_name(build(handler), "delete_transactions_matching")
        with pytest.raises(httpx.HTTPStatusError):
            await tool.coroutine(tool_call_id="call-1")


class TestQueryTransactions:
    async def test_list_mode_hits_transactions_endpoint(self, build):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json={"items": [], "next_cursor": None})

        tool = _tool_by_name(build(handler), "query_transactions")
        result = await tool.coroutine(description="bagel")

        assert captured["path"] == "/api/transactions/transactions"
        assert result == {"items": [], "next_cursor": None}

    async def test_aggregate_mode_hits_aggregates_endpoint(self, build):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json={"items": []})

        tool = _tool_by_name(build(handler), "query_transactions")
        await tool.coroutine(aggregate=True)

        assert captured["path"] == "/api/transactions/aggregates"

    async def test_error_response_raises(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        tool = _tool_by_name(build(handler), "query_transactions")
        with pytest.raises(httpx.HTTPStatusError):
            await tool.coroutine()


class TestGetExchangeRate:
    async def test_success_from_primary_source(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "usd.json" in str(request.url)
            return httpx.Response(200, json={"date": "2026-01-01", "usd": {"eur": 0.9}})

        tool = _tool_by_name(build(handler), "get_exchange_rate")
        result = await tool.coroutine(from_currency="usd", to_currency="eur")

        assert result == {
            "from": "USD",
            "to": "EUR",
            "rate": 0.9,
            "date": "2026-01-01",
            "note": "Daily reference rate, not real-time.",
        }

    async def test_falls_back_to_second_source_when_first_fails(self, build):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if "cdn.jsdelivr.net" in str(request.url):
                raise httpx.ConnectError("unreachable", request=request)
            return httpx.Response(200, json={"date": "2026-01-01", "usd": {"idr": 15800}})

        tool = _tool_by_name(build(handler), "get_exchange_rate")
        result = await tool.coroutine(from_currency="usd", to_currency="idr")

        assert result["rate"] == 15800
        assert len(calls) == 2

    async def test_both_sources_unreachable_returns_error_dict(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unreachable", request=request)

        tool = _tool_by_name(build(handler), "get_exchange_rate")
        result = await tool.coroutine(from_currency="usd", to_currency="eur")

        assert "error" in result
        assert "transient" in result["error"]

    async def test_unrecognized_currency_returns_error_dict(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"date": "2026-01-01", "usd": {"eur": 0.9}})

        tool = _tool_by_name(build(handler), "get_exchange_rate")
        result = await tool.coroutine(from_currency="usd", to_currency="zzz")

        assert "error" in result
        assert "doesn't recognize" not in result["error"]  # sanity: message still specific, not this exact wording
        assert "ZZZ" in result["error"]


class TestGetTotalInCurrency:
    # Regression: the agent used to do this arithmetic itself in prose — call
    # query_transactions(aggregate=true), call get_exchange_rate per currency, then
    # multiply/sum by hand in its reply. That's not guaranteed to be exact for money.
    # This tool exists so the multiply-and-sum happens in real code instead.
    async def test_single_currency_matching_target_needs_no_rate_lookup(self, build):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"currency": "USD", "category": "dining", "month": "2026-01", "total": "12.50", "count": 1}
                    ]
                },
            )

        tool = _tool_by_name(build(handler), "get_total_in_currency")
        result = await tool.coroutine(to_currency="usd")

        assert result == {
            "total": "12.50",
            "currency": "USD",
            "breakdown": [{"currency": "USD", "amount": "12.50", "converted": "12.50"}],
            "note": "Daily reference rate, not real-time.",
        }
        assert len(calls) == 1  # only the aggregates call, no rate lookup needed

    async def test_multiple_currencies_converted_and_summed(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/transactions/aggregates":
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "currency": "IDR",
                                "category": "dining",
                                "month": "2026-01",
                                "total": "100000",
                                "count": 1,
                            },
                            {
                                "currency": "IDR",
                                "category": "groceries",
                                "month": "2026-01",
                                "total": "50000",
                                "count": 1,
                            },
                            {
                                "currency": "UAH",
                                "category": "utilities",
                                "month": "2026-01",
                                "total": "600.00",
                                "count": 1,
                            },
                        ]
                    },
                )
            if "idr.json" in str(request.url):
                return httpx.Response(200, json={"date": "2026-01-01", "idr": {"usd": 0.00006}})
            if "uah.json" in str(request.url):
                return httpx.Response(200, json={"date": "2026-01-01", "uah": {"usd": 0.024}})
            raise AssertionError(f"unexpected request: {request.url}")

        tool = _tool_by_name(build(handler), "get_total_in_currency")
        result = await tool.coroutine(to_currency="usd")

        # 150000 IDR * 0.00006 = 9.0; 600 UAH * 0.024 = 14.4; total = 23.4
        assert result["currency"] == "USD"
        assert result["total"] == "23.40"
        assert len(result["breakdown"]) == 2

    async def test_no_transactions_returns_zero(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": []})

        tool = _tool_by_name(build(handler), "get_total_in_currency")
        result = await tool.coroutine(to_currency="usd")

        assert result == {"total": "0.00", "currency": "USD", "breakdown": []}

    async def test_rate_lookup_failure_propagates_error(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/transactions/aggregates":
                return httpx.Response(
                    200,
                    json={
                        "items": [{"currency": "IDR", "category": "x", "month": "2026-01", "total": "1000", "count": 1}]
                    },
                )
            raise httpx.ConnectError("unreachable", request=request)

        tool = _tool_by_name(build(handler), "get_total_in_currency")
        result = await tool.coroutine(to_currency="usd")

        assert "error" in result

    async def test_filters_passed_through_to_aggregates_request(self, build):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"items": []})

        tool = _tool_by_name(build(handler), "get_total_in_currency")
        await tool.coroutine(
            to_currency="usd", type="expense", from_date="2026-01-01", to_date="2026-01-31", category="dining"
        )

        assert captured["params"] == {
            "type": "expense",
            "from": "2026-01-01",
            "to": "2026-01-31",
            "category": "dining",
        }


class TestSetFilter:
    def test_returns_filter_set_event_with_provided_fields(self, build):
        tool = _tool_by_name(build(lambda r: httpx.Response(200)), "set_filter")
        result = tool.func(currency="USD", min_amount="10")
        assert result == {"ui_event": "filter_set", "filter": {"currency": "USD", "min_amount": "10"}}

    def test_no_arguments_clears_filter(self, build):
        tool = _tool_by_name(build(lambda r: httpx.Response(200)), "set_filter")
        result = tool.func()
        assert result == {"ui_event": "filter_set", "filter": {}}


class TestExportTransactions:
    def test_returns_export_ready_event(self, build):
        tool = _tool_by_name(build(lambda r: httpx.Response(200)), "export_transactions")
        assert tool.func() == {"ui_event": "export_ready"}
