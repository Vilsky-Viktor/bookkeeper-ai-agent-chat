"""DELETE /transactions (bulk, filtered) and DELETE /transactions/{id} (single)."""

from datetime import date

from fastapi import Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from ... import db, signal
from ...auth import require_uid
from ...filters import build_filter_clauses
from ...idempotency import run_idempotent
from ...models.transactions import BulkDeleteFilterPayload, BulkDeleteResponse, DeleteResponse
from . import router


@router.delete("/transactions", response_model=BulkDeleteResponse)
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

    payload = BulkDeleteFilterPayload(
        currency=currency,
        category=category,
        type=type,
        from_=from_.isoformat() if from_ else None,  # type: ignore[call-arg]
        # ^ pydantic's static typing only recognizes the alias ("from") as a valid
        # constructor keyword, but "from" alone isn't valid Python keyword-argument
        # syntax — from_= is correct and works at runtime (populate_by_name=True on
        # the model), mypy just can't express it; see the model's own docstring.
        to=to.isoformat() if to else None,
        min_amount=min_amount,
        max_amount=max_amount,
        description=description,
    ).model_dump(by_alias=True)

    async with db.uid_conn(uid) as conn:

        async def handler() -> tuple[int, dict]:
            sql = "DELETE FROM transactions WHERE " + " AND ".join(clauses)
            result = await conn.execute(sql, *params)
            deleted_count = int(result.split(" ")[1]) if result.startswith("DELETE") else 0
            return 200, BulkDeleteResponse(deleted_count=deleted_count).model_dump()

        status, response, replayed = await run_idempotent(conn, uid, idempotency_key, payload, handler)

    if not replayed and status < 300:
        await signal.bump_async(uid, ["transactions_version"], x_client_id)
    # Dynamic status code means a raw JSONResponse, same as create/patch —
    # response_model above is doc-only; the .model_dump() calls are what actually
    # guarantee the wire shape.
    return JSONResponse(status_code=status, content=response)


@router.delete("/transactions/{transaction_id}", response_model=DeleteResponse)
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
            return 200, DeleteResponse(deleted=transaction_id).model_dump()

        status, response, replayed = await run_idempotent(conn, uid, idempotency_key, payload, handler)

    if not replayed and status < 300:
        await signal.bump_async(uid, ["transactions_version"], x_client_id)
    return JSONResponse(status_code=status, content=response)
