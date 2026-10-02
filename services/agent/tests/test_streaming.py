"""chat/streaming.py: graph events to SSE."""

import json

from langchain_core.messages import AIMessageChunk

from app.chat import streaming
from app.models.turns import TurnState


class _FakeGraph:
    def __init__(self, events: list[dict]):
        self.events = events

    async def astream_events(self, inputs, config=None, version=None):
        for event in self.events:
            yield event


def _token(content) -> dict:
    return {
        "event": "on_chat_model_stream",
        "metadata": {"langgraph_node": "call_model"},
        "data": {"chunk": AIMessageChunk(content=content)},
    }


class TestTokens:
    async def test_streams_text_from_string_and_block_list_content(self):
        # Regression: with tools bound, gpt-6-luna replies through the Responses API,
        # whose chunks carry a list of content blocks; reading only string content
        # dropped every reply.
        graph = _FakeGraph([_token("Hi"), _token([{"type": "text", "text": " there", "index": 0}]), _token([])])
        state = TurnState()

        chunks = [c async for c in streaming.run_graph_turn(graph, {}, {}, state)]

        texts = [json.loads(c.decode().split("data: ")[1])["text"] for c in chunks]
        assert texts == ["Hi", " there"]
        assert "".join(state.assistant_text_parts) == "Hi there"
