from unittest.mock import AsyncMock

from app.chat import turns
from app.models.turns import TurnState

_AGENT_BASE_URL = "https://agent.example.com"


class TestFinalizeTurnSummarizeTrigger:
    async def test_enqueue_failure_does_not_propagate(self, patch_chat_uid_conn, monkeypatch):
        # A failed background summarize enqueue (e.g. a misconfigured Cloud Tasks env
        # var) must not surface as the whole turn erroring out — the turn itself
        # already succeeded by the time this runs.
        patch_chat_uid_conn.fetchrow.return_value = {"max_seq": 100}  # well past RECENT_MESSAGE_LIMIT (40)
        monkeypatch.setattr(turns.tasks, "enqueue_summarize", AsyncMock(side_effect=RuntimeError("boom")))

        thread = {"working_set": {}, "summarized_through": 0}
        state = TurnState()

        await turns.finalize_turn(
            "uid-1", "thread-1", thread, state, user_tokens=5, agent_base_url=_AGENT_BASE_URL
        )  # must not raise

        turns.tasks.enqueue_summarize.assert_awaited_once_with("uid-1", "thread-1", 60, _AGENT_BASE_URL)

    async def test_not_triggered_below_the_limit(self, patch_chat_uid_conn, monkeypatch):
        patch_chat_uid_conn.fetchrow.return_value = {"max_seq": 10}  # well under RECENT_MESSAGE_LIMIT (40)
        mock_enqueue = AsyncMock()
        monkeypatch.setattr(turns.tasks, "enqueue_summarize", mock_enqueue)

        thread = {"working_set": {}, "summarized_through": 0}
        state = TurnState()

        await turns.finalize_turn("uid-1", "thread-1", thread, state, user_tokens=5, agent_base_url=_AGENT_BASE_URL)

        mock_enqueue.assert_not_awaited()
