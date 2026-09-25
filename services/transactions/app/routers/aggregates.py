from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..auth import require_uid
from ..money import InvalidAmount, to_decimal_string, to_minor

router = APIRouter()


@router.get("/aggregates")
async def aggregates(
    currency: str | None = None,
    category: str | None = None,
    type: str | None = Query(default=None, alias="type"),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    description: str | None = None,
    uid: str = Depends(require_uid),
):
    # Same filter set as GET /transactions (list_transactions in transactions.py) —
    # query_transactions's own docstring promises callers the same filters apply in
    # both modes, but this endpoint only ever implemented currency/type/from/to;
    # category (and the rest) were silently ignored by FastAPI rather than erroring,
    # so a category-filtered aggregate call quietly returned the unfiltered total.
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
        add("description ILIKE ${n}", f"%{description}%")

    exponent_currency = currency.upper() if currency else "USD"
    try:
        if min_amount:
            add("amount_minor >= ${n}", to_minor(min_amount, exponent_currency))
        if max_amount:
            add("amount_minor <= ${n}", to_minor(max_amount, exponent_currency))
    except InvalidAmount as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    sql = (
        "SELECT currency, category, to_char(date_trunc('month', occurred_on), 'YYYY-MM') AS month, "
        "SUM(amount_minor) AS total_minor, COUNT(*) AS count "
        "FROM transactions WHERE "
        + " AND ".join(clauses)
        + " GROUP BY currency, category, month ORDER BY month DESC, currency, category"
    )
    async with db.uid_conn(uid) as conn:
        rows = await conn.fetch(sql, *params)

    return {
        "items": [
            {
                "currency": r["currency"],
                "category": r["category"],
                "month": r["month"],
                "total": to_decimal_string(r["total_minor"], r["currency"]),
                "count": r["count"],
            }
            for r in rows
        ]
    }
