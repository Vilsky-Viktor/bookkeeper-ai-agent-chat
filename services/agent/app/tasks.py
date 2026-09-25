"""Background work. TASKS_MODE=local runs the handler in-process via
asyncio.create_task (no Cloud Run CPU throttling to worry about locally); in
production this enqueues an HTTP task to the real Cloud Tasks queue instead, which
Cloud Tasks then POSTs back to this same service's /internal/summarize with a
signed OIDC token — service_auth.py's require_service_caller is what verifies that
token on the way back in, so its AUDIENCE must match what's minted here.
agent_base_url (this service's own origin, for the callback URL) comes from the
triggering request's Host header — see main.py's chat() — not an env var, since a
Cloud Run service can't reference its own computed URL from within its own
Terraform resource block."""

import asyncio
import json
import logging
import os

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2

from .service_auth import AUDIENCE

log = logging.getLogger("tasks")

_seen_task_names: set[str] = set()
_tasks_client: tasks_v2.CloudTasksClient | None = None


def _get_tasks_client() -> tasks_v2.CloudTasksClient:
    global _tasks_client
    if _tasks_client is None:
        _tasks_client = tasks_v2.CloudTasksClient()
    return _tasks_client


async def enqueue_summarize(uid: str, thread_id: str, through_seq: int, agent_base_url: str) -> None:
    # Cloud Tasks would carry {thread_id, through_seq}; we also pass uid so the local
    # handler can open an RLS-scoped connection without a caller JWT to derive it from.
    task_name = f"summarize-{thread_id}-{through_seq}"
    if task_name in _seen_task_names:
        return  # duplicate enqueue for the same range, rejected like Cloud Tasks would
    _seen_task_names.add(task_name)

    if os.getenv("TASKS_MODE") == "local":
        from .summarize import run_summarize

        async def _run():
            try:
                await run_summarize(uid, thread_id, through_seq)
            except Exception:
                log.exception("summarize task failed", extra={"thread_id": thread_id})
            finally:
                _seen_task_names.discard(task_name)

        asyncio.create_task(_run())
        return

    try:
        client = _get_tasks_client()
        parent = client.queue_path(
            os.environ["GOOGLE_CLOUD_PROJECT"],
            os.environ["CLOUD_TASKS_LOCATION"],
            os.environ["CLOUD_TASKS_QUEUE"],
        )
        task = tasks_v2.Task(
            # An explicit, deterministic name gives Cloud Tasks its own
            # cross-instance dedup (~1h window) — the _seen_task_names set above
            # only dedupes within this one running container.
            name=f"{parent}/tasks/{task_name}",
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=f"{agent_base_url}/internal/summarize",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"uid": uid, "thread_id": thread_id, "through_seq": through_seq}).encode(),
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=os.environ["TASKS_INVOKER_SERVICE_ACCOUNT"],
                    audience=AUDIENCE,
                ),
            ),
        )
        try:
            await asyncio.to_thread(client.create_task, parent=parent, task=task)
        except AlreadyExists:
            pass  # Cloud Tasks itself already has this exact task queued
    finally:
        _seen_task_names.discard(task_name)
