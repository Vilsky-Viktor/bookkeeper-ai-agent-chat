"""Return shapes for the tools built in app/tools/*.py."""

from decimal import Decimal, InvalidOperation
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


# Currencies with a 0 exponent — must stay in sync with services/transactions/app/
# money.py's _EXPONENTS (a separate service, no shared code to import this from). A
# correctly-formatted zero-decimal amount never contains a ".", which is exactly what
# makes the model-output bug below (see _normalize_amounts) detectable and safe to
# auto-correct: a "." in one of these currencies can only be a misread thousands
# separator (e.g. IDR "63.800" meaning 63,800 rupiah), never a real decimal point.
_ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW", "VND", "CLP", "ISK", "HUF", "PYG", "UGX", "IDR"}


class ReceiptExtraction(BaseModel):
    """Validates the vision model's parsed JSON output immediately after json.loads —
    catches a malformed/off-spec response early with a clear error instead of an
    AttributeError several lines later. Also normalizes two specific, observed
    failure modes of the vision model itself (see _normalize_amounts) rather than
    relying solely on prompt instructions it doesn't always follow — both would
    otherwise reach the user as a proposed item that fails the moment they try to
    confirm it, since the transactions service enforces amount_minor > 0 and rejects
    more decimal places than a currency allows."""

    is_receipt: bool
    merchant: str | None = None
    occurred_on: str | None = None
    currency: str | None = None
    items: list[ReceiptLineItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_amounts(self) -> "ReceiptExtraction":
        if not self.items:
            return self

        if (self.currency or "").upper() in _ZERO_DECIMAL_CURRENCIES:
            for item in self.items:
                item.amount = item.amount.replace(".", "")

        # A stray negative line (a discount/voucher the model failed to net into the
        # charge it reduces, despite the prompt instructing it to) can never be saved
        # as its own transaction — every amount in this system is a positive
        # magnitude, with sign coming from a separate expense/income type, never a
        # negative literal (see db/init/001_schema.sql's amount_minor > 0 check). Net
        # it into the largest positive item instead of letting the model's mistake
        # reach the user as an item that's guaranteed to fail on confirm.
        positive_items: list[ReceiptLineItem] = []
        negative_items: list[ReceiptLineItem] = []
        for item in self.items:
            try:
                (negative_items if Decimal(item.amount) < 0 else positive_items).append(item)
            except InvalidOperation:
                positive_items.append(item)  # not our job to fix a non-numeric amount
        if negative_items and positive_items:
            target = max(positive_items, key=lambda i: Decimal(i.amount))
            adjustment = sum((Decimal(i.amount) for i in negative_items), start=Decimal(0))
            target.amount = str(Decimal(target.amount) + adjustment)
            self.items = positive_items

        return self
