"""GET /transactions — paginated listing with the shared filter set."""

from datetime import date, datetime

from fastapi import Depends, HTTPException, Query

from ... import db
from ...auth import require_uid
from ...filters import build_filter_clauses
from ...models.transactions import TransactionsListResponse
from . import router
from .serializers import row_to_out


@router.get("/transactions", response_model=TransactionsListResponse)
async def list_transactions(
    currency: str | None = None,
    category: str | None = None,
    type: str | None = Query(default=None, alias="type"),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    description: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
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

    if cursor:
        try:
            c_date, c_created_at, c_id = cursor.split("_", 2)
            c_date_parsed = date.fromisoformat(c_date)
            c_created_at_parsed = datetime.fromisoformat(c_created_at)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid cursor") from e
        params.append(c_date_parsed)
        params.append(c_created_at_parsed)
        params.append(c_id)
        clauses.append(f"(occurred_on, created_at, id) < (${len(params) - 2}, ${len(params) - 1}, ${len(params)})")

    params.append(limit)
    # created_at (not id, which is a random uuid) breaks ties within the same
    # occurred_on date, so same-day rows show most-recently-added first.
    sql = (
        "SELECT * FROM transactions WHERE "
        + " AND ".join(clauses)
        + f" ORDER BY occurred_on DESC, created_at DESC, id DESC LIMIT ${len(params)}"
    )

    async with db.uid_conn(uid) as conn:
        rows = await conn.fetch(sql, *params)

    items = [row_to_out(r) for r in rows]
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = f"{last['occurred_on'].isoformat()}_{last['created_at'].isoformat()}_{last['id']}"
    return {"items": items, "next_cursor": next_cursor}
