import pytest

from app.money import InvalidAmount, exponent_for, to_decimal_string, to_minor


class TestExponentFor:
    def test_default_currency_has_two_decimals(self):
        assert exponent_for("USD") == 2

    def test_zero_decimal_currency(self):
        assert exponent_for("JPY") == 0

    def test_three_decimal_currency(self):
        assert exponent_for("BHD") == 3

    def test_idr_is_zero_decimals(self):
        # IDR's sen subunit is defunct — real purchases are always whole rupiah.
        assert exponent_for("IDR") == 0

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

    def test_idr_thousands_separator_is_rejected_not_silently_misparsed(self):
        # "104.700" written on an Indonesian receipt means 104,700 rupiah (the "." is
        # a thousands separator there, not a decimal point) — money.py has no way to
        # tell that from the bare string, so normalizing this is the extraction
        # prompt's job (see tools.py), not to_minor's. This asserts the money-layer
        # side of that contract: a raw, un-normalized "104.700" must be rejected
        # loudly, never silently stored as 104.70 (1000x too small).
        with pytest.raises(InvalidAmount, match="allows at most 0 decimal place"):
            to_minor("104.700", "IDR")

    def test_error_message_hints_at_thousands_separator_confusion(self):
        with pytest.raises(InvalidAmount, match="thousands"):
            to_minor("104.700", "IDR")

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


ZERO_DECIMAL_CURRENCIES = ["JPY", "KRW", "VND", "CLP", "ISK", "HUF", "PYG", "UGX", "IDR"]
THREE_DECIMAL_CURRENCIES = ["BHD", "KWD", "OMR", "JOD", "TND", "LYD"]
TWO_DECIMAL_CURRENCIES = ["USD", "EUR", "GBP", "AUD", "CAD", "SGD", "CHF"]  # the unlisted-currency default


class TestExponentForEveryKnownCurrency:
    """Spot-checking one currency per bucket (above) isn't enough to catch a typo'd
    entry in money.py's _EXPONENTS table — this walks every currency it lists,
    plus a sample of ones that fall through to the default, individually."""

    @pytest.mark.parametrize("currency", ZERO_DECIMAL_CURRENCIES)
    def test_zero_decimal_currency(self, currency):
        assert exponent_for(currency) == 0

    @pytest.mark.parametrize("currency", THREE_DECIMAL_CURRENCIES)
    def test_three_decimal_currency(self, currency):
        assert exponent_for(currency) == 3

    @pytest.mark.parametrize("currency", TWO_DECIMAL_CURRENCIES)
    def test_two_decimal_default_currency(self, currency):
        assert exponent_for(currency) == 2


class TestToMinorAndToDecimalStringRoundTripEveryKnownCurrency:
    """For every currency money.py knows an exponent for, a correctly-formatted
    amount at that exact precision must both parse via to_minor and format back to
    the identical string via to_decimal_string — the two functions must agree with
    each other and with exponent_for for every currency, not just the ones spot-
    checked elsewhere in this file."""

    @pytest.mark.parametrize("currency", ZERO_DECIMAL_CURRENCIES)
    def test_zero_decimal_round_trip(self, currency):
        assert to_minor("1500", currency) == 1500
        assert to_decimal_string(1500, currency) == "1500"

    @pytest.mark.parametrize("currency", THREE_DECIMAL_CURRENCIES)
    def test_three_decimal_round_trip(self, currency):
        assert to_minor("12.345", currency) == 12345
        assert to_decimal_string(12345, currency) == "12.345"

    @pytest.mark.parametrize("currency", TWO_DECIMAL_CURRENCIES)
    def test_two_decimal_round_trip(self, currency):
        assert to_minor("12.34", currency) == 1234
        assert to_decimal_string(1234, currency) == "12.34"

    @pytest.mark.parametrize("currency", ZERO_DECIMAL_CURRENCIES)
    def test_zero_decimal_currency_rejects_any_fractional_amount(self, currency):
        with pytest.raises(InvalidAmount, match="allows at most 0 decimal place"):
            to_minor("12.5", currency)

    @pytest.mark.parametrize("currency", THREE_DECIMAL_CURRENCIES)
    def test_three_decimal_currency_rejects_a_fourth_decimal_place(self, currency):
        with pytest.raises(InvalidAmount, match="allows at most 3 decimal place"):
            to_minor("12.3456", currency)

    @pytest.mark.parametrize("currency", TWO_DECIMAL_CURRENCIES)
    def test_two_decimal_currency_rejects_a_third_decimal_place(self, currency):
        with pytest.raises(InvalidAmount, match="allows at most 2 decimal place"):
            to_minor("12.345", currency)

    @pytest.mark.parametrize("currency", ZERO_DECIMAL_CURRENCIES + THREE_DECIMAL_CURRENCIES + TWO_DECIMAL_CURRENCIES)
    def test_lowercase_currency_code_behaves_identically(self, currency):
        exp = exponent_for(currency)
        amount = "1" + ("." + "5" * exp if exp else "")
        assert to_minor(amount, currency) == to_minor(amount, currency.lower())


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
