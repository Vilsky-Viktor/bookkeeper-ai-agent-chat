from datetime import date, datetime

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from .. import db, signal
from ..auth import require_uid
from ..categorize import categorize, save_correction
from ..idempotency import run_idempotent
from ..money import InvalidAmount, to_decimal_string, to_minor
from ..schemas import CreateBatchRequest, TransactionPatch

router = APIRouter()


def _row_to_out(row: asyncpg.Record) -> dict:
    return {
        "id": str(row["id"]),
        "uid": row["uid"],
        "occurred_on": row["occurred_on"].isoformat(),
        "type": row["type"],
        "amount": to_decimal_string(row["amount_minor"], row["currency"]),
        "currency": row["currency"],
        "category": row["category"],
        "description": row["description"],
        "receipt_uri": row["receipt_uri"],
        "batch_id": str(row["batch_id"]) if row["batch_id"] else None,
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/transactions")
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
        clauses.append(
            f"(occurred_on, created_at, id) < (${len(params) - 2}, ${len(params) - 1}, ${len(params)})"
        )

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

    items = [_row_to_out(r) for r in rows]
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = f"{last['occurred_on'].isoformat()}_{last['created_at'].isoformat()}_{last['id']}"
    return {"items": items, "next_cursor": next_cursor}


@router.post("/transactions", status_code=201)
async def create_transactions(
    body: CreateBatchRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    uid: str = Depends(require_uid),
):
    if not body.transactions:
        raise HTTPException(status_code=400, detail="transactions must be non-empty")

    payload = [t.model_dump() for t in body.transactions]

    async with db.uid_conn(uid) as conn:

        async def handler() -> tuple[int, dict]:
            created = []
            for t in body.transactions:
                try:
                    amount_minor = to_minor(t.amount, t.currency)
                except InvalidAmount as e:
                    raise HTTPException(status_code=400, detail=str(e)) from e
                category = t.category or await categorize(
                    conn, uid, t.description, amount_minor, t.currency, t.type
                )
                row = await conn.fetchrow(
                    """
                    INSERT INTO transactions
                        (uid, occurred_on, type, amount_minor, currency, category,
                         description, receipt_uri, batch_id)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    RETURNING *
                    """,
                    uid, t.occurred_on, t.type, amount_minor, t.currency, category,
                    t.description, t.receipt_uri, t.batch_id,
                )
                created.append(_row_to_out(row))

                # Receipt confirmation flow: the user may have edited a proposed row's
                # category before confirming. That edit is a correction for future
                # extractions of this item (architecture doc, Receipt ingestion, p.
                # 11), even though this call is a create, not a PATCH.
                if t.receipt_uri and t.category:
                    await save_correction(conn, uid, t.description, category)
            return 201, {"items": created}

        status, response, replayed = await run_idempotent(conn, uid, idempotency_key, payload, handler)

    if not replayed and status < 300:
        await signal.bump_async(uid, ["transactions_version"], x_client_id)
    return JSONResponse(status_code=status, content=response)


@router.patch("/transactions/{transaction_id}")
async def patch_transaction(
    transaction_id: str,
    body: TransactionPatch,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    uid: str = Depends(require_uid),
):
    fields = body.model_dump(exclude_unset=True)
    payload = {"id": transaction_id, **fields}

    async with db.uid_conn(uid) as conn:

        async def handler() -> tuple[int, dict]:
            existing = await conn.fetchrow(
                "SELECT * FROM transactions WHERE uid=$1 AND id=$2", uid, transaction_id
            )
            if not existing:
                raise HTTPException(status_code=404, detail="transaction not found")

            currency = fields.get("currency", existing["currency"])
            amount_minor = existing["amount_minor"]
            if "amount" in fields:
                try:
                    amount_minor = to_minor(fields["amount"], currency)
                except InvalidAmount as e:
                    raise HTTPException(status_code=400, detail=str(e)) from e

            category = fields.get("category", existing["category"])
            description = fields.get("description", existing["description"])

            row = await conn.fetchrow(
                """
                UPDATE transactions SET
                    occurred_on = $1, type = $2, amount_minor = $3, currency = $4,
                    category = $5, description = $6
                WHERE uid = $7 AND id = $8
                RETURNING *
                """,
                fields.get("occurred_on", existing["occurred_on"]),
                fields.get("type", existing["type"]),
                amount_minor,
                currency,
                category,
                description,
                uid,
                transaction_id,
            )

            # See categorize.py's save_correction: keyed purely on the normalized
            # description, so this correction only reliably reapplies to a
            # near-identical description in the future (the LLM fallback path handles
            # near-duplicates that don't match exactly).
            if "category" in fields:
                await save_correction(conn, uid, description, category)
            return 200, _row_to_out(row)

        status, response, replayed = await run_idempotent(conn, uid, idempotency_key, payload, handler)

    if not replayed and status < 300:
        await signal.bump_async(uid, ["transactions_version"], x_client_id)
    return JSONResponse(status_code=status, content=response)


@router.delete("/transactions")
async def delete_transactions_bulk(
    currency: str | None = None,
    category: str | None = None,
    type: str | None = Query(default=None, alias="type"),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    description: str | None = None,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    uid: str = Depends(require_uid),
):
    # Deletes every transaction matching the given filters in one statement — no
    # filters means every transaction the uid owns. This exists because the agent's
    # bulk-delete-by-id loop only ever sees one page of query_transactions results
    # (default 50), so "delete all my transactions" silently deleted just that page.
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

    payload = {
        "currency": currency, "category": category, "type": type,
        "from": from_.isoformat() if from_ else None, "to": to.isoformat() if to else None,
        "min_amount": min_amount, "max_amount": max_amount, "description": description,
    }

    async with db.uid_conn(uid) as conn:

        async def handler() -> tuple[int, dict]:
            sql = "DELETE FROM transactions WHERE " + " AND ".join(clauses)
            result = await conn.execute(sql, *params)
            deleted_count = int(result.split(" ")[1]) if result.startswith("DELETE") else 0
            return 200, {"deleted_count": deleted_count}

        status, response, replayed = await run_idempotent(conn, uid, idempotency_key, payload, handler)

    if not replayed and status < 300:
        await signal.bump_async(uid, ["transactions_version"], x_client_id)
    return JSONResponse(status_code=status, content=response)


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(
    transaction_id: str,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    uid: str = Depends(require_uid),
):
    payload = {"id": transaction_id}

    async with db.uid_conn(uid) as conn:

        async def handler() -> tuple[int, dict]:
            result = await conn.execute("DELETE FROM transactions WHERE uid=$1 AND id=$2", uid, transaction_id)
            if result == "DELETE 0":
                raise HTTPException(status_code=404, detail="transaction not found")
            return 200, {"deleted": transaction_id}

        status, response, replayed = await run_idempotent(conn, uid, idempotency_key, payload, handler)

    if not replayed and status < 300:
        await signal.bump_async(uid, ["transactions_version"], x_client_id)
    return JSONResponse(status_code=status, content=response)
