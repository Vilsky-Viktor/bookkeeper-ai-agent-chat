"""The receipt workflow: a deterministic subgraph — load the file, read it (vision),
categorize its items (the shared categorize subgraph), propose one transaction, and
report. No model decides the steps: they're fixed, so an agent would only add calls
and room for mistakes.

`report` publishes through custom events (streaming.py turns them into SSE): the
proposal card, a record of the result for the chat history, and — when the user
typed nothing else — the reply. It also adds the result to the conversation as an
extract_receipt tool call, which is what the assistant sees if it runs next."""

import asyncio
import datetime
import json
import uuid
from typing import Annotated, TypedDict

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .. import receipts, storage
from ..models.categorize import Correction
from ..models.tool_results import (
    NotAReceiptResult,
    ReceiptExtraction,
    ReceiptProposedItem,
    ReceiptProposedResult,
    ToolError,
)

REPLIES: dict[str, dict[str, str]] = {
    "en": {
        "proposed": "Extracted your receipt from {date} — you can edit or confirm it below.",
        "not_a_receipt": "That doesn't look like a receipt. Please upload a photo or PDF of an actual receipt.",
        "error": "I couldn't read that file. Please upload the receipt as a photo (JPEG, PNG, WEBP, GIF) or a PDF.",
    },
    "es": {
        "proposed": "He extraído tu recibo del {date}: puedes editarlo o confirmarlo abajo.",
        "not_a_receipt": "Eso no parece un recibo. Sube una foto o un PDF de un recibo real.",
        "error": "No pude leer ese archivo. Sube el recibo como foto (JPEG, PNG, WEBP, GIF) o PDF.",
    },
    "id": {
        "proposed": "Struk tanggal {date} sudah diekstrak — kamu bisa mengedit atau mengonfirmasinya di bawah.",
        "not_a_receipt": "Itu sepertinya bukan struk. Silakan unggah foto atau PDF struk yang asli.",
        "error": "File itu tidak bisa dibaca. Silakan unggah struk sebagai foto (JPEG, PNG, WEBP, GIF) atau PDF.",
    },
    "fr": {
        "proposed": "J'ai extrait votre reçu du {date} — vous pouvez le modifier ou le confirmer ci-dessous.",
        "not_a_receipt": "Cela ne ressemble pas à un reçu. Veuillez envoyer une photo ou un PDF d'un vrai reçu.",
        "error": "Je n'ai pas pu lire ce fichier. Envoyez le reçu en photo (JPEG, PNG, WEBP, GIF) ou en PDF.",
    },
    "de": {
        "proposed": "Dein Beleg vom {date} wurde ausgelesen — du kannst ihn unten bearbeiten oder bestätigen.",
        "not_a_receipt": "Das sieht nicht wie ein Beleg aus. Bitte lade ein Foto oder PDF eines echten Belegs hoch.",
        "error": "Ich konnte die Datei nicht lesen. Bitte lade den Beleg als Foto (JPEG, PNG, WEBP, GIF) oder PDF hoch.",
    },
    "pt": {
        "proposed": "Extraí seu recibo de {date} — você pode editá-lo ou confirmá-lo abaixo.",
        "not_a_receipt": "Isso não parece um recibo. Envie uma foto ou PDF de um recibo de verdade.",
        "error": "Não consegui ler esse arquivo. Envie o recibo como foto (JPEG, PNG, WEBP, GIF) ou PDF.",
    },
    "he": {
        "proposed": "חילצתי את הקבלה מתאריך {date} — אפשר לערוך או לאשר אותה למטה.",
        "not_a_receipt": "זה לא נראה כמו קבלה. אנא העלה תמונה או PDF של קבלה אמיתית.",
        "error": "לא הצלחתי לקרוא את הקובץ. אנא העלה את הקבלה כתמונה (JPEG, PNG, WEBP, GIF) או כ-PDF.",
    },
    "ru": {
        "proposed": "Чек от {date} распознан — его можно отредактировать или подтвердить ниже.",
        "not_a_receipt": "Это не похоже на чек. Загрузите фото или PDF настоящего чека.",
        "error": "Не удалось прочитать файл. Загрузите чек как фото (JPEG, PNG, WEBP, GIF) или PDF.",
    },
    "uk": {
        "proposed": "Чек від {date} розпізнано — його можна відредагувати або підтвердити нижче.",
        "not_a_receipt": "Це не схоже на чек. Завантажте фото або PDF справжнього чека.",
        "error": "Не вдалося прочитати файл. Завантажте чек як фото (JPEG, PNG, WEBP, GIF) або PDF.",
    },
    "ar": {
        "proposed": "تم استخراج إيصالك بتاريخ {date} — يمكنك تعديله أو تأكيده أدناه.",
        "not_a_receipt": "لا يبدو هذا إيصالًا. يرجى تحميل صورة أو ملف PDF لإيصال حقيقي.",
        "error": "تعذّرت قراءة هذا الملف. يرجى تحميل الإيصال كصورة (JPEG أو PNG أو WEBP أو GIF) أو PDF.",
    },
}


