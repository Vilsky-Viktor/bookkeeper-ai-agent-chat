"""The compact tool schema the chat model gets (workflows/assistant.py)."""

from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool


def compact_tool_schema(tool: BaseTool) -> dict:
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
