"""Lists this service duplicates from elsewhere in the repo (the services share no
code on purpose). These fail when a copy drifts, instead of it failing silently at
runtime."""

import ast
import re
import typing
from pathlib import Path

from app.categorize import CATEGORIES, CATEGORY_DEFINITIONS
from app.languages import SUPPORTED_LANGUAGES
from app.models.notices import NoticeKey
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


def test_every_notice_has_a_translation_in_the_web_app():
    # Other locales are typed against en.ts, so a key there is in all of them.
    en = (REPO / "web/src/lib/i18n/locales/en.ts").read_text()
    ui_keys = set(re.findall(r"^    (\w+):", re.search(r"ui: \{(.*?)\n  \}", en, re.S).group(1), re.M))
    assert set(typing.get_args(NoticeKey)) <= ui_keys


def test_supported_languages_match_the_web_app():
    web = (REPO / "web/src/lib/i18n/languages.ts").read_text()
    assert set(re.findall(r'code: "([a-z]{2})"', web)) == set(SUPPORTED_LANGUAGES)


def test_categories_match_the_web_apps_category_labels():
    en = (REPO / "web/src/lib/i18n/locales/en.ts").read_text()
    block = re.search(r"categories: \{(.*?)\}", en, re.S)
    assert block, "categories block not found in en.ts"
    assert set(re.findall(r"^\s*(\w+):", block.group(1), re.M)) == set(CATEGORIES)


def test_every_category_except_income_has_a_definition_for_the_model():
    assert set(CATEGORY_DEFINITIONS) == set(CATEGORIES) - {"income"}
