from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import require_uid
from ..categorize import categorize
from ..models.categorize import CategorizeRequest, CategorizeResponse
from ..money import InvalidAmount, to_minor
from ..service_auth import require_service_caller

router = APIRouter()


@router.post("/categorize", dependencies=[Depends(require_service_caller)], response_model=CategorizeResponse)
async def categorize_endpoint(body: CategorizeRequest, uid: str = Depends(require_uid)):
    try:
        amount_minor = to_minor(body.amount, body.currency)
    except InvalidAmount as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    async with db.uid_conn(uid) as conn:
        category = await categorize(conn, uid, body.description, amount_minor, body.currency, body.type)
    return CategorizeResponse(category=category)
