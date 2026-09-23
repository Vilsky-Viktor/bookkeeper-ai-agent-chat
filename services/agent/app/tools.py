"""Tools the agent calls (architecture doc, Agent service > Tool table, p. 7). Every
tool forwards the user's JWT to the transactions service — the agent never asserts
"act as uid X" with its own identity. Built per-request via build_tools() so each
closure carries this turn's JWT/X-Client-Id without leaking across requests."""

import base64
import json
import os
from typing import Annotated, Optional

import httpx
import pymupdf
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from openai import AsyncOpenAI

from . import storage
from .languages import SUPPORTED_LANGUAGES

TRANSACTIONS_URL = os.environ["TRANSACTIONS_URL"]

_vision_client = AsyncOpenAI(api_key=os.environ["LLM_API_KEY"])

RECEIPT_EXTRACTION_PROMPT = """First decide whether this image/document is actually a \
purchase receipt, invoice, or similar proof-of-purchase listing items and prices — \
not an unrelated photo, screenshot, or document.

If it is NOT a receipt, reply with JSON only, no prose:
{"is_receipt": false}

If it IS a receipt, extract every line item and reply with JSON only, no prose, in \
exactly this shape:
{"is_receipt": true, "merchant": "string", "occurred_on": "YYYY-MM-DD",
 "currency": "3-letter ISO 4217 code", "items": [{"description": "string", "amount": "12.50"}]}
Use your best guess for any field you can't read exactly. amount is a decimal string \
matching the currency's usual precision. Write "merchant" and every item's "description" \
in {language} — if the receipt itself is in a different language, translate that text \
into {language}; only the merchant/item text is translated, the currency code, amount \
and date stay exactly as read."""


SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PDF_RENDER_DPI = 200


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


FRANKFURTER_URL = "https://api.frankfurter.app/latest"


def _fold_merchant(description: str | None, merchant: str | None) -> str | None:
    """There's no merchant field downstream — the vision model still extracts it
    separately (helps it parse the receipt correctly), but it gets folded into the
    line item's description here rather than sent on its own."""
    description = (description or "").strip()
    merchant = (merchant or "").strip()
    if not merchant:
        return description or None
    if not description:
        return merchant
    if merchant.lower() in description.lower():
        return description
    return f"{description} - {merchant}"


async def _extract_line_items(image_bytes: bytes, content_type: str, language: str) -> dict:
    b64 = base64.b64encode(image_bytes).decode()
    language_name = SUPPORTED_LANGUAGES.get(language, "English")
    resp = await _vision_client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-4o"),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": RECEIPT_EXTRACTION_PROMPT.format(language=language_name)},
                    {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
                ],
            }
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content or "{}")


