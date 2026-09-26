"""LangSmith tracing. Native to LangChain: it activates purely from
LANGSMITH_TRACING/LANGSMITH_API_KEY/LANGSMITH_PROJECT in the environment, and
LangChain's own tracer attaches itself to every run — no client or callback handler
to thread through call sites. An empty .env means tracing never activates."""

import contextlib
import hashlib


@contextlib.contextmanager
def traced_turn(uid: str, thread_id: str, request_id: str, tags: list[str]):
    """Yields the tags/metadata to merge into the graph run's config — user_id/
    session_id are LangSmith's own conventional metadata keys, used to filter/group
    runs by user and conversation in the UI. Kept as a context manager (rather than a
    plain function) only so call sites keep their `with traced_turn(...) as ...:`
    shape — there's no actual span/client lifecycle to manage on this side."""
    yield {
        "tags": tags,
        "metadata": {"user_id": uid, "session_id": thread_id, "request_id": request_id},
    }


def mask_for_export(uid: str, description: str | None) -> dict:
    """Strips free-text before it could ever reach a trace — amounts and categories
    stay, for debugging."""

    def _hash(v: str | None) -> str | None:
        return hashlib.sha256(v.encode()).hexdigest()[:12] if v else None

    return {"description_hash": _hash(description)}
