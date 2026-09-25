"""Internal-endpoint gate (POST /internal/summarize, called by Cloud Tasks / the
local task stand-in — see tasks.py, the only minter). Verifies a Google-signed OIDC
ID token in X-Serverless-Authorization: signature and expiry (via Google's public
certs), a fixed audience both this verifier and tasks.py agree on, and that the
signer is tasks-invoker-sa specifically — not just "any valid Google token".
Locally it's skipped entirely via SKIP_SERVICE_AUTH."""

import os

from fastapi import Header, HTTPException
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token

# Not a real URL — just a fixed string both this file and tasks.py's minter agree
# on. Namespaced per-endpoint so a token minted for a different internal route
# can't be replayed here.
AUDIENCE = "internal://agent/summarize"

_auth_request = google_auth_requests.Request()


async def require_service_caller(
    x_serverless_authorization: str | None = Header(default=None),
) -> None:
    if os.getenv("SKIP_SERVICE_AUTH") == "true":
        return
    if not x_serverless_authorization:
        raise HTTPException(status_code=401, detail="missing service token")

    token = x_serverless_authorization.removeprefix("Bearer ").strip()
    try:
        claims = google_id_token.verify_oauth2_token(token, _auth_request, audience=AUDIENCE)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"invalid service token: {e}") from e

    # TASKS_INVOKER_SERVICE_ACCOUNT is tasks-invoker-sa's email (see
    # terraform/service_accounts.tf and cloud_run.tf) — only Cloud Tasks, minting as
    # that identity, is allowed to call this endpoint.
    expected_caller = os.environ["TASKS_INVOKER_SERVICE_ACCOUNT"]
    if not claims.get("email_verified") or claims.get("email") != expected_caller:
        raise HTTPException(status_code=403, detail="caller not authorized")
