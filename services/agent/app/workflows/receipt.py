"""The receipt workflow: a deterministic subgraph — load the file, read it (vision),
categorize its items (the shared categorize subgraph), propose one transaction, and
report. No model decides the steps: they're fixed, so an agent would only add calls
and room for mistakes.

`report` publishes through custom events (streaming.py turns them into SSE): the
proposal card, a record of the result for the chat history, and — when the user
typed nothing else — the reply, as a notice key the web app shows translated. It
also adds the result to the conversation as an extract_receipt tool call, which is
what the assistant sees if it runs next."""

import asyncio
import datetime
import json
import uuid

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from ..helpers import images
from ..helpers.receipts import fold_merchant, majority_category
from ..models.notices import Notice
from ..models.tool_results import NotAReceiptResult, ReceiptProposedItem, ReceiptProposedResult, ToolError
from ..services import receipts
from ..storage import bucket
from .state import ReceiptState


def build_receipt_graph(categorize_graph, language: str, today: datetime.date):
    async def load(state: ReceiptState) -> ReceiptState:
        data, content_type = await asyncio.to_thread(bucket.read_bytes, state["receipt_object"])

        if content_type == "application/pdf":
            data, content_type = images.pdf_first_page_to_png(data), "image/png"
        elif content_type not in images.SUPPORTED_IMAGE_TYPES:
            error = (
                f"That file is a {content_type}, which isn't supported. Please upload the "
                "receipt as a photo/image (JPEG/PNG/WEBP/GIF) or a PDF."
            )

            return {"result": ToolError(error=error).model_dump()}
        data, content_type = images.shrink_for_vision(data, content_type)

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
        # The merchant rides along with each item name: "Fried rice - Corner Diner"
        # categorizes far better than a bare "Fried rice", and matches how the saved
        # description (and so the user's corrections) is worded.
        names = extraction.items or [extraction.description or ""]

        return {
            "extraction": extraction,
            "descriptions": [fold_merchant(n, extraction.merchant) or "" for n in names][:100],
        }

    async def propose(state: ReceiptState) -> ReceiptState:
        extraction = state["extraction"]
        receipt_uri = f"gs://{bucket.BUCKET}/{state['receipt_object']}"
        item = ReceiptProposedItem(
            occurred_on=extraction.occurred_on,
            type="expense",
            amount=extraction.total_paid,
            currency=(extraction.currency or "USD").upper(),
            category=majority_category(state.get("categories", [])),
            description=fold_merchant(extraction.description, extraction.merchant),
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
            await adispatch_custom_event("notice", notice_for(result, ui_event).model_dump(), config=config)

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


def notice_for(result: dict, ui_event: str | None) -> Notice:
    if ui_event == "receipt_proposed":
        date = (result.get("items") or [{}])[0].get("occurred_on") or ""

        return Notice(key="receiptProposed", params={"date": str(date)})

    if result.get("not_a_receipt"):
        return Notice(key="notAReceipt")

    return Notice(key="receiptUnreadable")
