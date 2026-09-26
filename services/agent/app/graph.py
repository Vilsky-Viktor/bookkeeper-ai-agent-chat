"""LangGraph graph (architecture doc, Key design decisions: "LangGraph library inside
FastAPI", no LangGraph Server/Platform, no checkpointer — the graph runs once per HTTP
request and threads persist in the chat DB instead, see chat_db.py)."""

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from . import llm


def _compact_tool_schema(tool: BaseTool) -> dict:
    """The schema sent to the model on EVERY call, so every token here is billed on
    every request. Collapses the docstring's indentation/newlines and rewrites each
    optional param's generated `anyOf: [{type: X}, {type: null}], default: null`
    as plain `type: X` — it's already optional by being absent from `required`.
    Execution still goes through the real tool (ToolNode), so validation is unchanged."""
    schema = convert_to_openai_tool(tool)
    fn = schema["function"]
    fn["description"] = " ".join(fn.get("description", "").split())
    for prop in fn.get("parameters", {}).get("properties", {}).values():
        non_null = [s for s in prop.get("anyOf", []) if s.get("type") != "null"]
        if len(non_null) == 1:
            del prop["anyOf"]
            prop.update(non_null[0])
        if "default" in prop and prop["default"] is None:
            del prop["default"]
    return schema


def build_graph(tools: list[BaseTool]):
    schemas = [_compact_tool_schema(t) for t in tools]
    model_with_tools = llm.primary_model().bind_tools(schemas)
    fallback_with_tools = llm.fallback_model().bind_tools(schemas)

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


def initial_state(messages: list[AnyMessage]) -> MessagesState:
    return {"messages": messages}
