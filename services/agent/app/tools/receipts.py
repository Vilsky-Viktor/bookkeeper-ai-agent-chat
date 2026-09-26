"""Receipt image/PDF extraction: PDF->PNG rendering, merchant-name folding, the
vision-model call, and the extract_receipt tool itself."""

import asyncio
import base64
import datetime
import io
import json
import os
from collections import Counter
from typing import Callable

import httpx
import pymupdf
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, tool
from PIL import Image, ImageOps

from .. import llm, storage
from ..languages import SUPPORTED_LANGUAGES
from ..models.tool_results import (
    NotAReceiptResult,
    ReceiptExtraction,
    ReceiptProposedItem,
    ReceiptProposedResult,
    ToolError,
)
from .prompts import RECEIPT_EXTRACTION_PROMPT

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

# Must match transactions' service_auth.py's AUDIENCE for POST /categorize exactly
# — not a real URL, just a fixed string both sides agree on.
_CATEGORIZE_AUDIENCE = "internal://transactions/categorize"
_auth_request = google_auth_requests.Request()


async def _categorize_service_token() -> str | None:
    """A signed OIDC token proving this call really came from the agent service —
    verified by transactions' require_service_caller. None locally
    (SKIP_SERVICE_AUTH): there's no real GCP identity to mint one with outside
    Cloud Run/gcloud ADC, and the receiving side doesn't check it either in that
    mode. Minting hits the metadata server, so it's pushed off the event loop."""
    if os.getenv("SKIP_SERVICE_AUTH") == "true":
        return None
    return await asyncio.to_thread(google_id_token.fetch_id_token, _auth_request, _CATEGORIZE_AUDIENCE)


PDF_RENDER_DPI = 200
# Long-side cap for what's sent to the vision model. Phone photos are often 4000px+
# and several MB of base64; OpenAI downsizes them anyway (to fit 2048px, then 768px
# on the short side), so the extra pixels only cost upload size and latency — and on
# patch-billed models (gpt-4.1 family) they cost tokens directly.
MAX_IMAGE_SIDE = 1600


def _pdf_first_page_to_png(pdf_bytes: bytes) -> bytes:
    """Renders a PDF receipt's first page to PNG bytes for the vision model — receipts
    are effectively always one page, and OpenAI's vision endpoint doesn't take PDF
    input directly. The original PDF stays the stored receipt_uri; this rendering is
    only ever used in-memory for extraction."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        pixmap = doc[0].get_pixmap(dpi=PDF_RENDER_DPI)
        return pixmap.tobytes("png")
    finally:
        doc.close()


def _shrink_for_vision(image_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    """Downscales to MAX_IMAGE_SIDE and re-encodes as JPEG. exif_transpose bakes in
    a phone photo's orientation tag first — re-encoding drops the tag, so skipping
    this would hand the model a sideways receipt. An image Pillow can't decode is
    sent unchanged rather than failing the upload."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as original:
            img = ImageOps.exif_transpose(original)
            img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            if img.mode != "RGB":
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85, optimize=True)
    except OSError:
        return image_bytes, content_type
    return out.getvalue(), "image/jpeg"


_UNKNOWN_MERCHANT_PLACEHOLDERS = {"unknown", "n/a", "na", "none", "store", "merchant", "-"}


def _fold_merchant(description: str | None, merchant: str | None) -> str | None:
    """There's no merchant field downstream — the vision model still extracts it
    separately (helps it parse the receipt correctly), but it gets folded into the
    line item's description here rather than sent on its own. The prompt tells the
    model to return null rather than a placeholder when it can't read a merchant
    name, but this is a defensive backstop in case it still slips one through — a
    literal "Unknown" folded in looks like a real (wrong) merchant name."""
    description = (description or "").strip()
    merchant = (merchant or "").strip()
    if merchant.lower() in _UNKNOWN_MERCHANT_PLACEHOLDERS:
        merchant = ""
    if not merchant:
        return description or None
    if not description:
        return merchant
    if merchant.lower() in description.lower():
        return description
    return f"{description} - {merchant}"


