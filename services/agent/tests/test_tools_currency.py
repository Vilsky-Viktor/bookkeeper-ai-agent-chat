"""Currency tools: exchange rate and total in one currency."""

import json

import httpx
from tool_helpers import tool_by_name


class TestGetExchangeRate:
    async def test_success_from_primary_source(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "usd.json" in str(request.url)

            return httpx.Response(200, json={"date": "2026-01-01", "usd": {"eur": 0.9}})

        tool = tool_by_name(build(handler), "get_exchange_rate")
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

        tool = tool_by_name(build(handler), "get_exchange_rate")
        result = await tool.coroutine(from_currency="usd", to_currency="idr")

        assert result["rate"] == 15800
        assert len(calls) == 2

    async def test_both_sources_unreachable_returns_error_dict(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unreachable", request=request)

        tool = tool_by_name(build(handler), "get_exchange_rate")
        result = await tool.coroutine(from_currency="usd", to_currency="eur")

        assert "error" in result
        assert "transient" in result["error"]

    async def test_unrecognized_currency_returns_error_dict(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"date": "2026-01-01", "usd": {"eur": 0.9}})

        tool = tool_by_name(build(handler), "get_exchange_rate")
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

        tool = tool_by_name(build(handler), "get_total_in_currency")
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

        tool = tool_by_name(build(handler), "get_total_in_currency")
        result = await tool.coroutine(to_currency="usd")

        # 150000 IDR * 0.00006 = 9.0; 600 UAH * 0.024 = 14.4; total = 23.4
        assert result["currency"] == "USD"
        assert result["total"] == "23.40"
        assert len(result["breakdown"]) == 2

    async def test_no_transactions_returns_zero(self, build):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": []})

        tool = tool_by_name(build(handler), "get_total_in_currency")
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

        tool = tool_by_name(build(handler), "get_total_in_currency")
        result = await tool.coroutine(to_currency="usd")

        assert "error" in result

    async def test_filters_passed_through_to_aggregates_request(self, build):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)

            return httpx.Response(200, json={"items": []})

        tool = tool_by_name(build(handler), "get_total_in_currency")
        await tool.coroutine(
            to_currency="usd", type="expense", from_date="2026-01-01", to_date="2026-01-31", category="dining"
        )

        assert captured["params"] == {
            "type": "expense",
            "from": "2026-01-01",
            "to": "2026-01-31",
            "category": "dining",
        }
