"""The user's preferences (language)."""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_uid
from ..constants.languages import SUPPORTED_LANGUAGES
from ..models.api import PreferencesOut, PreferencesUpdate
from ..storage import chat_db

router = APIRouter()


@router.get("/preferences", response_model=PreferencesOut)
async def get_preferences_endpoint(uid: str = Depends(require_uid)):
    async with chat_db.uid_conn(uid) as conn:
        row = await chat_db.get_preferences(conn, uid)

    return PreferencesOut(
        language=row["language"] if row else "en",
        default_currency=row["default_currency"] if row else None,
    )


@router.put("/preferences", response_model=PreferencesOut)
async def update_preferences_endpoint(body: PreferencesUpdate, uid: str = Depends(require_uid)):
    if body.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"unsupported language: {body.language}")

    async with chat_db.uid_conn(uid) as conn:
        row = await chat_db.set_language(conn, uid, body.language)

    return PreferencesOut(language=row["language"], default_currency=row["default_currency"])
