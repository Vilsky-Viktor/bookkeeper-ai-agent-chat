"""PATCH /transactions/{id} — partial update, including the currency-rescale
handling when currency changes without an explicit new amount."""

from fastapi import Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from ... import db, signal
from ...auth import require_uid
from ...categorize import save_correction
from ...idempotency import run_idempotent
from ...models.transactions import PatchIdempotencyPayload, TransactionOut, TransactionPatch
from ...money import InvalidAmount, to_decimal_string, to_minor
from . import router
from .serializers import row_to_out


@router.patch("/transactions/{transaction_id}", response_model=TransactionOut)
async def patch_transaction(
    transaction_id: str,
    body: TransactionPatch,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    uid: str = Depends(require_uid),
):
    fields = body.model_dump(exclude_unset=True)
    payload = PatchIdempotencyPayload(id=transaction_id, **fields).model_dump(exclude_unset=True)

    async with db.uid_conn(uid) as conn:

        async def handler() -> tuple[int, dict]:
            existing = await conn.fetchrow("SELECT * FROM transactions WHERE uid=$1 AND id=$2", uid, transaction_id)
            if not existing:
                raise HTTPException(status_code=404, detail="transaction not found")

            currency = fields.get("currency", existing["currency"])
            if "amount" in fields:
                try:
                    amount_minor = to_minor(fields["amount"], currency)
                except InvalidAmount as e:
                    raise HTTPException(status_code=400, detail=str(e)) from e
            elif currency != existing["currency"]:
                # Currency changed but amount didn't: reinterpret the existing
                # numeric value under the new currency's precision. Reusing
                # amount_minor as-is here would read the old currency's minor units
                # back under the new currency's exponent — e.g. a 2-decimal amount's
                # stored integer, read back as a 0-decimal currency, silently
                # inflates the displayed amount by 100x.
                existing_amount = to_decimal_string(existing["amount_minor"], existing["currency"])
                try:
                    amount_minor = to_minor(existing_amount, currency)
                except InvalidAmount as e:
                    raise HTTPException(status_code=400, detail=str(e)) from e
            else:
                amount_minor = existing["amount_minor"]

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
            return 200, row_to_out(row).model_dump(mode="json")

        status, response, replayed = await run_idempotent(conn, uid, idempotency_key, payload, handler)

    if not replayed and status < 300:
        await signal.bump_async(uid, ["transactions_version"], x_client_id)
    # Dynamic status code (200 fresh vs. replayed) means this returns a raw
    # JSONResponse rather than relying on FastAPI's response_model machinery —
    # response_model above is doc-only here; the .model_dump(mode="json") above is
    # what actually guarantees the wire shape matches TransactionOut.
    return JSONResponse(status_code=status, content=response)
