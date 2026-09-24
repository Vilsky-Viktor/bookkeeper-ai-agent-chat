from unittest.mock import AsyncMock, MagicMock

from app import llm as llm_module
from app import summarize


def _mock_model(reply_text: str):
    model = MagicMock()
    response = MagicMock()
    response.content = reply_text
    model.ainvoke = AsyncMock(return_value=response)
    return model


class TestRunSummarize:
    async def test_missing_thread_returns_without_side_effects(self, patch_chat_uid_conn, mock_conn, monkeypatch):
        mock_conn.fetchrow.return_value = None  # get_thread finds nothing
        mock_model = _mock_model("summary")
        monkeypatch.setattr(llm_module, "summary_model", lambda: mock_model)

        await summarize.run_summarize("uid-1", "thread-1", 10)

        mock_model.ainvoke.assert_not_awaited()
        mock_conn.execute.assert_not_awaited()

    async def test_already_summarized_through_is_a_noop(self, patch_chat_uid_conn, mock_conn, monkeypatch):
        mock_conn.fetchrow.return_value = {"summarized_through": 15, "summary": "old summary"}
        mock_model = _mock_model("summary")
        monkeypatch.setattr(llm_module, "summary_model", lambda: mock_model)

        await summarize.run_summarize("uid-1", "thread-1", 10)  # 10 <= already-applied 15

        mock_model.ainvoke.assert_not_awaited()

    async def test_no_new_rows_is_a_noop(self, patch_chat_uid_conn, mock_conn, monkeypatch):
        mock_conn.fetchrow.return_value = {"summarized_through": None, "summary": None}
        mock_conn.fetch.return_value = []
        mock_model = _mock_model("summary")
        monkeypatch.setattr(llm_module, "summary_model", lambda: mock_model)

        await summarize.run_summarize("uid-1", "thread-1", 10)

        mock_model.ainvoke.assert_not_awaited()

    async def test_success_folds_messages_and_updates_summary(self, patch_chat_uid_conn, mock_conn, monkeypatch):
        mock_conn.fetchrow.return_value = {"summarized_through": None, "summary": None}
        mock_conn.fetch.return_value = [
            {"seq": 1, "role": "user", "content": '{"text": "add coffee"}'},
            {
                "seq": 2,
                "role": "assistant",
                "content": '{"text": "added", "tool_calls": [{"name": "add_transaction"}]}',
            },
        ]
        mock_model = _mock_model("user added a coffee expense")
        monkeypatch.setattr(llm_module, "summary_model", lambda: mock_model)

        await summarize.run_summarize("uid-1", "thread-1", 2)

        mock_model.ainvoke.assert_awaited_once()
        mock_conn.execute.assert_awaited_once()
        args = mock_conn.execute.call_args.args
        assert args[1] == "user added a coffee expense"
        assert args[2] == 2

    async def test_rows_beyond_through_seq_are_excluded(self, patch_chat_uid_conn, mock_conn, monkeypatch):
        mock_conn.fetchrow.return_value = {"summarized_through": None, "summary": None}
        mock_conn.fetch.return_value = [
            {"seq": 1, "role": "user", "content": '{"text": "in range"}'},
            {"seq": 5, "role": "user", "content": '{"text": "out of range"}'},
        ]
        mock_model = _mock_model("summary")
        monkeypatch.setattr(llm_module, "summary_model", lambda: mock_model)

        await summarize.run_summarize("uid-1", "thread-1", through_seq=2)

        prompt = mock_model.ainvoke.call_args.args[0][0].content
        assert "in range" in prompt
        assert "out of range" not in prompt
