"""Receipt reading, used by the receipt workflow (workflows/receipt.py): file
preparation (PDF render, downscaling), the vision-model call, merchant folding and the
majority category."""

import base64
import datetime
import io
import json
from collections import Counter

import pymupdf
from langchain_core.messages import HumanMessage
from PIL import Image, ImageOps

from . import llm
from .languages import SUPPORTED_LANGUAGES
from .models.tool_results import ReceiptExtraction
from .prompts.receipt import RECEIPT_EXTRACTION_PROMPT

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

PDF_RENDER_DPI = 200
# Long-side cap for what's sent to the vision model. Phone photos are often 4000px+
# and several MB of base64; OpenAI downsizes them anyway (to fit 2048px, then 768px
# on the short side), so the extra pixels only cost upload size and latency — and on
# patch-billed models (gpt-4.1 family) they cost tokens directly.
MAX_IMAGE_SIDE = 1600


def pdf_first_page_to_png(pdf_bytes: bytes) -> bytes:
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


def shrink_for_vision(image_bytes: bytes, content_type: str) -> tuple[bytes, str]:
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


UNKNOWN_MERCHANT_PLACEHOLDERS = {"unknown", "n/a", "na", "none", "store", "merchant", "-"}


def fold_merchant(description: str | None, merchant: str | None) -> str | None:
    """There's no merchant field downstream — the vision model still extracts it
    separately (helps it parse the receipt correctly), but it gets folded into the
    line item's description here rather than sent on its own. The prompt tells the
    model to return null rather than a placeholder when it can't read a merchant
    name, but this is a defensive backstop in case it still slips one through — a
    literal "Unknown" folded in looks like a real (wrong) merchant name."""
    description = (description or "").strip()
    merchant = (merchant or "").strip()
    if merchant.lower() in UNKNOWN_MERCHANT_PLACEHOLDERS:
        merchant = ""
    if not merchant:
        return description or None
    if not description:
        return merchant
    if merchant.lower() in description.lower():
        return description
    return f"{description} - {merchant}"


async def read_receipt(
    image_bytes: bytes, content_type: str, language: str, today: datetime.date | None = None, note: str = ""
) -> ReceiptExtraction:
    """`note` is what the user typed with the upload (e.g. "this was yesterday").
    Substituted last, so text in it can't fill the other placeholders."""
    b64 = base64.b64encode(image_bytes).decode()
    language_name = SUPPORTED_LANGUAGES.get(language, "English")
    prompt = (
        RECEIPT_EXTRACTION_PROMPT.replace("{language}", language_name)
        .replace("{today}", (today or datetime.date.today()).isoformat())
        .replace("{note}", note.strip() or "(none)")
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


def majority_category(categories: list[str]) -> str:
    """Most common category across the receipt's items; a tie goes to whichever of
    the tied categories appears first on the receipt."""
    if not categories:
        return "other"
    counts = Counter(categories)
    top = max(counts.values())
    return next(c for c in categories if counts[c] == top)
