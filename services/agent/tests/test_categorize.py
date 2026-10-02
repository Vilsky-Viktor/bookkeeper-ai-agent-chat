import json

import httpx
import pytest

from app.integrations import llm
from app.models.categorize import Correction
from app.services import categorize


class _FakeModel:
    """Stands in for the model plus its structured output: records the schema it was
    given and answers `reply` (a JSON string) as the parsed dict."""

    def __init__(self, reply: str | Exception):
        self.reply = reply
        self.prompts: list[str] = []
        self.schemas: list[dict] = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)

        return self

    async def ainvoke(self, messages, config=None):
        self.prompts.append(messages[0].content)

        if isinstance(self.reply, Exception):
            raise self.reply

        return json.loads(self.reply)


@pytest.fixture
def model(monkeypatch):
    """Replace the categorizer's model; set .reply to what it answers."""
    fake = _FakeModel(json.dumps({"categories": []}))
    built: list[tuple[int, str | None]] = []

    def build(items, model_name=None):
        built.append((items, model_name))

        return fake

    monkeypatch.setattr(llm, "categorize_model", build)
    fake.built = built  # type: ignore[attr-defined]

    return fake


class TestCategorize:
    async def test_an_exact_correction_skips_the_model(self, model):
        corrections = [Correction(item_key="rice - shop", category="groceries")]
        assert await categorize.categorize(["  Rice - Shop "], corrections) == ["groceries"]
        assert model.prompts == []

    async def test_one_model_call_for_every_item_without_a_correction(self, model):
        model.reply = json.dumps({"categories": ["dining", "shopping"]})
        corrections = [Correction(item_key="shampoo - shop", category="health")]

        result = await categorize.categorize(["Latte - Cafe", "Shampoo - Shop", "Marlboro - 7-Eleven"], corrections)

        assert result == ["dining", "health", "shopping"]
        (prompt,) = model.prompts
        assert "1. Latte - Cafe" in prompt and "2. Marlboro - 7-Eleven" in prompt
        assert "Shampoo" not in prompt.split("Items:")[1].split("The user has")[0]
        assert model.built == [(2, None)]  # output budget sized for 2 items

    async def test_missing_answers_become_other(self, model):
        model.reply = json.dumps({"categories": ["dining"]})
        assert await categorize.categorize(["a", "b"], []) == ["dining", "other"]

    async def test_the_schema_allows_only_the_built_in_and_custom_categories(self, model):
        # An enum in the structured output, so the model can't answer with anything
        # else; "income" is never a guess (it's only set for income transactions).
        model.reply = json.dumps({"categories": ["Work Tools"]})
        corrections = [Correction(item_key="claude subscription", category="Work Tools")]

        assert await categorize.categorize(["Claude AI subscription payment"], corrections) == ["Work Tools"]
        (schema,) = model.schemas
        allowed = schema["properties"]["categories"]["items"]["enum"]
        assert "Work Tools" in allowed and "groceries" in allowed and "income" not in allowed

    async def test_a_failed_model_call_falls_back_to_other(self, model):
        model.reply = RuntimeError("API down")
        assert await categorize.categorize(["a"], []) == ["other"]

    async def test_prompt_carries_the_definitions_and_the_users_corrections(self, model):
        model.reply = json.dumps({"categories": ["shopping"]})
        corrections = [Correction(item_key="3x camel white 20", category="entertainment")]

        await categorize.categorize(["Camel White 20's - Indomaret"], corrections)

        (prompt,) = model.prompts
        # The groceries definition excludes tobacco — a regression fix (cigarettes
        # from a minimarket were filed as groceries).
        assert "tobacco" in prompt.lower()
        assert '"3x camel white 20" -> entertainment' in prompt
        assert "- income:" not in prompt


class TestFetchCorrections:
    async def test_reads_the_users_corrections(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/transactions/corrections"

            return httpx.Response(200, json={"items": [{"item_key": "coffee", "category": "dining"}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t") as c:
            assert await categorize.fetch_corrections(c) == [Correction(item_key="coffee", category="dining")]

    async def test_a_failure_means_no_history_not_an_error(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(500)), base_url="http://t"
        ) as c:
            assert await categorize.fetch_corrections(c) == []
