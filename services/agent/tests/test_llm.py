import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from app.integrations import llm


class TestBuildChatModel:
    def test_openai_provider_builds_chat_openai_with_requested_model(self):
        model = llm.build_chat_model("gpt-6-luna", max_tokens=1234)

        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "gpt-6-luna"
        assert model.max_tokens == 1234

    def test_openai_sets_reasoning_effort_and_no_temperature(self):
        # gpt-6-luna rejects any temperature but its default (a 400 error).
        model = llm.build_chat_model("gpt-6-luna", reasoning_effort="none")

        assert model.reasoning_effort == "none"
        assert model.temperature is None

    def test_no_reasoning_effort_is_sent_when_unset(self):
        # A non-reasoning model (e.g. gpt-4o) rejects the parameter with a 400.
        assert llm.build_chat_model("gpt-4o", reasoning_effort=None).reasoning_effort is None

    def test_unsupported_provider_raises(self, monkeypatch):
        monkeypatch.setattr(llm, "LLM_PROVIDER", "some-unsupported-provider")

        with pytest.raises(ValueError, match="unsupported LLM_PROVIDER"):
            llm.build_chat_model("gpt-6-luna")

    def test_anthropic_provider_builds_chat_anthropic_with_requested_model(self, monkeypatch):
        monkeypatch.setattr(llm, "LLM_PROVIDER", "anthropic")
        model = llm.build_chat_model("claude-haiku-4-5")

        assert isinstance(model, ChatAnthropic)
        assert model.model == "claude-haiku-4-5"

    def test_google_provider_builds_chat_google_with_requested_model(self, monkeypatch):
        monkeypatch.setattr(llm, "LLM_PROVIDER", "google")
        model = llm.build_chat_model("gemini-2.5-flash")

        assert isinstance(model, ChatGoogleGenerativeAI)
        assert model.model == "gemini-2.5-flash"


class TestModelConstructors:
    def test_every_purpose_but_the_fallback_defaults_to_gpt_6_luna(self):
        # Unless an env var points a purpose elsewhere (the test env sets none).
        for name in ("PRIMARY_MODEL", "SUMMARY_MODEL", "VISION_MODEL", "CATEGORIZE_MODEL"):
            assert getattr(llm, name) == "gpt-6-luna", name

    def test_the_fallback_is_gpt_4o_without_reasoning_effort(self):
        # A different model, so one outage doesn't take both down; gpt-4o rejects
        # reasoning_effort with a 400.
        assert llm.FALLBACK_MODEL == "gpt-4o"
        assert llm.fallback_model().reasoning_effort is None

    def test_primary_model_uses_primary_model_constant(self, monkeypatch):
        monkeypatch.setattr(llm, "PRIMARY_MODEL", "model-a")
        assert llm.primary_model().model_name == "model-a"

    def test_fallback_model_uses_fallback_model_constant(self, monkeypatch):
        monkeypatch.setattr(llm, "FALLBACK_MODEL", "model-b")
        assert llm.fallback_model().model_name == "model-b"

    def test_vision_model_uses_vision_model_constant(self, monkeypatch):
        monkeypatch.setattr(llm, "VISION_MODEL", "model-c")
        assert llm.vision_model().model_name == "model-c"

    def test_categorize_cap_leaves_room_for_reasoning(self):
        # A reasoning model spends output tokens before answering; a cap sized for
        # the answer alone (~12 per item) would cut the reply off.
        assert llm.categorize_model(1).max_tokens >= 500


class TestTranscribeClient:
    def test_openai_provider_builds_async_openai_client(self):
        client = llm.transcribe_client()
        assert isinstance(client, AsyncOpenAI)

    def test_unsupported_provider_raises(self, monkeypatch):
        monkeypatch.setattr(llm, "LLM_PROVIDER", "some-unsupported-provider")

        with pytest.raises(ValueError, match="unsupported LLM_PROVIDER for transcription"):
            llm.transcribe_client()


class TestAinvokeWithFallback:
    async def test_primary_success_does_not_call_fallback(self):
        primary = AsyncMock()
        primary.ainvoke = AsyncMock(return_value="primary result")
        fallback = AsyncMock()

        result = await llm.ainvoke_with_fallback(primary, fallback, ["msg"])

        assert result == "primary result"
        fallback.ainvoke.assert_not_called()

    async def test_primary_failure_falls_back(self):
        primary = AsyncMock()
        primary.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        fallback = AsyncMock()
        fallback.ainvoke = AsyncMock(return_value="fallback result")

        result = await llm.ainvoke_with_fallback(primary, fallback, ["msg"])

        assert result == "fallback result"

    async def test_both_fail_raises(self):
        primary = AsyncMock()
        primary.ainvoke = AsyncMock(side_effect=RuntimeError("primary boom"))
        fallback = AsyncMock()
        fallback.ainvoke = AsyncMock(side_effect=RuntimeError("fallback boom"))

        with pytest.raises(RuntimeError, match="fallback boom"):
            await llm.ainvoke_with_fallback(primary, fallback, ["msg"])

    async def test_primary_timeout_falls_back(self, monkeypatch):
        async def _hangs(*args, **kwargs):
            await asyncio.sleep(10)

        primary = AsyncMock()
        primary.ainvoke = _hangs
        fallback = AsyncMock()
        fallback.ainvoke = AsyncMock(return_value="fallback result")

        monkeypatch.setattr(llm, "CALL_TIMEOUT", 0.05)
        result = await llm.ainvoke_with_fallback(primary, fallback, ["msg"])

        assert result == "fallback result"


class TestReasoningEffortDefault:
    def test_defaults_to_medium(self):
        assert llm.REASONING_EFFORT == "medium"
        assert llm.primary_model().reasoning_effort == "medium"
