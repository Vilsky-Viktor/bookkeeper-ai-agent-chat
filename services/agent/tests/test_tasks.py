import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.api_core.exceptions import AlreadyExists

from app import tasks as tasks_module

_QUEUE_PATH = "projects/demo-project/locations/us-central1/queues/prod-summarize"


@pytest.fixture(autouse=True)
def _clear_seen_task_names():
    tasks_module._seen_task_names.clear()
    yield
    tasks_module._seen_task_names.clear()


@pytest.fixture
def cloud_tasks_env(monkeypatch):
    monkeypatch.setenv("TASKS_MODE", "cloud")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("CLOUD_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("CLOUD_TASKS_QUEUE", "prod-summarize")
    monkeypatch.setenv("AGENT_URL", "https://agent.example.com")
    monkeypatch.setenv("TASKS_INVOKER_SERVICE_ACCOUNT", "tasks-invoker@demo-project.iam.gserviceaccount.com")


@pytest.fixture
def mock_tasks_client(monkeypatch):
    client = MagicMock()
    client.queue_path.return_value = _QUEUE_PATH
    monkeypatch.setattr(tasks_module, "_get_tasks_client", lambda: client)
    return client


class TestEnqueueSummarizeLocal:
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


class TestEnqueueSummarizeCloudTasks:
    async def test_creates_a_task_targeting_internal_summarize(self, cloud_tasks_env, mock_tasks_client):
        await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)

        mock_tasks_client.create_task.assert_called_once()
        kwargs = mock_tasks_client.create_task.call_args.kwargs
        assert kwargs["parent"] == _QUEUE_PATH

        task = kwargs["task"]
        assert task.name == f"{_QUEUE_PATH}/tasks/summarize-thread-1-10"
        assert task.http_request.url == "https://agent.example.com/internal/summarize"
        assert json.loads(task.http_request.body) == {"uid": "uid-1", "thread_id": "thread-1", "through_seq": 10}

    async def test_oidc_token_matches_service_auths_expectations(self, cloud_tasks_env, mock_tasks_client):
        # The whole point: service_auth.py's require_service_caller must accept
        # exactly what gets minted here, or the callback 403s.
        await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)

        oidc = mock_tasks_client.create_task.call_args.kwargs["task"].http_request.oidc_token
        assert oidc.service_account_email == "tasks-invoker@demo-project.iam.gserviceaccount.com"
        assert oidc.audience == tasks_module.AUDIENCE

    async def test_duplicate_task_name_from_cloud_tasks_itself_is_swallowed(self, cloud_tasks_env, mock_tasks_client):
        mock_tasks_client.create_task.side_effect = AlreadyExists("task already exists")

        await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)  # must not raise

    async def test_truly_concurrent_duplicate_calls_only_reach_cloud_tasks_once(
        self, cloud_tasks_env, mock_tasks_client
    ):
        # _seen_task_names is added to synchronously before the (awaited) Cloud Tasks
        # call, so two calls racing *before either resolves* dedupe in-process —
        # unlike two sequential calls, which both legitimately reach Cloud Tasks and
        # rely on its own server-side, cross-instance dedup instead (see
        # test_duplicate_task_name_from_cloud_tasks_itself_is_swallowed above) —
        # this only protects the narrower "still in flight" case.
        await asyncio.gather(
            tasks_module.enqueue_summarize("uid-1", "thread-1", 10),
            tasks_module.enqueue_summarize("uid-1", "thread-1", 10),
        )

        mock_tasks_client.create_task.assert_called_once()

    async def test_sequential_duplicate_calls_both_reach_cloud_tasks(self, cloud_tasks_env, mock_tasks_client):
        # Once the first call has fully resolved, its name is no longer tracked as
        # "in flight" — a second, later call for the same range legitimately hits
        # Cloud Tasks again, which is where the real (server-side) dedup lives.
        await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)
        await tasks_module.enqueue_summarize("uid-1", "thread-1", 10)

        assert mock_tasks_client.create_task.call_count == 2
