"""Lists this service shares with other parts of the repo by copy (the services share
no code on purpose). These fail when a copy drifts."""

import re
from pathlib import Path

from app.categorize import CATEGORIES, CATEGORY_DEFINITIONS

REPO = Path(__file__).resolve().parents[3]


def test_categories_match_the_web_apps_category_labels():
    en = (REPO / "web/src/lib/i18n/locales/en.ts").read_text()
    block = re.search(r"categories: \{(.*?)\}", en, re.S)
    assert block, "categories block not found in en.ts"
    assert set(re.findall(r"^\s*(\w+):", block.group(1), re.M)) == set(CATEGORIES)


def test_every_category_except_income_has_a_definition_for_the_model():
    assert set(CATEGORY_DEFINITIONS) == set(CATEGORIES) - {"income"}
