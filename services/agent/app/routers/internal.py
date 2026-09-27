"""Service-to-service endpoints (Cloud Tasks)."""

from fastapi import APIRouter, Depends

from ..models.api import HealthzResponse, SummarizeRequest
from ..service_auth import require_service_caller
from ..services.summarize import run_summarize

router = APIRouter()


@router.post("/summarize", dependencies=[Depends(require_service_caller)], response_model=HealthzResponse)
async def summarize_endpoint(body: SummarizeRequest):
    await run_summarize(body.uid, body.thread_id, body.through_seq)

    return HealthzResponse(ok=True)
