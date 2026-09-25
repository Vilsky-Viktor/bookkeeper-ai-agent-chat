import pytest
from pydantic import ValidationError

from app.models.transactions import BulkDeleteFilterPayload, CreateBatchRequest, PatchIdempotencyPayload, TransactionIn


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


class TestPatchIdempotencyPayload:
    def test_only_fields_actually_set_are_dumped(self):
        # Mirrors patch_transaction's payload = {"id": transaction_id, **fields} —
        # the idempotency hash/cache must only reflect what the caller actually sent,
        # not every optional field defaulting to None.
        payload = PatchIdempotencyPayload(id="txn-1", category="groceries").model_dump(exclude_unset=True)
        assert payload == {"id": "txn-1", "category": "groceries"}

    def test_all_fields_when_all_set(self):
        payload = PatchIdempotencyPayload(id="txn-1", amount="5.00", currency="USD").model_dump(exclude_unset=True)
        assert payload == {"id": "txn-1", "amount": "5.00", "currency": "USD"}


class TestBulkDeleteFilterPayload:
    def test_from_field_dumps_under_from_alias(self):
        # "from" is a Python keyword, so the field is named from_ with an alias —
        # the on-the-wire/hashed key must still be the literal "from" the original
        # dict literal used, so replaying an old idempotency key still matches.
        payload = BulkDeleteFilterPayload(from_="2026-01-01").model_dump(by_alias=True)
        assert payload["from"] == "2026-01-01"
        assert "from_" not in payload

    def test_full_width_even_when_unset(self):
        # Unlike the patch payload, this one is NOT exclude_unset — every filter key
        # is always present (as None if unfiltered), matching the original dict
        # literal that always built all 8 keys unconditionally.
        payload = BulkDeleteFilterPayload().model_dump(by_alias=True)
        assert set(payload.keys()) == {
            "currency",
            "category",
            "type",
            "from",
            "to",
            "min_amount",
            "max_amount",
            "description",
        }
        assert all(v is None for v in payload.values())
