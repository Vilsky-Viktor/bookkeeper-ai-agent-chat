"""LLM call policy: timeouts, retries and a fallback model. Retry-on-429/5xx with
backoff+jitter is handled by the provider SDK's own max_retries; we add an overall
timeout, an in-process concurrency cap, and a one-shot fallback to a secondary model.

Every chat model in the app — including the receipt reader and the categorizer
(services/) — is built through build_chat_model() below instead of importing a
provider's LangChain integration at each call site, so swapping providers means adding
one builder function (and its package) here and setting LLM_PROVIDER."""

import asyncio
import os
from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

CALL_TIMEOUT = 60.0
LLM_CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY", "40"))
_semaphore = asyncio.Semaphore(LLM_CONCURRENCY)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
# One model for everything; each purpose can still be pointed elsewhere by its env var.
PRIMARY_MODEL = os.environ.get("LLM_MODEL", "gpt-6-luna")
# A different model as the fallback, so an outage of one doesn't take both down.
FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o")
SUMMARY_MODEL = os.environ.get("LLM_SUMMARY_MODEL", "gpt-6-luna")
VISION_MODEL = os.environ.get("LLM_VISION_MODEL", "gpt-6-luna")
CATEGORIZE_MODEL = os.environ.get("LLM_CATEGORIZE_MODEL", "gpt-6-luna")
# Speech-to-text needs a transcription model, not a chat model.
TRANSCRIBE_MODEL = os.environ.get("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
# medium: at low, the chat eval missed tool choices (query instead of set_filter, a
# description searched as a category); medium passed every case.
# gpt-6-luna is a reasoning model: it only accepts its default temperature (so no
# call sets one), and its reasoning tokens count against max_tokens below. Empty
# means "not sent", for non-reasoning models, which reject the parameter.
REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "medium") or None


def _build_openai(model: str, max_tokens: int, reasoning_effort: str | None) -> BaseChatModel:
    # Imported here, not at module level, so a provider whose package isn't installed
    # only breaks when actually selected, not for everyone importing this module.
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=SecretStr(os.environ["LLM_API_KEY"]),
        timeout=CALL_TIMEOUT,
        max_retries=2,  # SDK-level: retries 429/5xx only, backoff+jitter, honors Retry-After
        max_completion_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )


def _build_anthropic(model: str, max_tokens: int, reasoning_effort: str | None) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    # The constructor args use the fields' aliases (model_name, api_key, timeout,
    # max_tokens_to_sample) because mypy only accepts aliases here; stop=None is also
    # only there for mypy.
    return ChatAnthropic(
        model_name=model,
        api_key=SecretStr(os.environ["LLM_API_KEY"]),
        timeout=CALL_TIMEOUT,
        max_retries=2,
        max_tokens_to_sample=max_tokens,
        stop=None,
    )


def _build_google(model: str, max_tokens: int, reasoning_effort: str | None) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=SecretStr(os.environ["LLM_API_KEY"]),
        timeout=CALL_TIMEOUT,
        max_retries=2,
        max_output_tokens=max_tokens,
    )


# Add an entry here (plus its LangChain integration package as a dependency, plus a
# builder function above) to support a new provider. Every model constructor below
# goes through build_chat_model(), so this map is the only place that needs to
# change — no call site imports a provider-specific class directly.
_PROVIDER_BUILDERS: dict[str, Callable[..., BaseChatModel]] = {
    "openai": _build_openai,
    "anthropic": _build_anthropic,
    "google": _build_google,
}


# max_tokens caps output, billed at ~4x input: a runaway answer is the priciest
# failure. The caps leave room for reasoning tokens on top of the reply itself.
def build_chat_model(
    model: str, max_tokens: int = 2000, reasoning_effort: str | None = REASONING_EFFORT
) -> BaseChatModel:
    """`reasoning_effort` is OpenAI-only (the other builders ignore it)."""

    try:
        builder = _PROVIDER_BUILDERS[LLM_PROVIDER]
    except KeyError:
        raise ValueError(
            f"unsupported LLM_PROVIDER: {LLM_PROVIDER!r} (supported: {sorted(_PROVIDER_BUILDERS)})"
        ) from None

    return builder(model, max_tokens, reasoning_effort)


def primary_model() -> BaseChatModel:
    return build_chat_model(PRIMARY_MODEL)


def fallback_model() -> BaseChatModel:
    # gpt-4o isn't a reasoning model and rejects reasoning_effort.
    return build_chat_model(FALLBACK_MODEL, reasoning_effort=None)


def summary_model() -> BaseChatModel:
    return build_chat_model(SUMMARY_MODEL, max_tokens=1500)


def vision_model() -> BaseChatModel:
    """For services/receipts.py, which adds the structured output schema."""

    return build_chat_model(VISION_MODEL, max_tokens=2000)


def categorize_model(items: int, model: str | None = None) -> BaseChatModel:
    """For services/categorize.py, which adds the structured output schema: one short
    category word per item, plus room for reasoning."""

    return build_chat_model(model or CATEGORIZE_MODEL, max_tokens=12 * items + 1000)


def _build_openai_transcribe_client() -> Any:
    # Imported here, not at module level — same reasoning as _build_openai above.
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=os.environ["LLM_API_KEY"])


# LangChain has no unified speech-to-text model abstraction the way it does
# BaseChatModel, so routers/transcribe.py can't go through
# build_chat_model(). This is the equivalent provider-keyed registry for that one
# non-chat call site, so provider-swapping still doesn't mean hunting through the routers.
_TRANSCRIBE_CLIENT_BUILDERS: dict[str, Callable[[], Any]] = {
    "openai": _build_openai_transcribe_client,
}


def transcribe_client() -> Any:
    try:
        builder = _TRANSCRIBE_CLIENT_BUILDERS[LLM_PROVIDER]
    except KeyError:
        raise ValueError(
            f"unsupported LLM_PROVIDER for transcription: {LLM_PROVIDER!r} "
            f"(supported: {sorted(_TRANSCRIBE_CLIENT_BUILDERS)})"
        ) from None

    return builder()


async def ainvoke_with_fallback(primary, fallback, messages, config=None):
    """Runs `primary`; if it still fails after its own retries (or times out), falls
    back once to `fallback`. Raises the fallback's error if that also fails. `config`
    is threaded through so LangGraph's astream_events sees this as a nested run and
    still emits on_chat_model_stream/end for it."""

    async with _semaphore:
        try:
            return await asyncio.wait_for(primary.ainvoke(messages, config=config), timeout=CALL_TIMEOUT)
        except Exception:
            return await asyncio.wait_for(fallback.ainvoke(messages, config=config), timeout=CALL_TIMEOUT)
