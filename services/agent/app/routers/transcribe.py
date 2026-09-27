"""Voice input: audio to text."""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..auth import require_uid
from ..constants.languages import SUPPORTED_LANGUAGES
from ..integrations import llm
from ..models.api import TranscribeResponse
from ..storage import chat_db

log = logging.getLogger("agent")

router = APIRouter()


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(file: UploadFile = File(...), uid: str = Depends(require_uid)):
    """Transcribes a recorded voice message to text — the frontend then drops that
    text into the message box for the user to review/edit before sending, same as any
    typed message. Doesn't touch quotas itself; the actual chat turn it feeds into
    does."""
    audio_bytes = await file.read()

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty audio")

    async with chat_db.uid_conn(uid) as conn:
        preferences_row = await chat_db.get_preferences(conn, uid)
    language = (dict(preferences_row) if preferences_row else {}).get("language")

    # The SDK's `language` param takes a plain str (or must be omitted entirely) — it
    # doesn't accept None as "no hint", so this is only added when there's a real value.
    transcribe_kwargs = {"language": language} if language in SUPPORTED_LANGUAGES else {}

    try:
        resp = await llm.transcribe_client().audio.transcriptions.create(
            model=llm.TRANSCRIBE_MODEL,
            file=(file.filename or "audio.webm", audio_bytes, file.content_type or "audio/webm"),
            **transcribe_kwargs,
        )
    except Exception as e:
        log.warning("transcription failed: %s", e)
        raise HTTPException(status_code=502, detail="Couldn't transcribe that — please try again.") from e

    return TranscribeResponse(text=resp.text)
