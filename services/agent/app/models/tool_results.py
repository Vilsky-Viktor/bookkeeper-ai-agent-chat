"""Return shapes for the tools built in app/tools/*.py."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolError(BaseModel):
    """Shared error shape across every tool below."""

    error: str


# --- tools/currency.py ---------------------------------------------------------------


class ExchangeRateResult(BaseModel):
    from_currency: str = Field(alias="from")
    to: str
    rate: float
    date: str | None
    note: str

    model_config = ConfigDict(populate_by_name=True)


class CurrencyBreakdownEntry(BaseModel):
    currency: str
    amount: str
    rate: str | None
    converted: str


class TotalInCurrencyResult(BaseModel):
    total: str
    currency: str
    breakdown: list[CurrencyBreakdownEntry]
    note: str | None = None


# --- tools/utility.py ------------------------------------------------------------------


class TransactionFilter(BaseModel):
    currency: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    from_date: Optional[str] = Field(default=None, alias="from")
    to_date: Optional[str] = Field(default=None, alias="to")
    min_amount: Optional[str] = None
    max_amount: Optional[str] = None
    description: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class FilterSetResult(BaseModel):
    ui_event: Literal["filter_set"] = "filter_set"
    filter: TransactionFilter


class ExportReadyResult(BaseModel):
    ui_event: Literal["export_ready"] = "export_ready"


# --- tools/crud.py -----------------------------------------------------------------

# add/edit/delete/delete_matching merge the transactions service's own response
# (**resp.json()) into their return value — that data isn't owned by this service, so
# it isn't forced into a rigid schema here; extra="allow" documents the one field this
# service does control (ui_event) while letting the rest pass through untouched.


class TableChangedResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    ui_event: Literal["table_changed"] = "table_changed"


# --- tools/receipts.py ---------------------------------------------------------------


class NotAReceiptResult(BaseModel):
    not_a_receipt: Literal[True] = True
    message: str


class ReceiptProposedItem(BaseModel):
    occurred_on: str | None
    type: str
    amount: str | None
    currency: str
    category: str
    description: str | None
    receipt_uri: str


class ReceiptProposedResult(BaseModel):
    ui_event: Literal["receipt_proposed"] = "receipt_proposed"
    items: list[ReceiptProposedItem]
    receipt_uri: str


class ReceiptLineItem(BaseModel):
    description: str
    amount: str


class ReceiptExtraction(BaseModel):
    """Validates the vision model's parsed JSON output immediately after json.loads —
    catches a malformed/off-spec response early with a clear error instead of an
    AttributeError several lines later."""

    is_receipt: bool
    merchant: str | None = None
    occurred_on: str | None = None
    currency: str | None = None
    items: list[ReceiptLineItem] = Field(default_factory=list)
