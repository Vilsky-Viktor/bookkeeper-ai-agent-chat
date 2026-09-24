import pytest
from pydantic import ValidationError

from app.schemas import CreateBatchRequest, TransactionIn


class TestTransactionIn:
    def test_valid_transaction(self):
        t = TransactionIn(occurred_on="2026-01-01", type="expense", amount="12.50", currency="usd")
        assert t.currency == "USD"  # uppercased by the validator

    def test_currency_wrong_length_rejected(self):
        with pytest.raises(ValidationError, match="3-letter ISO 4217 code"):
            TransactionIn(occurred_on="2026-01-01", type="expense", amount="12.50", currency="US")

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            TransactionIn(occurred_on="2026-01-01", type="refund", amount="12.50", currency="USD")

    def test_invalid_date_rejected(self):
        with pytest.raises(ValidationError):
            TransactionIn(occurred_on="not-a-date", type="expense", amount="12.50", currency="USD")

    def test_optional_fields_default_to_none(self):
        t = TransactionIn(occurred_on="2026-01-01", type="income", amount="100", currency="EUR")
        assert t.category is None
        assert t.description is None
        assert t.receipt_uri is None
        assert t.batch_id is None


class TestCreateBatchRequest:
    def test_empty_list_is_structurally_valid(self):
        # Business-rule rejection ("must be non-empty") happens in the router, not
        # the schema — this only checks the schema itself accepts an empty list.
        req = CreateBatchRequest(transactions=[])
        assert req.transactions == []

    def test_rejects_malformed_transaction_in_list(self):
        with pytest.raises(ValidationError):
            CreateBatchRequest(transactions=[{"occurred_on": "2026-01-01", "type": "expense"}])
