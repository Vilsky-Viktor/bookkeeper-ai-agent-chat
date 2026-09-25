"""Internal-endpoint gate (POST /categorize, called only by agent's extract_receipt
tool — see services/agent/app/tools/receipts.py). Verifies a Google-signed OIDC ID
token in X-Serverless-Authorization: signature and expiry (via Google's public
certs), a fixed audience both this verifier and that one minter agree on, and that
the signer is agent-sa specifically — not just "any valid Google token". Locally
it's skipped entirely via SKIP_SERVICE_AUTH."""

import os

from fastapi import Header, HTTPException
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token

# Not a real URL — just a fixed string both this file and receipts.py's minter
# agree on. Namespaced per-endpoint so a token minted for a different internal
# route can't be replayed here.
AUDIENCE = "internal://transactions/categorize"

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

    # AGENT_SERVICE_ACCOUNT is agent-sa's email (see terraform/service_accounts.tf
    # and cloud_run.tf) — only the agent service is allowed to call this endpoint.
    expected_caller = os.environ["AGENT_SERVICE_ACCOUNT"]
    if not claims.get("email_verified") or claims.get("email") != expected_caller:
        raise HTTPException(status_code=403, detail="caller not authorized")
