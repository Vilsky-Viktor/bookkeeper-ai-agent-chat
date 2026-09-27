"""A transactions DB row for the router tests (test_transactions_*.py)."""

import datetime
import uuid

TXN_ID = str(uuid.uuid4())


def row(**overrides) -> dict:
    data = {
        "id": TXN_ID,
        "uid": "test-uid",
        "occurred_on": datetime.date(2026, 1, 15),
        "type": "expense",
        "amount_minor": 1250,
        "currency": "USD",
        "category": "dining",
        "description": "coffee",
        "receipt_uri": None,
        "batch_id": None,
        "created_at": datetime.datetime(2026, 1, 15, 12, 0, 0),
    }
    data.update(overrides)

    return data
