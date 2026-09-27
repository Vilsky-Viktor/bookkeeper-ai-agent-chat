"""Categorization as a subgraph: load the user's corrections, then classify (an exact
correction first, one model call for the rest — app/categorize.py). Shared: the
receipt workflow runs it as a node, and the assistant's add_transaction tool invokes
the same compiled graph."""

from typing import Callable

import httpx
from langgraph.graph import END, START, StateGraph

from .. import categorize as categorizer
from .state import CategorizeState


def build_categorize_graph(http_client: Callable[[], httpx.AsyncClient]):
    async def load_corrections(state: CategorizeState) -> CategorizeState:
        async with http_client() as c:
            return {"corrections": await categorizer.fetch_corrections(c)}

    async def classify(state: CategorizeState) -> CategorizeState:
        return {"categories": await categorizer.categorize(state["descriptions"], state.get("corrections", []))}

    graph = StateGraph(CategorizeState)
    graph.add_node("load_corrections", load_corrections)
    graph.add_node("classify", classify)
    graph.add_edge(START, "load_corrections")
    graph.add_edge("load_corrections", "classify")
    graph.add_edge("classify", END)

    return graph.compile(name="categorize")