def build_tools(jwt: str, x_client_id: str | None, language: str = "en") -> list[BaseTool]:
    headers = {"Authorization": f"Bearer {jwt}"}
    if x_client_id:
        headers["X-Client-Id"] = x_client_id

    def http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=TRANSACTIONS_URL, headers=headers, timeout=30)

    @tool
    async def add_transaction(
        occurred_on: str,
        type: str,
        amount: str,
        currency: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        description: Optional[str] = None,
    ) -> dict:
        """Add one transaction (expense or income). occurred_on is YYYY-MM-DD, amount
        is a decimal string like '12.50', currency is a 3-letter ISO 4217 code, type is
        'expense' or 'income'. Ask a clarifying question first if amount or currency is
        missing from the user's request. There is no category argument: the
        transactions service categorizes every row itself (past corrections first,
        then its own model), so pass description and let it decide.
        description should be a short, complete, human-readable phrase covering what it
        was for, including the merchant/vendor/service name whenever one is
        identifiable — not just the bare item name. E.g. for "I spent 5000 IDR for
        indomie in Indomart", set description to "indomie purchased in Indomart", not
        just "indomie"; for a subscription with no physical store, still name it, e.g.
        "Claude subscription payment". Corrections are matched against this exact text
        (loosely, via near-duplicate matching), so use the SAME short, consistent
        wording for the same recurring purchase every time (e.g. always "Claude
        subscription payment", never alternating with "Anthropic Claude payment") —
        inconsistent wording across separate adds makes past corrections less likely
        to reapply."""
        async with http_client() as c:
            resp = await c.post(
                "/api/transactions/transactions",
                json={
                    "transactions": [
                        {
                            "occurred_on": occurred_on, "type": type, "amount": amount,
                            "currency": currency, "description": description,
                        }
                    ]
                },
                headers={"Idempotency-Key": tool_call_id},
            )
        resp.raise_for_status()
        return {"ui_event": "table_changed", **resp.json()["items"][0]}

    @tool
    async def edit_transaction(
        transaction_id: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        occurred_on: Optional[str] = None,
        type: Optional[str] = None,
        amount: Optional[str] = None,
        currency: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Edit fields on an existing transaction, identified by transaction_id.
        Resolve "that one" / "the coffee one" from recently referenced transactions or
        a prior query_transactions call — or from a "[transaction: <id>]" marker in the
        message, which takes priority when present. If the reference isn't something
        you've already seen this conversation, call query_transactions with
        description set to a distinctive word from what the user said (e.g. "bagel")
        to search the whole table before asking the user which one they mean. Only
        pass fields that change. If you set
        description, keep it a complete, human-readable phrase with context including
        the merchant/vendor name when relevant (e.g. "indomie purchased in Indomart"),
        not just an item name."""
        body = {
            k: v
            for k, v in {
                "occurred_on": occurred_on, "type": type, "amount": amount, "currency": currency,
                "category": category, "description": description,
            }.items()
            if v is not None
        }
        async with http_client() as c:
            resp = await c.patch(
                f"/api/transactions/transactions/{transaction_id}",
                json=body,
                headers={"Idempotency-Key": tool_call_id},
            )
        if resp.status_code == 404:
            return {"error": "transaction not found"}
        resp.raise_for_status()
        return {"ui_event": "table_changed", **resp.json()}

    @tool
    async def delete_transaction(
        transaction_id: str, tool_call_id: Annotated[str, InjectedToolCallId]
    ) -> dict:
        """Delete ONE transaction by id. For deleting more than one — "delete all",
        "clear the table", "remove my Starbucks purchases" — use
        delete_transactions_matching instead; it deletes in a single server-side
        operation instead of one id at a time. query_transactions only ever returns
        one page of results (up to 50), so looping delete_transaction over its output
        silently misses everything past the first page. "The last transaction"/"most
        recent" means current table state — resolve it with a fresh query_transactions
        call (newest-first) right before this, don't reuse an id from earlier in the
        conversation. If this returns an error, that transaction was NOT deleted — say
        so, don't report success anyway."""
        async with http_client() as c:
            resp = await c.delete(
                f"/api/transactions/transactions/{transaction_id}",
                headers={"Idempotency-Key": tool_call_id},
            )
        if resp.status_code == 404:
            return {"error": "transaction not found"}
        resp.raise_for_status()
        return {"ui_event": "table_changed", **resp.json()}

    @tool
    async def delete_transactions_matching(
        tool_call_id: Annotated[str, InjectedToolCallId],
        currency: Optional[str] = None,
        category: Optional[str] = None,
        type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_amount: Optional[str] = None,
        max_amount: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Delete every transaction matching these filters (same filters as
        query_transactions) in one operation — pass no filters to delete ALL of the
        user's transactions. This is irreversible: always confirm with the user
        exactly what will be deleted (and roughly how many, via query_transactions if
        unsure) before calling this. This is the right tool for "delete all my
        transactions", "clear the table", or deleting more than one transaction at
        once — never loop delete_transaction over query_transactions results, since
        that only sees one page and would leave the rest behind."""
        params = {
            k: v
            for k, v in {
                "currency": currency, "category": category, "type": type,
                "from": from_date, "to": to_date, "min_amount": min_amount, "max_amount": max_amount,
                "description": description,
            }.items()
            if v is not None
        }
        async with http_client() as c:
            resp = await c.delete(
                "/api/transactions/transactions",
                params=params,
                headers={"Idempotency-Key": tool_call_id},
            )
        resp.raise_for_status()
        return {"ui_event": "table_changed", **resp.json()}

    @tool
    async def query_transactions(
        currency: Optional[str] = None,
        category: Optional[str] = None,
        type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_amount: Optional[str] = None,
        max_amount: Optional[str] = None,
        description: Optional[str] = None,
        aggregate: bool = False,
    ) -> dict:
        """List transactions matching filters, or (aggregate=true) sums by category and
        month per currency. Use aggregate=true for analysis or savings questions — never
        state a total from memory or from the conversation summary, always call this.
        description is a case-insensitive substring match against the transaction's
        description — use it to resolve a vague reference ("the bagel one", "that
        Starbucks purchase") against the whole table, not just transactions already
        mentioned earlier in this conversation; try a short, distinctive word from
        what the user said (e.g. "bagel"), not the full phrase."""
        params = {
            k: v
            for k, v in {
                "currency": currency, "category": category, "type": type,
                "from": from_date, "to": to_date, "min_amount": min_amount, "max_amount": max_amount,
                "description": description,
            }.items()
            if v is not None
        }
        path = "/api/transactions/aggregates" if aggregate else "/api/transactions/transactions"
        async with http_client() as c:
            resp = await c.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    @tool
    async def get_exchange_rate(from_currency: str, to_currency: str) -> dict:
        """Look up the current exchange rate between two currencies (e.g. "what's the
        exchange rate from USD to EUR", "how much is 50 USD in IDR") — daily reference
        rates from the European Central Bank via Frankfurter.app, free, no API key.
        This is a daily rate, not tick-by-tick live market data, and it's for the
        user's reference only: never use it to silently convert or alter a
        transaction's actual stated amount/currency — record what the user said
        exactly. currencies are 3-letter ISO codes."""
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.get(
                    FRANKFURTER_URL, params={"from": from_currency, "to": to_currency}, follow_redirects=True
                )
            resp.raise_for_status()
            data = resp.json()
            rate = data["rates"][to_currency]
        except (httpx.HTTPError, KeyError):
            return {"error": f"Couldn't find an exchange rate for {from_currency} to {to_currency} right now."}
        return {
            "from": from_currency, "to": to_currency, "rate": rate, "date": data.get("date"),
            "note": "European Central Bank daily reference rate, not real-time.",
        }

    @tool
    def set_filter(
        currency: Optional[str] = None,
        category: Optional[str] = None,
        type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_amount: Optional[str] = None,
        max_amount: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Set the transactions table's filter in the UI (e.g. "show USD expenses over
        100 from last month", "show transactions with 'bagel' in the description").
        description is a case-insensitive substring match. Calls nothing downstream —
        the UI re-queries with this filter itself. To clear the filter (e.g. "clear
        the filter", "reset"), call this with every argument left unset — you must
        still call it; replying that the filter is cleared without calling this tool
        does nothing. Clearing resets the table to its default view, the current
        calendar month — not to every transaction ever, so don't tell the user it now
        shows "everything"/"all transactions"; say it's back to showing this month."""
        filt = {
            k: v
            for k, v in {
                "currency": currency, "category": category, "type": type,
                "from": from_date, "to": to_date, "min_amount": min_amount, "max_amount": max_amount,
                "description": description,
            }.items()
            if v is not None
        }
        return {"ui_event": "filter_set", "filter": filt}

    @tool
    def export_transactions() -> dict:
        """Export the transactions table's current view to a CSV file (e.g. "export
        transactions", "export this view", "download as csv"). You MUST call this
        tool for every such request, even if you exported earlier in this
        conversation — there is no file until you call it THIS turn; saying you've
        exported without calling it produces no file at all and misleads the user.
        Takes no arguments — it always exports exactly what the table is currently
        filtered to, not a filter you construct; if the user wants a different filter
        exported, call set_filter first, then this. Does nothing itself — the UI
        builds the CSV and attaches it to your reply as a clickable file; it is NOT
        downloaded automatically. Your reply's last sentence must say exactly "You can
        download it by clicking the file below." — use that exact wording, don't
        paraphrase it, and don't say it's been downloaded or saved anywhere, since
        nothing happens until they click it."""
        return {"ui_event": "export_ready"}

    @tool
    async def extract_receipt(object_name: str) -> dict:
        """Extract line items from an uploaded receipt, image or PDF. object_name looks
        like receipts/<uid>/<id>.jpg and is given to you in the user's message as
        '[uploaded receipt: <path>]' — use that exact path. Categorizes each item but
        NEVER writes to the table; the UI shows proposed rows for the user to edit and
        confirm before anything is saved. If the result says not_a_receipt, tell the
        user plainly that the file doesn't look like a receipt and ask them to upload
        an actual receipt (photo or PDF) — don't imply anything was saved or proposed."""
        image_bytes, content_type = storage.read_bytes(object_name)

        if content_type == "application/pdf":
            image_bytes = _pdf_first_page_to_png(image_bytes)
            content_type = "image/png"
        elif content_type not in SUPPORTED_IMAGE_TYPES:
            return {
                "error": (
                    f"That file is a {content_type}, which isn't supported. Please "
                    "upload the receipt as a photo/image (JPEG/PNG/WEBP/GIF) or a PDF."
                )
            }

        extracted = await _extract_line_items(image_bytes, content_type, language)

        if not extracted.get("is_receipt", True) or not extracted.get("items"):
            return {
                "not_a_receipt": True,
                "message": (
                    "That doesn't look like a receipt — I couldn't find any purchase "
                    "line items on it. Please upload a photo or PDF of an actual "
                    "receipt."
                ),
            }

        merchant = extracted.get("merchant")
        occurred_on = extracted.get("occurred_on")
        currency = (extracted.get("currency") or "USD").upper()

        proposed = []
        async with http_client() as c:
            for item in extracted.get("items", []):
                description = _fold_merchant(item.get("description"), merchant)
                category = "other"
                try:
                    cat_resp = await c.post(
                        "/api/transactions/categorize",
                        json={
                            "description": description,
                            "amount": item.get("amount", "0"), "currency": currency, "type": "expense",
                        },
                    )
                    if cat_resp.status_code == 200:
                        category = cat_resp.json().get("category", "other")
                except httpx.HTTPError:
                    pass
                proposed.append(
                    {
                        "occurred_on": occurred_on, "type": "expense", "amount": item.get("amount"),
                        "currency": currency, "category": category,
                        "description": description,
                        "receipt_uri": f"gs://{storage.BUCKET}/{object_name}",
                    }
                )
        return {"ui_event": "receipt_proposed", "items": proposed, "receipt_uri": f"gs://{storage.BUCKET}/{object_name}"}

    return [
        add_transaction, edit_transaction, delete_transaction, delete_transactions_matching,
        query_transactions, get_exchange_rate, set_filter, export_transactions, extract_receipt,
    ]
