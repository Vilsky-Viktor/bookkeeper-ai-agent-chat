"""Shared filter-clause building for every endpoint that filters transactions by
currency/category/type/date range/amount range/description: list_transactions,
delete_transactions_bulk (both in routers/transactions/), and aggregates all share
this exact filter set — query_transactions's docstring on the agent side promises
callers the same filters apply everywhere, so this needs to be one implementation,
not three copies that can drift."""

from datetime import date

from fastapi import HTTPException

from .money import InvalidAmount, to_minor


def build_filter_clauses(
    uid: str,
    *,
    currency: str | None = None,
    category: str | None = None,
    type: str | None = None,
    from_: date | None = None,
    to: date | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    description: str | None = None,
) -> tuple[list[str], list]:
    """Returns (clauses, params), starting from (["uid = $1"], [uid]) — ready to join
    with " AND " into a WHERE clause. Raises HTTPException(400) if min_amount/
    max_amount don't parse for the filtered (or default USD) currency."""
    clauses = ["uid = $1"]
    params: list = [uid]

    def add(clause_tpl: str, value) -> None:
        params.append(value)
        clauses.append(clause_tpl.format(n=len(params)))

    if currency:
        add("currency = ${n}", currency.upper())
    if category:
        add("category = ${n}", category)
    if type:
        add("type = ${n}", type)
    if from_:
        add("occurred_on >= ${n}", from_)
    if to:
        add("occurred_on <= ${n}", to)
    if description:
        # Case-insensitive substring match — lets the agent find a transaction by
        # what it was for ("the bagel one") across the whole table, not just the
        # current thread's recently-touched working set.
        add("description ILIKE ${n}", f"%{description}%")

    exponent_currency = currency.upper() if currency else "USD"
    try:
        if min_amount:
            add("amount_minor >= ${n}", to_minor(min_amount, exponent_currency))
        if max_amount:
            add("amount_minor <= ${n}", to_minor(max_amount, exponent_currency))
    except InvalidAmount as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return clauses, params
