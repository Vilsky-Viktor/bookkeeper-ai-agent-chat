"""The graphs' state types (workflows/)."""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages

from ..models.categorize import Correction
from ..models.tool_results import ReceiptExtraction


class ChatState(MessagesState):
    """The main graph's state: the conversation plus what the router needs."""

    receipt_object: str | None  # set when the message came with an uploaded receipt
    note: str  # what the user typed (empty for a bare upload)
    route: Literal["receipt", "assistant"]  # the router's decision, visible in traces


class CategorizeState(TypedDict, total=False):
    descriptions: list[str]  # input
    corrections: list[Correction]
    categories: list[str]  # output, one per description


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
