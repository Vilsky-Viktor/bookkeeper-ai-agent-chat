"""A receipt upload with no typed text runs extract_receipt directly, without the chat
model: the outcome is fully determined (call the tool, reply with one fixed
sentence), so the two model calls a graph turn would make are pure cost. Uploads that
come with text still go through the graph, so instructions like "this was yesterday"
are honored."""

import uuid

from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from ..models.turns import ToolCallRecord, ToolResult, TurnState
from .streaming import sse

_REPLIES: dict[str, dict[str, str]] = {
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


def _reply(result: dict, ui_event: str | None, language: str) -> str:
    replies = _REPLIES.get(language, _REPLIES["en"])
    if ui_event == "receipt_proposed":
        date = (result.get("items") or [{}])[0].get("occurred_on") or ""
        return replies["proposed"].format(date=date)
    if result.get("not_a_receipt"):
        return replies["not_a_receipt"]
    return replies["error"]


async def run_receipt_turn(
    tools: list[BaseTool], object_name: str, language: str, run_config: RunnableConfig, state: TurnState
):
    """Yields the same SSE chunks a graph turn would, and records the same TurnState
    (one extract_receipt call, its result, the reply text), so finalize_turn persists
    it exactly like a model-driven receipt turn."""
    extract_receipt = next(t for t in tools if t.name == "extract_receipt")
    call_id = f"call_{uuid.uuid4().hex[:24]}"
    args = {"object_name": object_name}
    state.tool_calls_made.append(ToolCallRecord(id=call_id, name="extract_receipt", args=args))

    # No graph event stream here to count the vision call's tokens from, so collect
    # them directly — they're real spend against the user's token quota.
    with get_usage_metadata_callback() as usage:
        result = dict(await extract_receipt.ainvoke(args, config=run_config))
    state.total_tokens_used += sum(u.get("total_tokens", 0) for u in usage.usage_metadata.values())
    ui_event = result.pop("ui_event", None)
    state.tool_results.append(ToolResult(name="extract_receipt", tool_call_id=call_id, result=result))
    if ui_event == "receipt_proposed":
        yield sse(
            ui_event,
            {"type": "receipt_proposed", "items": result.get("items", []), "receipt_uri": result.get("receipt_uri")},
        )

    text = _reply(result, ui_event, language)
    state.assistant_text_parts.append(text)
    yield sse(None, {"type": "token", "text": text})
