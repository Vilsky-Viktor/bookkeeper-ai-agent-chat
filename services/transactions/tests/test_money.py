import pytest

from app.money import InvalidAmount, exponent_for, to_decimal_string, to_minor


class TestExponentFor:
    def test_default_currency_has_two_decimals(self):
        assert exponent_for("USD") == 2

    def test_zero_decimal_currency(self):
        assert exponent_for("JPY") == 0

    def test_three_decimal_currency(self):
        assert exponent_for("BHD") == 3

    def test_case_insensitive(self):
        assert exponent_for("jpy") == 0


class TestToMinor:
    def test_simple_two_decimal_amount(self):
        assert to_minor("12.50", "USD") == 1250

    def test_integer_amount(self):
        assert to_minor("12", "USD") == 1200

    def test_zero_decimal_currency_rejects_fractional_precision_beyond_zero(self):
        assert to_minor("500", "JPY") == 500

    def test_three_decimal_currency(self):
        assert to_minor("1.234", "BHD") == 1234

    def test_rounds_half_up_within_allowed_precision(self):
        # 2 decimals allowed for USD; exact precision, no rounding needed here.
        assert to_minor("9.99", "USD") == 999

    def test_error_not_a_valid_decimal(self):
        with pytest.raises(InvalidAmount, match="not a valid decimal amount"):
            to_minor("abc", "USD")

    def test_error_too_many_decimal_places(self):
        with pytest.raises(InvalidAmount, match="allows at most 2 decimal place"):
            to_minor("12.505", "USD")

    def test_error_too_many_decimals_for_zero_exponent_currency(self):
        with pytest.raises(InvalidAmount, match="allows at most 0 decimal place"):
            to_minor("12.5", "JPY")

    def test_error_zero_amount_rejected(self):
        with pytest.raises(InvalidAmount, match="must be positive"):
            to_minor("0", "USD")

    def test_error_negative_amount_rejected(self):
        with pytest.raises(InvalidAmount, match="must be positive"):
            to_minor("-5.00", "USD")

    def test_error_empty_string(self):
        with pytest.raises(InvalidAmount):
            to_minor("", "USD")


class TestToDecimalString:
    def test_two_decimal_currency(self):
        assert to_decimal_string(1250, "USD") == "12.50"

    def test_zero_decimal_currency(self):
        assert to_decimal_string(500, "JPY") == "500"

    def test_three_decimal_currency(self):
        assert to_decimal_string(1234, "BHD") == "1.234"

    def test_round_trip_with_to_minor(self):
        minor = to_minor("42.07", "EUR")
        assert to_decimal_string(minor, "EUR") == "42.07"

    def test_small_amount_keeps_leading_zero(self):
        assert to_decimal_string(5, "USD") == "0.05"
