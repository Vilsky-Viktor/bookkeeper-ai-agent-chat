"""LangGraph graph (architecture doc, Key design decisions: "LangGraph library inside
FastAPI", no LangGraph Server/Platform, no checkpointer — the graph runs once per HTTP
request and threads persist in the chat DB instead, see chat_db.py)."""

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from . import llm


def build_graph(tools: list[BaseTool]):
    model_with_tools = llm.primary_model().bind_tools(tools)
    fallback_with_tools = llm.fallback_model().bind_tools(tools)

    async def call_model(state: MessagesState, config: RunnableConfig):
        response = await llm.ainvoke_with_fallback(
            model_with_tools, fallback_with_tools, state["messages"], config=config
        )
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("call_model", call_model)
    graph.add_node("call_tools", ToolNode(tools))
    graph.add_edge(START, "call_model")
    graph.add_conditional_edges("call_model", tools_condition, {"tools": "call_tools", "__end__": END})
    graph.add_edge("call_tools", "call_model")
    return graph.compile()


def initial_state(messages: list[BaseMessage]) -> MessagesState:
    return {"messages": messages}
