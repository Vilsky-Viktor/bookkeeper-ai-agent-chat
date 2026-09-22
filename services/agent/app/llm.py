"""LLM call policy: timeouts, retries and a fallback model (architecture doc,
Scalability and resilience > LLM calls, p. 15). Retry-on-429/5xx with backoff+jitter is
handled by the OpenAI SDK's own max_retries; we add an overall timeout, an in-process
concurrency cap, and a one-shot fallback to a secondary model."""

import asyncio
import os

from langchain_openai import ChatOpenAI

CALL_TIMEOUT = 60.0
LLM_CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY", "40"))
_semaphore = asyncio.Semaphore(LLM_CONCURRENCY)

PRIMARY_MODEL = os.environ.get("LLM_MODEL", "gpt-4o")
FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o-mini")
SUMMARY_MODEL = os.environ.get("LLM_SUMMARY_MODEL", "gpt-4o-mini")


def _client(model: str, temperature: float = 0.2) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        api_key=os.environ["LLM_API_KEY"],
        timeout=CALL_TIMEOUT,
        max_retries=2,  # openai SDK: retries 429/5xx only, backoff+jitter, honors Retry-After
        temperature=temperature,
    )


def primary_model() -> ChatOpenAI:
    return _client(PRIMARY_MODEL)


def fallback_model() -> ChatOpenAI:
    return _client(FALLBACK_MODEL)


def summary_model() -> ChatOpenAI:
    return _client(SUMMARY_MODEL, temperature=0)


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
