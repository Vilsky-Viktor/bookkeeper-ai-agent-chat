"""Background work. TASKS_MODE=local runs the handler in-process via
asyncio.create_task (no Cloud Run CPU throttling to worry about locally); in production
this enqueues to the Cloud Tasks summarize queue instead."""

import logging
import os

log = logging.getLogger("tasks")

_seen_task_names: set[str] = set()


async def enqueue_summarize(uid: str, thread_id: str, through_seq: int) -> None:
    # Cloud Tasks would carry {thread_id, through_seq}; we also pass uid so the local
    # handler can open an RLS-scoped connection without a caller JWT to derive it from.
    task_name = f"summarize-{thread_id}-{through_seq}"
    if task_name in _seen_task_names:
        return  # duplicate enqueue for the same range, rejected like Cloud Tasks would
    _seen_task_names.add(task_name)

    if os.getenv("TASKS_MODE") == "local":
        import asyncio

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

    raise NotImplementedError("Cloud Tasks enqueue not implemented locally; set TASKS_MODE=local")