class ReceiptState(TypedDict, total=False):
    receipt_object: str  # input
    note: str  # input: what the user typed with the upload
    messages: Annotated[list[AnyMessage], add_messages]  # shared with the main graph
    image: bytes
    content_type: str
    extraction: ReceiptExtraction
    descriptions: list[str]  # for the categorize subgraph
    corrections: list[Correction]
    categories: list[str]
    result: dict  # what gets reported: a proposal, not_a_receipt, or an error


def build_receipt_graph(categorize_graph, language: str, today: datetime.date):
    async def load(state: ReceiptState) -> ReceiptState:
        data, content_type = await asyncio.to_thread(storage.read_bytes, state["receipt_object"])
        if content_type == "application/pdf":
            data, content_type = receipts.pdf_first_page_to_png(data), "image/png"
        elif content_type not in receipts.SUPPORTED_IMAGE_TYPES:
            error = (
                f"That file is a {content_type}, which isn't supported. Please upload the "
                "receipt as a photo/image (JPEG/PNG/WEBP/GIF) or a PDF."
            )
            return {"result": ToolError(error=error).model_dump()}
        data, content_type = receipts.shrink_for_vision(data, content_type)
        return {"image": data, "content_type": content_type}

    async def read(state: ReceiptState) -> ReceiptState:
        extraction = await receipts.read_receipt(
            state["image"], state["content_type"], language, today, state.get("note", "")
        )
        if not extraction.is_receipt or not extraction.total_paid:
            message = (
                "That doesn't look like a receipt — I couldn't find a purchase total on it. "
                "Please upload a photo or PDF of an actual receipt."
            )
            return {"result": NotAReceiptResult(message=message).model_dump()}
        # The merchant rides along with each item name: "Nasi goreng - Warung Jakarta"
        # categorizes far better than a bare "Nasi goreng", and matches how the saved
        # description (and so the user's corrections) is worded.
        names = extraction.items or [extraction.description or ""]
        return {
            "extraction": extraction,
            "descriptions": [receipts.fold_merchant(n, extraction.merchant) or "" for n in names][:100],
        }

    async def propose(state: ReceiptState) -> ReceiptState:
        extraction = state["extraction"]
        receipt_uri = f"gs://{storage.BUCKET}/{state['receipt_object']}"
        item = ReceiptProposedItem(
            occurred_on=extraction.occurred_on,
            type="expense",
            amount=extraction.total_paid,
            currency=(extraction.currency or "USD").upper(),
            category=receipts.majority_category(state.get("categories", [])),
            description=receipts.fold_merchant(extraction.description, extraction.merchant),
            receipt_uri=receipt_uri,
        )
        return {"result": ReceiptProposedResult(items=[item], receipt_uri=receipt_uri).model_dump()}

    async def report(state: ReceiptState, config: RunnableConfig) -> ReceiptState:
        result = dict(state["result"])
        ui_event = result.pop("ui_event", None)
        call_id = f"call_{uuid.uuid4().hex[:24]}"
        args = {"object_name": state["receipt_object"]}
        if ui_event == "receipt_proposed":
            card = {"type": ui_event, "items": result["items"], "receipt_uri": result["receipt_uri"]}
            await adispatch_custom_event("ui_event", {"event": ui_event, "payload": card}, config=config)
        record = {"id": call_id, "name": "extract_receipt", "args": args, "result": result}
        await adispatch_custom_event("tool_record", record, config=config)
        if not state.get("note", "").strip():
            await adispatch_custom_event("reply", {"text": reply_text(result, ui_event, language)}, config=config)
        return {
            "messages": [
                AIMessage(content="", tool_calls=[{"id": call_id, "name": "extract_receipt", "args": args}]),
                ToolMessage(content=json.dumps(result), tool_call_id=call_id, name="extract_receipt"),
            ]
        }

    def next_after(step: str):
        return lambda state: "report" if "result" in state else step

    graph = StateGraph(ReceiptState)
    graph.add_node("load", load)
    graph.add_node("read", read)
    graph.add_node("categorize", categorize_graph)
    graph.add_node("propose", propose)
    graph.add_node("report", report)
    graph.add_edge(START, "load")
    graph.add_conditional_edges("load", next_after("read"), ["read", "report"])
    graph.add_conditional_edges("read", next_after("categorize"), ["categorize", "report"])
    graph.add_edge("categorize", "propose")
    graph.add_edge("propose", "report")
    graph.add_edge("report", END)
    return graph.compile(name="receipt_workflow")


def reply_text(result: dict, ui_event: str | None, language: str) -> str:
    replies = REPLIES.get(language, REPLIES["en"])
    if ui_event == "receipt_proposed":
        date = (result.get("items") or [{}])[0].get("occurred_on") or ""
        return replies["proposed"].format(date=date)
    if result.get("not_a_receipt"):
        return replies["not_a_receipt"]
    return replies["error"]
