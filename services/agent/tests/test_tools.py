import io
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from PIL import Image

from app import tools as tools_module
from app.models.tool_results import ReceiptExtraction
from app.tools import receipts as receipts_module

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


class TestExtractReceipt:
    async def test_unsupported_content_type_returns_error(self, build, monkeypatch):
        monkeypatch.setattr(receipts_module.storage, "read_bytes", lambda name: (b"data", "text/plain"))
        tool = _tool_by_name(build(lambda r: httpx.Response(200)), "extract_receipt")

        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert "error" in result
        assert "text/plain" in result["error"]

    async def test_not_a_receipt_returns_message_without_writing(self, build, monkeypatch):
        monkeypatch.setattr(receipts_module.storage, "read_bytes", lambda name: (b"imgdata", "image/jpeg"))
        monkeypatch.setattr(
            receipts_module, "_read_receipt", AsyncMock(return_value=ReceiptExtraction(is_receipt=False))
        )

        tool = _tool_by_name(build(lambda r: httpx.Response(200)), "extract_receipt")
        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert result["not_a_receipt"] is True

    async def test_receipt_without_a_total_is_treated_as_not_a_receipt(self, build, monkeypatch):
        monkeypatch.setattr(receipts_module.storage, "read_bytes", lambda name: (b"imgdata", "image/jpeg"))
        monkeypatch.setattr(
            receipts_module, "_read_receipt", AsyncMock(return_value=ReceiptExtraction(is_receipt=True, items=["Rice"]))
        )

        tool = _tool_by_name(build(lambda r: httpx.Response(200)), "extract_receipt")
        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert result["not_a_receipt"] is True

    async def test_proposes_one_row_for_the_total_with_the_majority_category(self, build, monkeypatch):
        monkeypatch.setattr(receipts_module.storage, "read_bytes", lambda name: (b"imgdata", "image/jpeg"))
        monkeypatch.setattr(
            receipts_module,
            "_read_receipt",
            AsyncMock(
                return_value=ReceiptExtraction(
                    is_receipt=True,
                    merchant="Alfamart",
                    occurred_on="2026-01-01",
                    currency="idr",
                    total_paid="164100",
                    description="Rice, eggs and 1 more item",
                    items=["Rice 1kg", "Eggs", "Shampoo"],
                )
            ),
        )
        categories = {
            "Rice 1kg - Alfamart": "groceries",
            "Eggs - Alfamart": "groceries",
            "Shampoo - Alfamart": "health",
        }
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            # One batch request for the whole receipt, not one per item.
            assert request.url.path == "/api/transactions/categorize/batch"
            names = json.loads(request.content)["descriptions"]
            seen.append(names)
            return httpx.Response(200, json={"categories": [categories[n] for n in names]})

        tool = _tool_by_name(build(handler), "extract_receipt")
        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert result["ui_event"] == "receipt_proposed"
        # Each item is categorized with the merchant attached, for context.
        assert seen == [["Rice 1kg - Alfamart", "Eggs - Alfamart", "Shampoo - Alfamart"]]
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["amount"] == "164100"
        assert item["category"] == "groceries"
        assert item["currency"] == "IDR"
        assert item["description"] == "Rice, eggs and 1 more item - Alfamart"

    async def test_no_item_names_categorizes_the_description(self, build, monkeypatch):
        monkeypatch.setattr(receipts_module.storage, "read_bytes", lambda name: (b"imgdata", "image/jpeg"))
        monkeypatch.setattr(
            receipts_module,
            "_read_receipt",
            AsyncMock(
                return_value=ReceiptExtraction(
                    is_receipt=True, currency="usd", total_paid="40.00", description="Dinner for two"
                )
            ),
        )

        def handler(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.content)["descriptions"] == ["Dinner for two"]
            return httpx.Response(200, json={"categories": ["dining"]})

        tool = _tool_by_name(build(handler), "extract_receipt")
        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert result["items"][0]["category"] == "dining"

    async def test_categorize_call_failure_defaults_to_other(self, build, monkeypatch):
        monkeypatch.setattr(receipts_module.storage, "read_bytes", lambda name: (b"imgdata", "image/jpeg"))
        monkeypatch.setattr(
            receipts_module,
            "_read_receipt",
            AsyncMock(
                return_value=ReceiptExtraction(is_receipt=True, currency="usd", total_paid="5.00", items=["widget"])
            ),
        )

        tool = _tool_by_name(build(lambda r: httpx.Response(500)), "extract_receipt")
        result = await tool.coroutine(object_name="receipts/u1/x.jpg")

        assert result["items"][0]["category"] == "other"


