from app.models.tool_results import ReceiptExtraction, ReceiptLineItem


def extraction(currency: str, items: list[tuple[str, str]]) -> ReceiptExtraction:
    return ReceiptExtraction(
        is_receipt=True,
        currency=currency,
        items=[ReceiptLineItem(description=d, amount=a) for d, a in items],
    )


class TestReceiptExtractionNormalization:
    # Regression: an Indonesian food-delivery receipt ("Warung Jakarta, Tabanan") came
    # back with the exact shape guarded here — a zero-decimal (IDR) amount with a
    # thousands-separator "." misread as a decimal point, and its "Other discounts"
    # line reported as its own negative item instead of netted into the product. Both
    # are guaranteed to fail at confirm time (transactions' money.py rejects extra
    # decimal places for a zero-decimal currency, and rejects amount <= 0 outright),
    # so this normalizes them before they ever reach the user as a proposed item.

    def test_strips_thousands_separator_dot_for_a_zero_decimal_currency(self):
        result = extraction("IDR", [("Coffee", "63.800")])
        assert result.items[0].amount == "63800"

    def test_leaves_a_real_decimal_point_alone_for_a_two_decimal_currency(self):
        result = extraction("USD", [("Coffee", "12.50")])
        assert result.items[0].amount == "12.50"

    def test_nets_a_stray_negative_item_into_the_largest_positive_item(self):
        result = extraction(
            "IDR",
            [("Warung Jakarta food", "63.800"), ("Handling and delivery fee", "26.900"), ("Other discounts", "-6.000")],
        )
        assert len(result.items) == 2
        amounts = {i.description: i.amount for i in result.items}
        assert amounts["Warung Jakarta food"] == "57800"  # 63800 - 6000, not the fee
        assert amounts["Handling and delivery fee"] == "26900"  # untouched

    def test_no_negative_items_is_a_no_op(self):
        result = extraction("USD", [("Coffee", "5.00"), ("Delivery fee", "2.00")])
        assert [i.amount for i in result.items] == ["5.00", "2.00"]

    def test_all_negative_items_are_left_as_is_with_nothing_to_net_into(self):
        # Bizarre/never-expected in practice (a receipt with no positive lines at
        # all) — left alone rather than guessed at; this would still fail at confirm
        # time, same as before normalization existed, just not silently mishandled.
        result = extraction("USD", [("Refund", "-5.00")])
        assert [i.amount for i in result.items] == ["-5.00"]

    def test_non_numeric_amount_does_not_crash_normalization(self):
        result = extraction("USD", [("Mystery item", "not-a-number")])
        assert result.items[0].amount == "not-a-number"
