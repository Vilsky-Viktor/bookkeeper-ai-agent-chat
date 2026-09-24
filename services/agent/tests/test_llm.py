import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from app import llm


class TestBuildChatModel:
    def test_openai_provider_builds_chat_openai_with_requested_model(self):
        model = llm.build_chat_model("gpt-4o", temperature=0.3)
        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "gpt-4o"
        assert model.temperature == 0.3

    def test_json_mode_sets_response_format(self):
        model = llm.build_chat_model("gpt-4o", json_mode=True)
        assert model.model_kwargs == {"response_format": {"type": "json_object"}}

    def test_no_json_mode_leaves_model_kwargs_empty(self):
        model = llm.build_chat_model("gpt-4o")
        assert model.model_kwargs == {}

    def test_unsupported_provider_raises(self, monkeypatch):
        monkeypatch.setattr(llm, "LLM_PROVIDER", "some-unsupported-provider")
        with pytest.raises(ValueError, match="unsupported LLM_PROVIDER"):
            llm.build_chat_model("gpt-4o")

    def test_anthropic_provider_builds_chat_anthropic_with_requested_model(self, monkeypatch):
        monkeypatch.setattr(llm, "LLM_PROVIDER", "anthropic")
        model = llm.build_chat_model("claude-haiku-4-5", temperature=0.3)
        assert isinstance(model, ChatAnthropic)
        assert model.model == "claude-haiku-4-5"
        assert model.temperature == 0.3

    def test_anthropic_provider_ignores_json_mode(self, monkeypatch):
        # Anthropic's Messages API has no response_format/json_object equivalent.
        monkeypatch.setattr(llm, "LLM_PROVIDER", "anthropic")
        model = llm.build_chat_model("claude-haiku-4-5", json_mode=True)
        assert model.model_kwargs == {}

    def test_google_provider_builds_chat_google_with_requested_model(self, monkeypatch):
        monkeypatch.setattr(llm, "LLM_PROVIDER", "google")
        model = llm.build_chat_model("gemini-2.5-flash", temperature=0.3)
        assert isinstance(model, ChatGoogleGenerativeAI)
        assert model.model == "gemini-2.5-flash"
        assert model.temperature == 0.3

    def test_google_provider_json_mode_sets_response_mime_type(self, monkeypatch):
        monkeypatch.setattr(llm, "LLM_PROVIDER", "google")
        model = llm.build_chat_model("gemini-2.5-flash", json_mode=True)
        assert model.response_mime_type == "application/json"

    def test_google_provider_no_json_mode_leaves_response_mime_type_unset(self, monkeypatch):
        monkeypatch.setattr(llm, "LLM_PROVIDER", "google")
        model = llm.build_chat_model("gemini-2.5-flash")
        assert model.response_mime_type is None


class TestModelConstructors:
    def test_primary_model_uses_primary_model_constant(self, monkeypatch):
        monkeypatch.setattr(llm, "PRIMARY_MODEL", "gpt-4o-test")
        assert llm.primary_model().model_name == "gpt-4o-test"

    def test_fallback_model_uses_fallback_model_constant(self, monkeypatch):
        monkeypatch.setattr(llm, "FALLBACK_MODEL", "gpt-4o-mini-test")
        assert llm.fallback_model().model_name == "gpt-4o-mini-test"

    def test_summary_model_uses_zero_temperature(self):
        assert llm.summary_model().temperature == 0

    def test_vision_model_defaults_to_primary_model(self, monkeypatch):
        monkeypatch.setattr(llm, "PRIMARY_MODEL", "gpt-4o-test")
        monkeypatch.setattr(llm, "VISION_MODEL", "gpt-4o-test")
        assert llm.vision_model().model_name == "gpt-4o-test"

    def test_vision_model_uses_json_mode(self):
        assert llm.vision_model().model_kwargs == {"response_format": {"type": "json_object"}}

    def test_vision_model_uses_zero_temperature(self):
        assert llm.vision_model().temperature == 0


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
