"""Exchange-rate lookups and cross-currency total conversion — both tools share the
_fetch_exchange_rate() HTTP-fetch helper below."""

from decimal import Decimal
from typing import Callable, Optional

import httpx
from langchain_core.tools import BaseTool, tool

from ..models.tool_results import CurrencyBreakdownEntry, ExchangeRateResult, ToolError, TotalInCurrencyResult
from .filters import filter_params

# Free, no-key, daily-updated exchange rates covering 300+ currencies (vs. ~30 for the
# ECB-only Frankfurter.app source this replaced, which didn't have UAH). Static JSON on
# two independent CDN mirrors — jsdelivr first, the project's own Cloudflare Pages
# mirror as a fallback if that one's unreachable. Source: fawazahmed0/currency-api.
CURRENCY_API_URLS = [
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{code}.json",
    "https://latest.currency-api.pages.dev/v1/currencies/{code}.json",
]


async def _fetch_exchange_rate(from_currency: str, to_currency: str) -> dict:
    """Shared by the get_exchange_rate and get_total_in_currency tools below — kept
    as a plain function (not a @tool) since only one of the two needs it exposed to
    the model directly."""
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    data = None
    for url_tpl in CURRENCY_API_URLS:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.get(url_tpl.format(code=from_currency.lower()), follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
            break
        except httpx.HTTPError:
            continue
    if data is None:
        return ToolError(
            error=(
                f"Couldn't reach the exchange rate service for {from_currency} to "
                f"{to_currency} right now — this looks transient, worth trying again."
            )
        ).model_dump()
    rate = data.get(from_currency.lower(), {}).get(to_currency.lower())
    if rate is None:
        return ToolError(
            error=(
                f"{from_currency} or {to_currency} isn't a currency code this data "
                "source recognizes — double-check it with the user."
            )
        ).model_dump()
    return ExchangeRateResult(
        **{"from": from_currency},
        to=to_currency,
        rate=rate,
        date=data.get("date"),
        note="Daily reference rate, not real-time.",
    ).model_dump(by_alias=True)


def build_currency_tools(http_client: Callable[[], httpx.AsyncClient]) -> list[BaseTool]:
    @tool
    async def get_exchange_rate(from_currency: str, to_currency: str) -> dict:
        """Daily reference exchange rate between two 3-letter currency codes, for the
        user's information only."""
        return await _fetch_exchange_rate(from_currency, to_currency)

    @tool
    async def get_total_in_currency(
        to_currency: str,
        type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        currency: Optional[str] = None,
        category: Optional[str] = None,
    ) -> dict:
        """Total of transactions (optionally filtered, same filters as
        query_transactions) converted into to_currency, with exact per-currency
        arithmetic. Use it for any total that spans more than one currency."""
        params = filter_params(type=type, from_date=from_date, to_date=to_date, currency=currency, category=category)
        async with http_client() as c:
            resp = await c.get("/api/transactions/aggregates", params=params)
        resp.raise_for_status()
        items = resp.json().get("items", [])

        to_currency = to_currency.upper()
        totals_by_currency: dict[str, Decimal] = {}
        for item in items:
            src = item["currency"].upper()
            totals_by_currency[src] = totals_by_currency.get(src, Decimal(0)) + Decimal(item["total"])

        if not totals_by_currency:
            return TotalInCurrencyResult(total="0.00", currency=to_currency, breakdown=[]).model_dump(exclude_none=True)

        breakdown: list[CurrencyBreakdownEntry] = []
        grand_total = Decimal(0)
        for src_currency, amount in totals_by_currency.items():
            if src_currency == to_currency:
                converted = amount
                rate = None
            else:
                rate_result = await _fetch_exchange_rate(src_currency, to_currency)
                if "error" in rate_result:
                    return rate_result
                rate = Decimal(str(rate_result["rate"]))
                converted = amount * rate
            grand_total += converted
            breakdown.append(
                CurrencyBreakdownEntry(
                    currency=src_currency,
                    amount=str(amount),
                    rate=str(rate) if rate is not None else None,
                    converted=str(converted),
                )
            )

        return TotalInCurrencyResult(
            total=str(grand_total.quantize(Decimal("0.01"))),
            currency=to_currency,
            breakdown=breakdown,
            note="Daily reference rate, not real-time.",
        ).model_dump(exclude_none=True)

    return [get_exchange_rate, get_total_in_currency]
