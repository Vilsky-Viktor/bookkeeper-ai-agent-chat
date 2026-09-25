"""Serializes a transactions row into the API's JSON shape."""

import asyncpg

from ...money import to_decimal_string


def row_to_out(row: asyncpg.Record) -> dict:
    return {
        "id": str(row["id"]),
        "uid": row["uid"],
        "occurred_on": row["occurred_on"].isoformat(),
        "type": row["type"],
        "amount": to_decimal_string(row["amount_minor"], row["currency"]),
        "currency": row["currency"],
        "category": row["category"],
        "description": row["description"],
        "receipt_uri": row["receipt_uri"],
        "batch_id": str(row["batch_id"]) if row["batch_id"] else None,
        "created_at": row["created_at"].isoformat(),
    }
