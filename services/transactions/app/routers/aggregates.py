from datetime import date

from fastapi import APIRouter, Depends, Query

from .. import db
from ..auth import require_uid
from ..filters import build_filter_clauses
from ..models.aggregates import AggregateItem, AggregatesResponse
from ..money import to_decimal_string

router = APIRouter()


@router.get("/aggregates", response_model=AggregatesResponse)
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
    clauses, params = build_filter_clauses(
        uid,
        currency=currency,
        category=category,
        type=type,
        from_=from_,
        to=to,
        min_amount=min_amount,
        max_amount=max_amount,
        description=description,
    )

    sql = (
        "SELECT currency, category, to_char(date_trunc('month', occurred_on), 'YYYY-MM') AS month, "
        "SUM(amount_minor) AS total_minor, COUNT(*) AS count "
        "FROM transactions WHERE "
        + " AND ".join(clauses)
        + " GROUP BY currency, category, month ORDER BY month DESC, currency, category"
    )
    async with db.uid_conn(uid) as conn:
        rows = await conn.fetch(sql, *params)

    return AggregatesResponse(
        items=[
            AggregateItem(
                currency=r["currency"],
                category=r["category"],
                month=r["month"],
                total=to_decimal_string(r["total_minor"], r["currency"]),
                count=r["count"],
            )
            for r in rows
        ]
    )
