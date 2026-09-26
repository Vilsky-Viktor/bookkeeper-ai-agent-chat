from pydantic import BaseModel


class Correction(BaseModel):
    """A category the user chose for a description (stored by the transactions
    service; GET /api/transactions/corrections)."""

    item_key: str  # normalized description
    category: str
