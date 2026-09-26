"""Token counting for build_context()'s budget."""

import os

import tiktoken

MODEL_FOR_TOKENS = os.environ.get("LLM_MODEL", "gpt-4o-mini")
# Tokens of conversation history (not system prompt/tools/current message) sent per
# model call. Every call in a turn resends it, so this is a direct cost lever. The
# rolling summary covers whatever falls outside (see chat/turns.py), so trimming here
# never silently loses context.
HISTORY_TOKEN_BUDGET = int(os.environ.get("LLM_HISTORY_TOKEN_BUDGET", "6000"))

try:
    _enc = tiktoken.encoding_for_model(MODEL_FOR_TOKENS)
except KeyError:
    _enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text or ""))
