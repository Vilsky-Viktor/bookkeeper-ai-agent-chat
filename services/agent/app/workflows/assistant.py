"""The bookkeeping assistant: a tool-calling agent (model <-> tools loop) over the
bookkeeping tools, with its own prompt (prompts/assistant.py, applied by
context.build_context)."""

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .. import llm
from ..tools.schema import compact_tool_schema


def build_assistant_graph(tools: list[BaseTool], name: str = "assistant", instructions: str | None = None):
    """`instructions` specialize this agent for its role on top of the shared prompt
    (e.g. receipt_followup's), added as a system message after the conversation."""
    schemas = [compact_tool_schema(t) for t in tools]
    model_with_tools = llm.primary_model().bind_tools(schemas)
    fallback_with_tools = llm.fallback_model().bind_tools(schemas)

    async def call_model(state: MessagesState, config: RunnableConfig):
        messages = state["messages"] + ([SystemMessage(content=instructions)] if instructions else [])
        response = await llm.ainvoke_with_fallback(model_with_tools, fallback_with_tools, messages, config=config)

        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("call_model", call_model)
    graph.add_node("call_tools", ToolNode(tools))
    graph.add_edge(START, "call_model")
    graph.add_conditional_edges("call_model", tools_condition, {"tools": "call_tools", "__end__": END})
    graph.add_edge("call_tools", "call_model")

    return graph.compile(name=name)
