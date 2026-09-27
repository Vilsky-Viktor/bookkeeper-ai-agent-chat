from typing import Literal

from langgraph.graph import MessagesState


class ChatState(MessagesState):
    """The main graph's state: the conversation plus what the router needs."""

    receipt_object: str | None  # set when the message came with an uploaded receipt
    note: str  # what the user typed (empty for a bare upload)
    route: Literal["receipt", "assistant"]  # the router's decision, visible in traces
