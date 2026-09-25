import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class TransactionsListResponse(BaseModel):
    items: list[TransactionOut]
    next_cursor: Optional[str] = None


class BulkDeleteResponse(BaseModel):
    deleted_count: int


class DeleteResponse(BaseModel):
    deleted: str


class PatchIdempotencyPayload(TransactionPatch):
    """What patch_transaction hashes/persists in idempotency_keys — TransactionPatch's
    fields plus the id being patched. Dumped with exclude_unset=True so only the
    fields the caller actually sent land in the hash/cache, matching the dynamic-width
    dict `{"id": transaction_id, **fields}` this replaces."""

    id: str


class BulkDeleteFilterPayload(BaseModel):
    """What delete_transactions_bulk hashes/persists in idempotency_keys — mirrors the
    filter kwargs build_filter_clauses() takes, using "from" (a Python keyword) as the
    on-the-wire key via alias, same as the dict literal this replaces.

    populate_by_name=True so callers can construct this with from_= (the field's own
    Python name — "from" alone isn't valid keyword-argument syntax); .model_dump(
    by_alias=True) still emits "from" on the way out, matching the original dict's key
    exactly for idempotency-hash consistency."""

    model_config = ConfigDict(populate_by_name=True)

    currency: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    min_amount: Optional[str] = None
    max_amount: Optional[str] = None
    description: Optional[str] = None
