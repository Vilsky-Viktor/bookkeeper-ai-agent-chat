"""Receipt upload targets."""

import uuid

from fastapi import APIRouter, Depends

from ..auth import require_uid
from ..models.api import UploadTargetOut, UploadTargetRequest
from ..storage import bucket

router = APIRouter()


@router.post("/uploads", response_model=UploadTargetOut)
async def create_upload_target(body: UploadTargetRequest | None = None, uid: str = Depends(require_uid)):
    """Returns a signed GCS URL in production, a direct fake-gcs URL locally. The
    frontend PUTs/POSTs the file there, then sends the returned `object` path back as
    `receipt_object` on the next /api/chat/chat call."""
    content_type = body.content_type if body else "image/jpeg"

    return bucket.upload_target(uid, str(uuid.uuid4()), content_type)
