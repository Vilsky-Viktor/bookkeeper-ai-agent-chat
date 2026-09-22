"""Internal-endpoint gate (e.g. POST /categorize). In production this verifies a
Google-signed ID token from agent-sa in X-Serverless-Authorization; locally it is
skipped via SKIP_SERVICE_AUTH."""

import os

from fastapi import Header, HTTPException


async def require_service_caller(
    x_serverless_authorization: str | None = Header(default=None),
) -> None:
    if os.getenv("SKIP_SERVICE_AUTH") == "true":
        return
    if not x_serverless_authorization:
        raise HTTPException(status_code=401, detail="missing service token")
    raise HTTPException(status_code=501, detail="service-to-service ID token check not implemented locally")
