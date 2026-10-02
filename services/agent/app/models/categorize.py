from pydantic import BaseModel


class Correction(BaseModel):
    """A category the user chose for a description (stored by the transactions
    service; GET /api/transactions/corrections)."""

    item_key: str  # normalized description
    category: str


def categories_schema(allowed: list[str]) -> dict:
    """The categorizer's structured output: one category per item, each one of
    `allowed` (an enum, so the model can't answer with anything else)."""

    return {
        "title": "categorize_result",
        "type": "object",
        "properties": {"categories": {"type": "array", "items": {"type": "string", "enum": allowed}}},
        "required": ["categories"],
        "additionalProperties": False,
    }
