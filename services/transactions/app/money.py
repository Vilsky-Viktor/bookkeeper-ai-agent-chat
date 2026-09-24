"""Integer minor-unit money handling. Amounts are stored as amount_minor (bigint),
scaled by the currency's ISO 4217 exponent, so aggregates never hit floating point."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Currencies with an exponent other than the default 2.
_EXPONENTS = {
    "JPY": 0,
    "KRW": 0,
    "VND": 0,
    "CLP": 0,
    "ISK": 0,
    "HUF": 0,
    "PYG": 0,
    "UGX": 0,
    "IDR": 0,
    "BHD": 3,
    "KWD": 3,
    "OMR": 3,
    "JOD": 3,
    "TND": 3,
    "LYD": 3,
}
_DEFAULT_EXPONENT = 2


class InvalidAmount(ValueError):
    pass


def exponent_for(currency: str) -> int:
    return _EXPONENTS.get(currency.upper(), _DEFAULT_EXPONENT)


def to_minor(amount: str, currency: str) -> int:
    """Decimal string -> integer minor units. Rejects more decimals than the currency
    allows. `amount` must already be a clean canonical decimal string — "." as the
    real decimal point only, no thousands separator of any kind (",", ".", " ", etc.)
    — for ANY currency, not just ones with an unusual exponent. That normalization is
    the caller's job (e.g. the receipt-extraction prompt, which sees the source
    formatting and can tell a decimal point from a thousands separator); this
    function has no way to guess which one a lone "." means from the string alone, so
    it treats every "." as a real decimal point and just enforces precision."""
    exp = exponent_for(currency)
    try:
        d = Decimal(amount)
    except InvalidOperation as e:
        raise InvalidAmount(f"not a valid decimal amount: {amount!r}") from e
    _, _, e_exp = d.as_tuple()
    if isinstance(e_exp, int) and -e_exp > exp:
        raise InvalidAmount(
            f"{currency} allows at most {exp} decimal place(s) — got {amount!r}. If this "
            'came from a receipt printed with a locale that uses "." as a thousands '
            "separator instead of a decimal point, that's likely misread as extra "
            "precision here — re-check the intended amount."
        )
    minor = int((d * (10**exp)).to_integral_exact(rounding=ROUND_HALF_UP))
    if minor <= 0:
        raise InvalidAmount("amount must be positive")
    return minor


def to_decimal_string(amount_minor: int, currency: str) -> str:
    """Integer minor units -> decimal string for API responses."""
    exp = exponent_for(currency)
    if exp == 0:
        return str(amount_minor)
    d = Decimal(amount_minor).scaleb(-exp)
    return format(d, f".{exp}f")
