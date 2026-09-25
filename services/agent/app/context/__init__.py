"""Token-budgeted prompt assembly (architecture doc, Chat memory > Context-window
handling, p. 9). Priority order: system+tools (handled by tool binding in graph.py),
preferences, working set, current message, recent messages newest-first until the
budget is spent (never splitting a tool call from its result), rolling summary."""

import datetime
import json
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from ..languages import SUPPORTED_LANGUAGES
from . import messages, tokens
from .messages import TRANSACTION_MARKER_RE, compact_tool_result
from .prompts import SYSTEM_PROMPT
from .tokens import count_tokens

__all__ = ["build_context", "count_tokens", "compact_tool_result", "TRANSACTION_MARKER_RE"]


def build_context(
    thread: dict,
    preferences: dict | None,
    recent_rows: list,  # oldest-first, from chat_db.recent_messages
    current_user_text: str,
    current_images: list[str] | None = None,
) -> list[AnyMessage]:
    budget = int(tokens.CONTEXT_WINDOW * (1 - tokens.OUTPUT_RESERVE_FRACTION))
    used = 0

    sys_text = (
        SYSTEM_PROMPT + f'\nToday\'s date is {datetime.date.today().isoformat()}. Resolve "today",'
        ' "yesterday", "last month" etc. against this date, not your training cutoff.'
    )
    if preferences and preferences.get("default_currency"):
        sys_text += f"\nUser's default currency: {preferences['default_currency']}."
    language_name = SUPPORTED_LANGUAGES.get((preferences or {}).get("language") or "en", "English")
    sys_text += (
        f"\nAlways reply in {language_name}, regardless of what language the user writes in "
        "— this is the language set in their settings, and the whole interface (including receipt "
        "extraction) is shown in it."
    )
    working_set = thread.get("working_set")
    if isinstance(working_set, str):
        working_set = json.loads(working_set) if working_set else {}
    working_set = dict(working_set) if working_set else {}
    # A "[transaction: <id>]" marker's id must always appear in this list, even if it
    # fell off the working set's cap — otherwise its absence reads to the model as
    # evidence the id is invalid, which in practice overrode the marker-priority rule
    # elsewhere even with an explicit caveat added below saying this list is
    # incomplete (observed directly, repeatedly: a marker edit whose id was still in
    # this list succeeded immediately every time; the one whose id had been evicted
    # kept failing regardless of prompt wording). Injecting the id here — not just
    # arguing the model out of the doubt — is what actually fixed it.
    for marker_id in TRANSACTION_MARKER_RE.findall(current_user_text):
        working_set.setdefault(marker_id, "referenced in this message")
    if working_set:
        labels = "; ".join(f"{k}: {v}" for k, v in working_set.items())
        sys_text += (
            f"\nRecently referenced transactions (id: label): {labels}. This list is a "
            "capped, most-recent-first convenience cache (older entries silently drop off "
            "as new ones are added) — it is NOT the full set of valid transactions, and an "
            "id's absence from it is not evidence that id is wrong or doesn't exist. In "
            'particular, a "[transaction: <id>]" marker\'s id is valid whether or not it '
            "happens to appear here."
        )
    if thread.get("summary"):
        sys_text += f"\nSummary of earlier conversation: {thread['summary']}"

    used += count_tokens(sys_text)
    used += count_tokens(current_user_text)

    turns = messages._group_into_turns(recent_rows)
    selected: list[list] = []
    for i, turn in enumerate(reversed(turns)):
        full_detail = i < messages.FULL_DETAIL_TURNS
        turn_tokens = 0
        rendered = []
        for row in turn:
            msg = messages._row_to_message(row, full_detail)
            rendered.append(msg)
            turn_tokens += count_tokens(str(msg.content))
        if used + turn_tokens > budget:
            break
        selected.append(rendered)
        used += turn_tokens
    selected.reverse()

    result: list[AnyMessage] = [SystemMessage(content=sys_text)]
    for turn in selected:
        result.extend(turn)

    if current_images:
        content_blocks: list[str | dict[str, Any]] = [{"type": "text", "text": current_user_text}]
        for url in current_images:
            content_blocks.append({"type": "image_url", "image_url": {"url": url}})
        result.append(HumanMessage(content=content_blocks))
    else:
        result.append(HumanMessage(content=current_user_text))

    return result
