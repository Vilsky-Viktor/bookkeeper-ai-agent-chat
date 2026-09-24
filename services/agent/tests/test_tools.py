import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app import tools as tools_module

_RealAsyncClient = httpx.AsyncClient  # captured before any monkeypatching below


def _tool_by_name(built, name):
    return next(t for t in built if t.name == name)


@pytest.fixture
def build(monkeypatch):
    """Builds the tool set with a given httpx handler mocked in for every
    httpx.AsyncClient constructed inside tools.py (both build_tools' http_client()
    closure and get_exchange_rate's own bare client)."""

    def _build(handler, language="en"):
        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return _RealAsyncClient(*args, **kwargs)

        monkeypatch.setattr(tools_module.httpx, "AsyncClient", factory)
        return tools_module.build_tools("test-jwt", "client-1", language)

    return _build


class TestAddTransaction:
    async def test_success_returns_created_item_with_ui_event(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer test-jwt"
            body = json.loads(request.content)
            assert body["transactions"][0]["amount"] == "12.50"
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

    async def test_server_error_raises(self, build):
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


class TestExtractReceipt:
    async def test_unsupported_content_type_returns_error(self, build, monkeypatch):
        monkeypatch.setattr(tools_module.storage, "read_bytes", lambda name: (b"data", "text/plain"))
        tool = _tool_by_name(build(lambda r: httpx.Response(200)), "extract_receipt")

        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert "error" in result
        assert "text/plain" in result["error"]

    async def test_not_a_receipt_returns_message_without_writing(self, build, monkeypatch):
        monkeypatch.setattr(tools_module.storage, "read_bytes", lambda name: (b"imgdata", "image/jpeg"))
        monkeypatch.setattr(tools_module, "_extract_line_items", AsyncMock(return_value={"is_receipt": False}))

        tool = _tool_by_name(build(lambda r: httpx.Response(200)), "extract_receipt")
        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert result["not_a_receipt"] is True

    async def test_success_folds_merchant_and_categorizes_each_item(self, build, monkeypatch):
        monkeypatch.setattr(tools_module.storage, "read_bytes", lambda name: (b"imgdata", "image/jpeg"))
        monkeypatch.setattr(
            tools_module,
            "_extract_line_items",
            AsyncMock(
                return_value={
                    "is_receipt": True,
                    "merchant": "Alfamart",
                    "occurred_on": "2026-01-01",
                    "currency": "idr",
                    "items": [{"description": "Rice 1kg", "amount": "10000"}],
                }
            ),
        )

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/transactions/categorize"
            return httpx.Response(200, json={"category": "groceries"})

        tool = _tool_by_name(build(handler), "extract_receipt")
        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert result["ui_event"] == "receipt_proposed"
        item = result["items"][0]
        assert item["category"] == "groceries"
        assert item["currency"] == "IDR"
        assert "Alfamart" in item["description"]

    async def test_categorize_call_failure_defaults_to_other(self, build, monkeypatch):
        monkeypatch.setattr(tools_module.storage, "read_bytes", lambda name: (b"imgdata", "image/jpeg"))
        monkeypatch.setattr(
            tools_module,
            "_extract_line_items",
            AsyncMock(
                return_value={
                    "is_receipt": True,
                    "merchant": None,
                    "occurred_on": "2026-01-01",
                    "currency": "usd",
                    "items": [{"description": "widget", "amount": "5.00"}],
                }
            ),
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        tool = _tool_by_name(build(handler), "extract_receipt")
        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert result["items"][0]["category"] == "other"


class TestExtractLineItems:
    async def test_prompt_includes_todays_date_with_no_placeholder_left_over(self, monkeypatch):
        # A misread receipt date (e.g. wrong year) is a real failure mode for the
        # vision model — giving it today's date as an anchor is the mitigation. This
        # guards the substitution itself: no literal "{today}"/"{language}" leftover,
        # and the date that lands in the prompt is the real one, not hardcoded.
        captured = {}

        class _FakeVisionModel:
            async def ainvoke(self, messages):
                captured["prompt"] = messages[0].content[0]["text"]
                return MagicMock(content='{"is_receipt": false}')

        monkeypatch.setattr(tools_module.llm, "vision_model", lambda: _FakeVisionModel())

        await tools_module._extract_line_items(b"imgdata", "image/jpeg", "en")

        today = tools_module.datetime.date.today().isoformat()
        assert today in captured["prompt"]
        assert "{today}" not in captured["prompt"]
        assert "{language}" not in captured["prompt"]
        # Guards the specific failure mode that prompted this: a receipt printing a
        # relative label ("Today, 5:52 PM") instead of a calendar date, which the
        # model has no way to resolve without being told what "today" actually is.
        assert "Today" in captured["prompt"] and "Yesterday" in captured["prompt"]
        # Guards a second, separate failure mode: a receipt (e.g. an app/delivery
        # order) that lists item names and quantities but no per-item price — the
        # model must not invent a per-item amount (observed: it used the quantity
        # number, e.g. "3", as if it were a price) and must fall back to the
        # receipt's real total instead.
        assert "never use a quantity number as if it were a price" in captured["prompt"]
        assert "collapse everything into ONE item" in captured["prompt"]
        # Guards a third failure mode: a receipt with a real per-item price plus extra
        # charges on top (delivery/packaging/service fee) that raise the actual total
        # paid — observed: the model reported only the product subtotal and silently
        # dropped the fees, understating what was actually spent.
        assert "sum of every item" in captured["prompt"]
        assert "Delivery & packaging" in captured["prompt"]
        # A fee must get its own line item even with only one product — folding it
        # into that product's amount was tried and rejected (it corrupts both the
        # amount and the category attributed to the actual purchase).
        assert "not even when there's only one product" in captured["prompt"]
        # Guards the same pattern in its restaurant-bill form: many dishes plus a
        # shared service charge/tip/tax, sometimes printed only as a percentage with
        # no computed amount of its own — the model must compute it, and must not
        # split or fold it into the individual dishes.
        assert "restaurant bill with many" in captured["prompt"]
        assert "calculate the actual amount yourself" in captured["prompt"]
        # Guards a fourth failure mode: an unreadable merchant name written as the
        # placeholder "Unknown" instead of null, which then folds into the
        # description as if it were a real merchant.
        assert 'set "merchant" to null' in captured["prompt"]


class TestFoldMerchant:
    def test_merchant_appended_when_not_already_in_description(self):
        assert tools_module._fold_merchant("rice", "Alfamart") == "rice - Alfamart"

    def test_merchant_omitted_when_already_present(self):
        assert tools_module._fold_merchant("rice from Alfamart", "Alfamart") == "rice from Alfamart"

    def test_no_merchant_returns_description_unchanged(self):
        assert tools_module._fold_merchant("rice", None) == "rice"

    def test_no_description_returns_merchant(self):
        assert tools_module._fold_merchant(None, "Alfamart") == "Alfamart"

    def test_neither_returns_none(self):
        assert tools_module._fold_merchant(None, None) is None

    def test_literal_unknown_merchant_is_treated_as_no_merchant(self):
        # Observed: the model wrote "Unknown" as the merchant when it genuinely
        # couldn't read one, which folded in as "3x Camel White 20 - Unknown" — a
        # placeholder that looks like a real (wrong) merchant name.
        assert tools_module._fold_merchant("3x Camel White 20", "Unknown") == "3x Camel White 20"

    def test_placeholder_merchant_case_insensitive(self):
        assert tools_module._fold_merchant("rice", "UNKNOWN") == "rice"
        assert tools_module._fold_merchant("rice", "N/A") == "rice"

    def test_unknown_merchant_with_no_description_returns_none(self):
        assert tools_module._fold_merchant(None, "Unknown") is None
