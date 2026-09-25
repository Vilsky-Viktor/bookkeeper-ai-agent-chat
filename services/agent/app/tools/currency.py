"""Exchange-rate lookups and cross-currency total conversion — both tools share the
_fetch_exchange_rate() HTTP-fetch helper below."""

from decimal import Decimal
from typing import Callable, Optional

import httpx
from langchain_core.tools import BaseTool, tool

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
        return {
            "error": (
                f"Couldn't reach the exchange rate service for {from_currency} to "
                f"{to_currency} right now — this looks transient, worth trying again."
            )
        }
    rate = data.get(from_currency.lower(), {}).get(to_currency.lower())
    if rate is None:
        return {
            "error": (
                f"{from_currency} or {to_currency} isn't a currency code this data "
                "source recognizes — double-check it with the user."
            )
        }
    return {
        "from": from_currency,
        "to": to_currency,
        "rate": rate,
        "date": data.get("date"),
        "note": "Daily reference rate, not real-time.",
    }


def build_currency_tools(http_client: Callable[[], httpx.AsyncClient]) -> list[BaseTool]:
    @tool
    async def get_exchange_rate(from_currency: str, to_currency: str) -> dict:
        """Look up the current exchange rate between two currencies (e.g. "what's the
        exchange rate from USD to EUR", "how much is 50 USD in IDR") — free, no API
        key, daily-updated, covers 300+ currencies. This is a daily rate, not
        tick-by-tick live market data, and it's for the user's reference only: never
        use it to silently convert or alter a transaction's actual stated
        amount/currency — record what the user said exactly. currencies are 3-letter
        ISO codes."""
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
        """Sums transactions (optionally filtered by type/date range/currency/
        category, same filters as query_transactions) and converts the result into
        to_currency. Use this for ANY total that spans more than one currency (e.g.
        "total expenses this month in USD", "how much have I spent overall in EUR")
        — it does the per-currency aggregation and the multiply-and-convert
        arithmetic in code, not an approximation. Never compute a cross-currency
        total yourself by calling query_transactions(aggregate=true) and
        get_exchange_rate separately and doing the multiplication/summing in your
        own reply — that arithmetic is not guaranteed to be exact, this tool's is.
        Same daily reference rate as get_exchange_rate, not live tick-by-tick data."""
        params = {
            k: v
            for k, v in {
                "type": type,
                "from": from_date,
                "to": to_date,
                "currency": currency,
                "category": category,
            }.items()
            if v is not None
        }
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
            return {"total": "0.00", "currency": to_currency, "breakdown": []}

        breakdown = []
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
                {
                    "currency": src_currency,
                    "amount": str(amount),
                    "rate": str(rate) if rate is not None else None,
                    "converted_to_" + to_currency.lower(): str(converted),
                }
            )

        return {
            "total": str(grand_total.quantize(Decimal("0.01"))),
            "currency": to_currency,
            "breakdown": breakdown,
            "note": "Daily reference rate, not real-time.",
        }

    return [get_exchange_rate, get_total_in_currency]
