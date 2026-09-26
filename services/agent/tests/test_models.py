from app.models.tool_results import ReceiptExtraction


class TestReceiptExtraction:
    def test_strips_thousands_separator_dot_from_a_zero_decimal_total(self):
        # A "." in a zero-decimal currency can only be a misread thousands separator;
        # left in, the transactions service rejects the amount on confirm.
        result = ReceiptExtraction(is_receipt=True, currency="IDR", total_paid="164.100")
        assert result.total_paid == "164100"

    def test_leaves_a_real_decimal_point_alone_for_a_two_decimal_currency(self):
        result = ReceiptExtraction(is_receipt=True, currency="USD", total_paid="12.50")
        assert result.total_paid == "12.50"

    def test_items_are_plain_names(self):
        result = ReceiptExtraction.model_validate(
            {"is_receipt": True, "total_paid": "5.00", "items": ["Rice 1kg", "Eggs"]}
        )
        assert result.items == ["Rice 1kg", "Eggs"]