async def _read_receipt(image_bytes: bytes, content_type: str, language: str) -> ReceiptExtraction:
    b64 = base64.b64encode(image_bytes).decode()
    language_name = SUPPORTED_LANGUAGES.get(language, "English")
    prompt = RECEIPT_EXTRACTION_PROMPT.replace("{language}", language_name).replace(
        "{today}", datetime.date.today().isoformat()
    )
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
        ]
    )
    response = await llm.vision_model().ainvoke(
        [message], config={"run_name": "receipt-vision", "tags": ["receipt-vision"]}
    )
    text = response.content if isinstance(response.content, str) else str(response.content)
    # Validated immediately after parsing so a malformed/off-spec vision response
    # raises a clear error here instead of an AttributeError several lines later.
    return ReceiptExtraction.model_validate(json.loads(text or "{}"))


def _majority_category(categories: list[str]) -> str:
    """Most common category across the receipt's items; a tie goes to whichever of
    the tied categories appears first on the receipt."""
    if not categories:
        return "other"
    counts = Counter(categories)
    top = max(counts.values())
    return next(c for c in categories if counts[c] == top)


def build_receipt_tools(http_client: Callable[[], httpx.AsyncClient], language: str) -> list[BaseTool]:
    @tool
    async def extract_receipt(object_name: str) -> dict:
        """Read an uploaded receipt, given in the user's message as '[uploaded
        receipt: <path>]' (pass that exact path), into one proposed transaction that
        the user confirms in a card below your reply; nothing is saved. If the result
        says not_a_receipt, ask the user to upload an actual receipt photo or PDF."""
        image_bytes, content_type = storage.read_bytes(object_name)

        if content_type == "application/pdf":
            image_bytes = _pdf_first_page_to_png(image_bytes)
            content_type = "image/png"
        elif content_type not in SUPPORTED_IMAGE_TYPES:
            return ToolError(
                error=(
                    f"That file is a {content_type}, which isn't supported. Please "
                    "upload the receipt as a photo/image (JPEG/PNG/WEBP/GIF) or a PDF."
                )
            ).model_dump()

        image_bytes, content_type = _shrink_for_vision(image_bytes, content_type)
        extracted = await _read_receipt(image_bytes, content_type, language)

        if not extracted.is_receipt or not extracted.total_paid:
            return NotAReceiptResult(
                message=(
                    "That doesn't look like a receipt — I couldn't find a purchase total "
                    "on it. Please upload a photo or PDF of an actual receipt."
                ),
            ).model_dump()

        currency = (extracted.currency or "USD").upper()
        receipt_uri = f"gs://{storage.BUCKET}/{object_name}"

        service_token = await _categorize_service_token()
        service_headers = {"X-Serverless-Authorization": f"Bearer {service_token}"} if service_token else {}

        # Every item is categorized (so past corrections and the categorizer's
        # definitions apply per product) in ONE batch call, then the receipt takes the
        # majority category. The merchant rides along with each name: "Nasi goreng -
        # Warung Jakarta" categorizes far better than a bare "Nasi goreng", and matches
        # how the saved description (and so the user's corrections) is worded.
        names = [
            _fold_merchant(n, extracted.merchant) or "" for n in (extracted.items or [extracted.description or ""])
        ][:100]
        categories: list[str] = []
        try:
            async with http_client() as c:
                resp = await c.post(
                    "/api/transactions/categorize/batch", json={"descriptions": names}, headers=service_headers
                )
            if resp.status_code == 200:
                categories = resp.json().get("categories", [])
        except httpx.HTTPError:
            pass
        category = _majority_category([c for c in categories if c])

        proposed = ReceiptProposedItem(
            occurred_on=extracted.occurred_on,
            type="expense",
            amount=extracted.total_paid,
            currency=currency,
            category=category,
            description=_fold_merchant(extracted.description, extracted.merchant),
            receipt_uri=receipt_uri,
        )
        return ReceiptProposedResult(items=[proposed], receipt_uri=receipt_uri).model_dump()

    return [extract_receipt]
