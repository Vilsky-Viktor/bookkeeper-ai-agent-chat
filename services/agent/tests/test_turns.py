from unittest.mock import AsyncMock

from app.chat import turns
from app.models.turns import TurnState

_AGENT_BASE_URL = "https://agent.example.com"


def _thread_rows(roles: str, first_seq: int = 1, stride: int = 1) -> list[dict]:
    """Rows as finalize's count query returns them: newest first. roles is oldest-first,
    one letter per message (u=user, a=assistant, t=tool). stride > 1 mimics other
    threads' messages interleaving in the global seq counter."""
    rows = [
        {"seq": first_seq + i * stride, "role": {"u": "user", "a": "assistant", "t": "tool"}[r]}
        for i, r in enumerate(roles)
    ]
    return list(reversed(rows))


async def _finalize(conn, monkeypatch, rows, summarized_through=0, trimmed_before_seq=None) -> AsyncMock:
    conn.fetch.return_value = rows
    enqueue = AsyncMock()
    monkeypatch.setattr(turns.tasks, "enqueue_summarize", enqueue)
    thread = {"working_set": {}, "summarized_through": summarized_through}
    await turns.finalize_turn(
        "uid-1",
        "thread-1",
        thread,
        TurnState(),
        user_tokens=5,
        agent_base_url=_AGENT_BASE_URL,
        trimmed_before_seq=trimmed_before_seq,
    )
    return enqueue


class TestFinalizeTurnSummarizeTrigger:
    async def test_not_triggered_at_or_below_the_threshold(self, patch_chat_uid_conn, monkeypatch):
        enqueue = await _finalize(patch_chat_uid_conn, monkeypatch, _thread_rows("uat" * 8))  # 24 messages
        enqueue.assert_not_awaited()

    async def test_short_thread_is_not_summarized_however_busy_the_app_is(self, patch_chat_uid_conn, monkeypatch):
        # Regression: the old trigger subtracted global seq values, so a 6-message
        # thread in an app with thousands of messages looked "long" on every turn.
        enqueue = await _finalize(patch_chat_uid_conn, monkeypatch, _thread_rows("uatuat", first_seq=5000, stride=300))
        enqueue.assert_not_awaited()

    async def test_folds_all_but_the_recent_window_starting_on_a_user_message(self, patch_chat_uid_conn, monkeypatch):
        # 27 messages = 9 turns of user/assistant/tool (seq 1..27). The newest 12 are
        # seq 16..27, which starts on a user message (16 = 5*3+1), so fold through 15.
        enqueue = await _finalize(patch_chat_uid_conn, monkeypatch, _thread_rows("uat" * 9))
        enqueue.assert_awaited_once_with("uid-1", "thread-1", 15, _AGENT_BASE_URL)

    async def test_kept_window_extends_back_to_the_turn_start(self, patch_chat_uid_conn, monkeypatch):
        # 2-message turns followed by one 4-message turn: the 12th-newest message is
        # mid-turn, so the window grows until it starts on that turn's user message.
        roles = "ua" * 10 + "uatt" + "ua" * 4  # 32 messages
        rows = _thread_rows(roles)
        enqueue = await _finalize(patch_chat_uid_conn, monkeypatch, rows)
        (through,) = [c.args[2] for c in enqueue.await_args_list]
        kept = [r for r in rows if r["seq"] > through]
        assert len(kept) >= turns.KEEP_RECENT_MESSAGES
        assert kept[-1]["role"] == "user"  # oldest kept row (rows are newest-first)

    async def test_budget_trimmed_messages_are_folded_even_below_the_threshold(self, patch_chat_uid_conn, monkeypatch):
        enqueue = await _finalize(
            patch_chat_uid_conn,
            monkeypatch,
            _thread_rows("uat" * 4, first_seq=100),
            summarized_through=99,
            trimmed_before_seq=106,
        )
        enqueue.assert_awaited_once_with("uid-1", "thread-1", 105, _AGENT_BASE_URL)

    async def test_enqueue_failure_does_not_propagate(self, patch_chat_uid_conn, monkeypatch):
        # A failed background summarize enqueue (e.g. a misconfigured Cloud Tasks env
        # var) must not surface as the whole turn erroring out — the turn itself
        # already succeeded by the time this runs.
        patch_chat_uid_conn.fetch.return_value = _thread_rows("uat" * 9)
        monkeypatch.setattr(turns.tasks, "enqueue_summarize", AsyncMock(side_effect=RuntimeError("boom")))
        thread = {"working_set": {}, "summarized_through": 0}

        await turns.finalize_turn(
            "uid-1", "thread-1", thread, TurnState(), user_tokens=5, agent_base_url=_AGENT_BASE_URL
        )  # must not raise

        turns.tasks.enqueue_summarize.assert_awaited_once()
