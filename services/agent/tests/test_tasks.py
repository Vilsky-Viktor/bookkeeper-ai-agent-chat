import asyncio
from unittest.mock import AsyncMock

import pytest

from app import tasks as tasks_module


@pytest.fixture(autouse=True)
def _clear_seen_task_names():
    tasks_module._seen_task_names.clear()
    yield
    tasks_module._seen_task_names.clear()


class TestEnqueueSummarize:
    async def test_local_mode_schedules_the_handler(self, monkeypatch):
        monkeypatch.setenv("TASKS_MODE", "local")
        mock_run = AsyncMock()
        monkeypatch.setattr("app.summarize.run_summarize", mock_run)

        await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)
        await asyncio.sleep(0)  # let the scheduled background task run

        mock_run.assert_awaited_once_with("uid-1", "thread-1", 10)

    async def test_duplicate_enqueue_for_same_range_is_skipped(self, monkeypatch):
        monkeypatch.setenv("TASKS_MODE", "local")
        mock_run = AsyncMock()
        monkeypatch.setattr("app.summarize.run_summarize", mock_run)

        await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)
        await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)  # same task_name, skipped synchronously
        await asyncio.sleep(0)

        mock_run.assert_awaited_once()

    async def test_different_through_seq_is_not_deduped(self, monkeypatch):
        monkeypatch.setenv("TASKS_MODE", "local")
        mock_run = AsyncMock()
        monkeypatch.setattr("app.summarize.run_summarize", mock_run)

        await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)
        await tasks_module.enqueue_summarize("uid-1", "thread-1", 20)
        await asyncio.sleep(0)

        assert mock_run.await_count == 2

    async def test_non_local_mode_raises_not_implemented(self, monkeypatch):
        monkeypatch.setenv("TASKS_MODE", "cloud")
        with pytest.raises(NotImplementedError):
            await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)