class TestMajorityCategory:
    def test_most_common_wins(self):
        assert receipts_module._majority_category(["health", "groceries", "groceries"]) == "groceries"

    def test_tie_goes_to_the_first_on_the_receipt(self):
        assert receipts_module._majority_category(["shopping", "groceries", "groceries", "shopping"]) == "shopping"

    def test_empty_is_other(self):
        assert receipts_module._majority_category([]) == "other"


class TestReadReceipt:
    async def test_prompt_substitutes_placeholders_and_stays_locale_neutral(self, monkeypatch):
        captured = {}

        class _FakeVisionModel:
            async def ainvoke(self, messages, config=None):
                captured["prompt"] = messages[0].content[0]["text"]
                return MagicMock(content='{"is_receipt": false}')

        monkeypatch.setattr(receipts_module.llm, "vision_model", lambda: _FakeVisionModel())

        await receipts_module._read_receipt(b"imgdata", "image/jpeg", "en")

        prompt = captured["prompt"]
        today = receipts_module.datetime.date.today().isoformat()
        assert today in prompt
        assert "{today}" not in prompt and "{language}" not in prompt
        # A relative date label ("Today, 5:52 PM") can only be resolved with today's date.
        assert "Today" in prompt and "Yesterday" in prompt
        assert 'set "merchant" to null' in prompt
        # The one amount read is the grand total — not the subtotal or cash tendered.
        assert '"total_paid"' in prompt
        assert "NOT the subtotal" in prompt
        # items drive the majority category: summary labels and fees in there once
        # voted a restaurant delivery order into "groceries" ("Price" vs "Handling and
        # delivery fee" vs "Other discounts", tie -> first).
        assert "list ONLY real" in prompt
        assert "never summary labels" in prompt
        # Receipts come from any country: describe line types by function, never one
        # locale's wording.
        assert "any language" in prompt
        for locale_specific in ("TUNAI", "KEMBALI", "HEMAT", "BELANJA", "PPN", "Indomaret", "rupiah"):
            assert locale_specific not in prompt


class TestFoldMerchant:
    def test_merchant_appended_when_not_already_in_description(self):
        assert receipts_module._fold_merchant("rice", "Alfamart") == "rice - Alfamart"

    def test_merchant_omitted_when_already_present(self):
        assert receipts_module._fold_merchant("rice from Alfamart", "Alfamart") == "rice from Alfamart"

    def test_no_merchant_returns_description_unchanged(self):
        assert receipts_module._fold_merchant("rice", None) == "rice"

    def test_no_description_returns_merchant(self):
        assert receipts_module._fold_merchant(None, "Alfamart") == "Alfamart"

    def test_neither_returns_none(self):
        assert receipts_module._fold_merchant(None, None) is None

    def test_literal_unknown_merchant_is_treated_as_no_merchant(self):
        # Observed: the model wrote "Unknown" as the merchant when it genuinely
        # couldn't read one, which folded in as "3x Camel White 20 - Unknown" — a
        # placeholder that looks like a real (wrong) merchant name.
        assert receipts_module._fold_merchant("3x Camel White 20", "Unknown") == "3x Camel White 20"

    def test_placeholder_merchant_case_insensitive(self):
        assert receipts_module._fold_merchant("rice", "UNKNOWN") == "rice"
        assert receipts_module._fold_merchant("rice", "N/A") == "rice"

    def test_unknown_merchant_with_no_description_returns_none(self):
        assert receipts_module._fold_merchant(None, "Unknown") is None


def _jpeg(width: int, height: int, orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    out = io.BytesIO()
    if orientation is None:
        img.save(out, format="JPEG")
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


class TestShrinkForVision:
    def test_caps_the_long_side_and_keeps_the_aspect_ratio(self):
        shrunk, content_type = receipts_module._shrink_for_vision(_jpeg(1200, 4000), "image/jpeg")
        assert content_type == "image/jpeg"
        with Image.open(io.BytesIO(shrunk)) as img:
            assert img.size == (480, receipts_module.MAX_IMAGE_SIDE)

    def test_leaves_a_small_image_at_its_size(self):
        shrunk, _ = receipts_module._shrink_for_vision(_jpeg(600, 900), "image/jpeg")
        with Image.open(io.BytesIO(shrunk)) as img:
            assert img.size == (600, 900)

    def test_applies_the_exif_rotation_before_dropping_the_tag(self):
        # Orientation 6 = "rotate 90° clockwise to display": a phone's portrait shot
        # stored landscape. Re-encoding without applying it sends a sideways receipt.
        shrunk, _ = receipts_module._shrink_for_vision(_jpeg(400, 300, orientation=6), "image/jpeg")
        with Image.open(io.BytesIO(shrunk)) as img:
            assert img.size == (300, 400)

    def test_undecodable_bytes_are_passed_through_unchanged(self):
        assert receipts_module._shrink_for_vision(b"not an image", "image/png") == (b"not an image", "image/png")
