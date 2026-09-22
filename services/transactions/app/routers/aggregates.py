from datetime import date

from fastapi import APIRouter, Depends, Query

from .. import db
from ..auth import require_uid
from ..money import to_decimal_string

router = APIRouter()


@router.get("/aggregates")
async def aggregates(
    currency: str | None = None,
    type: str | None = Query(default=None, alias="type"),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    uid: str = Depends(require_uid),
):
    clauses = ["uid = $1"]
    params: list = [uid]

    def add(clause_tpl: str, value) -> None:
        params.append(value)
        clauses.append(clause_tpl.format(n=len(params)))

    if currency:
        add("currency = ${n}", currency.upper())
    if type:
        add("type = ${n}", type)
    if from_:
        add("occurred_on >= ${n}", from_)
    if to:
        add("occurred_on <= ${n}", to)

    sql = (
        "SELECT currency, category, to_char(date_trunc('month', occurred_on), 'YYYY-MM') AS month, "
        "SUM(amount_minor) AS total_minor, COUNT(*) AS count "
        "FROM transactions WHERE " + " AND ".join(clauses)
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
