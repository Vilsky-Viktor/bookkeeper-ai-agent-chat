import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.idempotency import run_idempotent


class TestRunIdempotent:
    async def test_no_existing_key_runs_handler_and_stores_result(self, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = None
        handler = AsyncMock(return_value=(201, {"id": "abc"}))

        status, response, replayed = await run_idempotent(mock_conn, "uid-1", "key-1", {"a": 1}, handler)

        assert status == 201
        assert response == {"id": "abc"}
        assert replayed is False
        handler.assert_awaited_once()
        # The result gets persisted so a retry with the same key replays it.
        insert_call = mock_conn.execute.call_args
        assert insert_call.args[0].strip().startswith("INSERT INTO idempotency_keys")
        assert insert_call.args[1] == "uid-1"
        assert insert_call.args[2] == "key-1"
        assert insert_call.args[4] == 201
        assert json.loads(insert_call.args[5]) == {"id": "abc"}

    async def test_existing_key_same_payload_replays_without_calling_handler(self, mock_conn: AsyncMock):
        from app.idempotency import _hash

        payload = {"a": 1}
        mock_conn.fetchrow.return_value = {
            "request_hash": _hash(payload),
            "status": 201,
            "response": json.dumps({"id": "abc"}),
        }
        handler = AsyncMock()

        status, response, replayed = await run_idempotent(mock_conn, "uid-1", "key-1", payload, handler)

        assert status == 201
        assert response == {"id": "abc"}
        assert replayed is True
        handler.assert_not_awaited()
        # No new row written on a replay.
        mock_conn.execute.assert_not_awaited()

    async def test_existing_key_different_payload_raises_409(self, mock_conn: AsyncMock):
        from app.idempotency import _hash

        mock_conn.fetchrow.return_value = {
            "request_hash": _hash({"a": 1}),
            "status": 201,
            "response": json.dumps({"id": "abc"}),
        }
        handler = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await run_idempotent(mock_conn, "uid-1", "key-1", {"a": 2}, handler)

        assert exc_info.value.status_code == 409
        handler.assert_not_awaited()

    async def test_hash_is_stable_regardless_of_key_order(self):
        from app.idempotency import _hash

        assert _hash({"a": 1, "b": 2}) == _hash({"b": 2, "a": 1})

    async def test_hash_differs_for_different_payloads(self):
        from app.idempotency import _hash

        assert _hash({"a": 1}) != _hash({"a": 2})
