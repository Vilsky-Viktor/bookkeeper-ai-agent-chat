from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..auth import require_uid
from ..categorize import categorize
from ..money import InvalidAmount, to_minor
from ..service_auth import require_service_caller

router = APIRouter()


class CategorizeRequest(BaseModel):
    description: str | None = None
    amount: str
    currency: str
    type: str = "expense"


@router.post("/categorize", dependencies=[Depends(require_service_caller)])
async def categorize_endpoint(body: CategorizeRequest, uid: str = Depends(require_uid)):
    try:
        amount_minor = to_minor(body.amount, body.currency)
    except InvalidAmount as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    async with db.uid_conn(uid) as conn:
        category = await categorize(conn, uid, body.description, amount_minor, body.currency, body.type)
    return {"category": category}
