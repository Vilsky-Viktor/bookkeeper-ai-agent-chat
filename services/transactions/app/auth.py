"""JWT verification. Always on, local too — this is the isolation boundary."""

from fastapi import Header, HTTPException
from firebase_admin import auth as fb_auth
from firebase_admin import initialize_app

initialize_app()  # honors FIREBASE_AUTH_EMULATOR_HOST / GOOGLE_CLOUD_PROJECT


async def require_uid(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        decoded = fb_auth.verify_id_token(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e}") from e
    return decoded["uid"]
