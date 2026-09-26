"""Lists this service duplicates from elsewhere in the repo (the services share no
code on purpose). These fail when a copy drifts, instead of it failing silently at
runtime."""

import ast
import re
from pathlib import Path

from app.chat.receipt_turn import _REPLIES
from app.languages import SUPPORTED_LANGUAGES
from app.models.tool_results import _ZERO_DECIMAL_CURRENCIES

REPO = Path(__file__).resolve().parents[3]


def _assigned_literal(path: Path, name: str):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def test_zero_decimal_currencies_match_the_transactions_service():
    exponents = _assigned_literal(REPO / "services/transactions/app/money.py", "_EXPONENTS")
    assert _ZERO_DECIMAL_CURRENCIES == {code for code, exponent in exponents.items() if exponent == 0}


def test_every_supported_language_has_receipt_replies():
    assert set(_REPLIES) == set(SUPPORTED_LANGUAGES)


def test_supported_languages_match_the_web_app():
    web = (REPO / "web/src/lib/i18n/languages.ts").read_text()
    assert set(re.findall(r'code: "([a-z]{2})"', web)) == set(SUPPORTED_LANGUAGES)
