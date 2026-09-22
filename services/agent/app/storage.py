"""Receipt upload target: a signed GCS URL in production, a direct POST to
fake-gcs-server through Caddy locally. The frontend sends the image with whatever
method/url it receives, so it can't tell the environments apart."""

import datetime
import os

from google.cloud import storage  # honors STORAGE_EMULATOR_HOST

BUCKET = os.environ["RECEIPTS_BUCKET"]


def upload_target(uid: str, object_id: str) -> dict:
    name = f"receipts/{uid}/{object_id}.jpg"
    if os.getenv("STORAGE_MODE") == "local":
        base = os.environ["PUBLIC_UPLOAD_BASE"]
        return {
            "method": "POST",
            "object": name,
            "url": f"{base}/upload/storage/v1/b/{BUCKET}/o?uploadType=media&name={name}",
        }
    blob = storage.Client().bucket(BUCKET).blob(name)
    url = blob.generate_signed_url(
        version="v4", method="PUT", expiration=datetime.timedelta(minutes=5), content_type="image/jpeg"
    )
    return {"method": "PUT", "object": name, "url": url}


def read_bytes(object_name: str) -> tuple[bytes, str]:
    """Reads a receipt image back for vision extraction, plus its actual stored
    content type (populated by the client after download — not from the object name,
    which is always a nominal .jpg regardless of the real format uploaded). Works
    against both fake-gcs-server (STORAGE_EMULATOR_HOST) and real GCS."""
    blob = storage.Client().bucket(BUCKET).blob(object_name)
    data = blob.download_as_bytes()
    return data, blob.content_type or "image/jpeg"
