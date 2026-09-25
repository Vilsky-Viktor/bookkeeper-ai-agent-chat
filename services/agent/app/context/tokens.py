"""Token counting for build_context()'s budget."""

import os

import tiktoken

MODEL_FOR_TOKENS = os.environ.get("LLM_MODEL", "gpt-4o")
CONTEXT_WINDOW = int(os.environ.get("LLM_CONTEXT_WINDOW", "128000"))
OUTPUT_RESERVE_FRACTION = 0.18

try:
    _enc = tiktoken.encoding_for_model(MODEL_FOR_TOKENS)
except KeyError:
    _enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text or ""))
