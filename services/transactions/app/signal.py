"""Firestore change-signal bump, shared shape with services/agent/app/signal.py.
Best-effort: a failed bump is logged, never raised into the request."""

import asyncio
import logging

from google.cloud import firestore  # honors FIRESTORE_EMULATOR_HOST

log = logging.getLogger("signal")
_db: firestore.Client | None = None


def _client() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client()
    return _db


def _nested_increment_dict(fields: list[str]) -> dict:
    """Turns dotted field paths into a nested dict of Increment sentinels, so
    set(merge=True) deep-merges instead of overwriting a whole nested map."""
    result: dict = {}
    for f in fields:
        parts = f.split(".")
        node = result
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = firestore.Increment(1)
    return result


def bump(uid: str, fields: list[str], origin: str | None) -> None:
    try:
        data = _nested_increment_dict(fields)
        data["origin"] = origin
        data["updated_at"] = firestore.SERVER_TIMESTAMP
        _client().document(f"sync/{uid}").set(data, merge=True)
    except Exception:
        log.warning("sync bump failed", exc_info=True)


async def bump_async(uid: str, fields: list[str], origin: str | None) -> None:
    await asyncio.to_thread(bump, uid, fields, origin)
