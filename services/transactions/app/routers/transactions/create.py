"""POST /transactions — batch create, used both for chat-driven adds and receipt
confirmation."""

from fastapi import Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from ... import db, signal
from ...auth import require_uid
from ...categorize import categorize, save_correction
from ...idempotency import run_idempotent
from ...models.transactions import CreateBatchRequest, TransactionsListResponse
from ...money import InvalidAmount, to_minor
from . import router
from .serializers import row_to_out


@router.post("/transactions", status_code=201, response_model=TransactionsListResponse)
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
                category = t.category or await categorize(conn, uid, t.description, amount_minor, t.currency, t.type)
                row = await conn.fetchrow(
                    """
                    INSERT INTO transactions
                        (uid, occurred_on, type, amount_minor, currency, category,
                         description, receipt_uri, batch_id)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    RETURNING *
                    """,
                    uid,
                    t.occurred_on,
                    t.type,
                    amount_minor,
                    t.currency,
                    category,
                    t.description,
                    t.receipt_uri,
                    t.batch_id,
                )
                created.append(row_to_out(row).model_dump(mode="json"))

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
    # This endpoint's status code is dynamic (200 on idempotency replay, 201 on a
    # fresh create), so it returns a raw JSONResponse instead of relying on FastAPI's
    # response_model machinery to serialize it — response_model above is doc-only
    # here; `.model_dump(mode="json")` above is what actually guarantees the wire
    # shape matches TransactionsListResponse.
    return JSONResponse(status_code=status, content=response)
