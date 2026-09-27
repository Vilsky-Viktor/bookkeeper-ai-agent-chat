from fastapi import APIRouter, Depends

from .. import db
from ..auth import require_uid
from ..corrections import list_corrections
from ..models.corrections import Correction, CorrectionsResponse

router = APIRouter()


@router.get("/corrections", response_model=CorrectionsResponse)
async def list_corrections_endpoint(uid: str = Depends(require_uid)):
    """The user's saved category corrections, for the agent's categorizer."""

    async with db.uid_conn(uid) as conn:
        rows = await list_corrections(conn, uid)

    return CorrectionsResponse(items=[Correction(item_key=r["item_key"], category=r["category"]) for r in rows])
