"""LLM call policy: timeouts, retries and a fallback model (architecture doc,
Scalability and resilience > LLM calls, p. 15). Retry-on-429/5xx with backoff+jitter is
handled by the provider SDK's own max_retries; we add an overall timeout, an
in-process concurrency cap, and a one-shot fallback to a secondary model.

Every chat model in the app — including the one-shot receipt-vision call in
tools.py, which used to go through a separate raw OpenAI client — is built through
build_chat_model() below instead of importing a provider's LangChain integration
directly at each call site. Swapping providers is then a matter of adding one builder
function (and its package as a dependency) here and setting LLM_PROVIDER, not
hunting down every place a model gets constructed."""

import asyncio
import os
from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

CALL_TIMEOUT = 60.0
LLM_CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY", "40"))
_semaphore = asyncio.Semaphore(LLM_CONCURRENCY)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
PRIMARY_MODEL = os.environ.get("LLM_MODEL", "gpt-4o")
FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o-mini")
SUMMARY_MODEL = os.environ.get("LLM_SUMMARY_MODEL", "gpt-4o-mini")
# Receipt extraction needs real vision + instruction-following (locale number
# formats, fee attribution, merchant nulls — see tools.py's RECEIPT_EXTRACTION_PROMPT)
# — it defaults to the primary model rather than the cheaper fallback/summary ones.
VISION_MODEL = os.environ.get("LLM_VISION_MODEL", PRIMARY_MODEL)
TRANSCRIBE_MODEL = os.environ.get("TRANSCRIBE_MODEL", "whisper-1")


def _build_openai(model: str, temperature: float, *, json_mode: bool) -> BaseChatModel:
    # Imported here, not at module level, so a provider whose package isn't installed
    # only breaks when actually selected, not for everyone importing this module.
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=SecretStr(os.environ["LLM_API_KEY"]),
        timeout=CALL_TIMEOUT,
        max_retries=2,  # SDK-level: retries 429/5xx only, backoff+jitter, honors Retry-After
        temperature=temperature,
        model_kwargs={"response_format": {"type": "json_object"}} if json_mode else {},
    )


def _build_anthropic(model: str, temperature: float, *, json_mode: bool) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    # Unlike OpenAI, Anthropic's Messages API has no response_format/json_object mode
    # — json_mode is a no-op here; JSON-only output relies on the prompt itself (see
    # tools.py's RECEIPT_EXTRACTION_PROMPT), which Claude follows reliably in practice.
    #
    # model/anthropic_api_key/default_request_timeout are the field names (what
    # self.model etc. read back as); model_name/api_key/timeout are their Field(alias=)
    # — pydantic's dataclass_transform only types the constructor by alias, so mypy
    # rejects the field names here even though they're also accepted at runtime.
    # stop=None is likewise just satisfying mypy: stop_sequences (alias "stop") has a
    # real default, but dataclass_transform doesn't see it as optional in this class.
    return ChatAnthropic(
        model_name=model,
        api_key=SecretStr(os.environ["LLM_API_KEY"]),
        timeout=CALL_TIMEOUT,
        max_retries=2,
        temperature=temperature,
        stop=None,
    )


def _build_google(model: str, temperature: float, *, json_mode: bool) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=SecretStr(os.environ["LLM_API_KEY"]),
        timeout=CALL_TIMEOUT,
        max_retries=2,
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
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


def build_chat_model(model: str, temperature: float = 0.2, *, json_mode: bool = False) -> BaseChatModel:
    try:
        builder = _PROVIDER_BUILDERS[LLM_PROVIDER]
    except KeyError:
        raise ValueError(
            f"unsupported LLM_PROVIDER: {LLM_PROVIDER!r} (supported: {sorted(_PROVIDER_BUILDERS)})"
        ) from None
    return builder(model, temperature, json_mode=json_mode)


def primary_model() -> BaseChatModel:
    return build_chat_model(PRIMARY_MODEL)


def fallback_model() -> BaseChatModel:
    return build_chat_model(FALLBACK_MODEL)


def summary_model() -> BaseChatModel:
    return build_chat_model(SUMMARY_MODEL, temperature=0)


def vision_model() -> BaseChatModel:
    """Used for receipt image extraction (see tools.py) — a one-shot structured-JSON
    call outside the main chat graph, so it's built directly rather than bound with
    tools."""
    return build_chat_model(VISION_MODEL, temperature=0, json_mode=True)


def _build_openai_transcribe_client() -> Any:
    # Imported here, not at module level — same reasoning as _build_openai above.
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=os.environ["LLM_API_KEY"])


# LangChain has no unified speech-to-text model abstraction the way it does
# BaseChatModel, so main.py's /api/chat/transcribe can't go through
# build_chat_model(). This is the equivalent provider-keyed registry for that one
# non-chat call site, so provider-swapping still doesn't mean hunting through main.py.
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
