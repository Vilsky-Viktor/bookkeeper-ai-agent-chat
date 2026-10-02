"""Reading a receipt image with the vision model, used by the receipt workflow
(workflows/receipt.py)."""

import base64
import datetime

from langchain_core.messages import HumanMessage

from ..constants.languages import SUPPORTED_LANGUAGES
from ..integrations import llm
from ..models.tool_results import ReceiptExtraction
from ..prompts.receipt import RECEIPT_EXTRACTION_PROMPT


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
    model = llm.vision_model().with_structured_output(ReceiptExtraction)
    extraction = await model.ainvoke([message], config={"run_name": "receipt-vision", "tags": ["receipt-vision"]})

    return ReceiptExtraction.model_validate(extraction)
