"""Image preparation for the vision model: PDF rendering and downscaling."""

import io

import pymupdf
from PIL import Image, ImageOps

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
