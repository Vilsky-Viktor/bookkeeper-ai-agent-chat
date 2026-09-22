import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class TransactionIn(BaseModel):
    occurred_on: datetime.date
    type: Literal["expense", "income"]
    amount: str  # decimal string, e.g. "12.50"
    currency: str
    category: Optional[str] = None
    description: Optional[str] = None
    receipt_uri: Optional[str] = None
    batch_id: Optional[str] = None

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        v = v.upper()
        if len(v) != 3:
            raise ValueError("currency must be a 3-letter ISO 4217 code")
        return v


class TransactionPatch(BaseModel):
    occurred_on: Optional[datetime.date] = None
    type: Optional[Literal["expense", "income"]] = None
    amount: Optional[str] = None
    currency: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None


class CreateBatchRequest(BaseModel):
    transactions: list[TransactionIn]


class TransactionOut(BaseModel):
    id: str
    uid: str
    occurred_on: datetime.date
    type: str
    amount: str
    currency: str
    category: str
    description: Optional[str]
    receipt_uri: Optional[str]
    batch_id: Optional[str]
    created_at: datetime.datetime
