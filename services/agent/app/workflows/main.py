"""The main graph: a router hands each message to the right workflow.

    router ─┬─ receipt_workflow ─(user also typed something?)─┬─ receipt_followup
            │                                                 └─ END
            └─ assistant

receipt_followup is the assistant scoped for the turn after a receipt: confirm it and
answer what was asked, with read-only tools and its own instructions. The receipt is
saved only when the user confirms its card; with mutating tools in reach, the model
was seen saving it itself, then "editing" it.

A new capability is a new subgraph plus a routing rule here. The router is a plain
rule while the routes are unambiguous (an upload vs. anything else); a cheap model
call belongs here only once they aren't."""

import datetime

from langgraph.graph import END, START, StateGraph

from ..prompts.assistant import RECEIPT_FOLLOWUP_PROMPT
from ..tools import MUTATING_TOOLS, build_tools, transactions_client
from .assistant import build_assistant_graph
from .categorize import build_categorize_graph
from .receipt import build_receipt_graph
from .state import ChatState


def route(state: ChatState) -> dict:
    return {"route": "receipt" if state.get("receipt_object") else "assistant"}


def after_receipt(state: ChatState) -> str:
    # Anything typed with the upload ("this was yesterday — and how much did I spend
    # this week?") was already used as a note by the reader; the assistant also
    # answers it. A bare upload gets the workflow's fixed reply instead.
    return "receipt_followup" if state.get("note", "").strip() else END


def build_main_graph(jwt: str, language: str, today: datetime.date):
    """Built per request: the tools carry this user's JWT."""
    http_client = transactions_client(jwt)
    categorize_graph = build_categorize_graph(http_client)

    graph = StateGraph(ChatState)
    graph.add_node("router", route)
    graph.add_node("receipt_workflow", build_receipt_graph(categorize_graph, language, today))
    tools = build_tools(http_client, categorize_graph)
    graph.add_node("assistant", build_assistant_graph(tools))
    graph.add_node(
        "receipt_followup",
        build_assistant_graph(
            [t for t in tools if t.name not in MUTATING_TOOLS],
            name="receipt_followup",
            instructions=RECEIPT_FOLLOWUP_PROMPT,
        ),
    )
    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router", lambda s: s["route"], {"receipt": "receipt_workflow", "assistant": "assistant"}
    )
    graph.add_conditional_edges("receipt_workflow", after_receipt, ["receipt_followup", END])
    graph.add_edge("assistant", END)
    graph.add_edge("receipt_followup", END)
    return graph.compile(name="chat")
