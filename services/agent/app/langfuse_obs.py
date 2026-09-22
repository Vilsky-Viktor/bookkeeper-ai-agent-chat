"""Langfuse tracing (architecture doc, Observability > Langfuse setup, p. 16-18).
get_client() never raises when LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY are unset — it
just logs a warning and disables itself — so every call site here is safe to use with
an empty .env; tracing silently no-ops instead of blocking local dev."""

import contextlib

from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler

langfuse = get_client()


@contextlib.contextmanager
def traced_turn(uid: str, thread_id: str, request_id: str, tags: list[str]):
    """Enclosing span with propagate_attributes, so user/session land on the
    top-level trace (setting them only as LangChain metadata can leave them on child
    spans — see doc note under 'What is traced')."""
    with langfuse.start_as_current_observation(as_type="span", name="chat-turn"):
        with propagate_attributes(
            user_id=uid, session_id=thread_id, tags=tags, metadata={"request_id": request_id}
        ):
            yield CallbackHandler()


def mask_for_export(uid: str, description: str | None) -> dict:
    """Strips free-text before anything is exported, per the Privacy in traces
    section — amounts and categories stay, for debugging."""
    import hashlib

    def _hash(v: str | None) -> str | None:
        return hashlib.sha256(v.encode()).hexdigest()[:12] if v else None

    return {"description_hash": _hash(description)}
