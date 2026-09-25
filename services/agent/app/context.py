"""Token-budgeted prompt assembly (architecture doc, Chat memory > Context-window
handling, p. 9). Priority order: system+tools (handled by tool binding in graph.py),
preferences, working set, current message, recent messages newest-first until the
budget is spent (never splitting a tool call from its result), rolling summary."""

import datetime
import json
import os
import re
from typing import Any

import tiktoken
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from .languages import SUPPORTED_LANGUAGES

# Matches the marker ChatPanel.tsx's insertReference() drops into the message box
# (`[transaction: ${id}]`) when the user clicks a table row's # reference button.
TRANSACTION_MARKER_RE = re.compile(r"\[transaction: ([^\]]+)\]")

MODEL_FOR_TOKENS = os.environ.get("LLM_MODEL", "gpt-4o")
CONTEXT_WINDOW = int(os.environ.get("LLM_CONTEXT_WINDOW", "128000"))
OUTPUT_RESERVE_FRACTION = 0.18
FULL_DETAIL_TURNS = 3  # most-recent N turns keep full tool-result content, not compact

try:
    _enc = tiktoken.encoding_for_model(MODEL_FOR_TOKENS)
except KeyError:
    _enc = tiktoken.get_encoding("cl100k_base")

SYSTEM_PROMPT = """You are the chat controller for a personal bookkeeping app. The \
transactions table is the system of record; you act on it only through your tools \
(add_transaction, edit_transaction, delete_transaction, delete_transactions_matching, \
query_transactions, get_exchange_rate, set_filter, export_transactions, extract_receipt). \
Never state a total or figure from memory or from the \
conversation summary — always call query_transactions/aggregates for numbers. Ask a \
clarifying question if amount or currency is missing before adding a transaction. \
get_exchange_rate returns a daily reference rate (not live tick-by-tick data) — never \
use it to convert or alter a transaction's actual stated amount/currency. \
add_transaction has no category argument on purpose: categorization is applied by the \
transactions service itself (past corrections first, then its own model), so every \
row is categorized consistently regardless of whether it came from chat or a receipt. \
A message may contain a "[transaction: <id>]" marker — the user clicked a reference \
button on that row in the table, so this id is known-good, straight from the table \
they're looking at right now. Use that exact id directly as transaction_id for \
edit_transaction/delete_transaction; don't resolve it by description/category or ask \
which transaction they mean, and don't repeat the raw marker back in your reply — refer \
to the transaction naturally (e.g. by its description or amount). You MUST actually \
call edit_transaction/delete_transaction with that id THIS turn, every single time — \
never reply that the id wasn't found, is invalid, or ask the user to check and resend \
it unless you actually called the tool and it returned a real error; claiming "not \
found" without ever calling the tool is a fabrication, not caution, especially since \
the marker means the id is already confirmed to exist. This applies fresh every \
single time, even if an earlier turn in this same conversation already replied "not \
found"/"couldn't find" for the exact same id: that earlier reply is not evidence the \
id is invalid — it was itself never backed by an actual tool call, so it proves \
nothing and must not be repeated or treated as settled. Call the tool for real this \
time instead of matching your own prior wording. \
"The last transaction"/"the most recent one"/"my latest expense" is a TEMPORAL \
reference to current table state, not a conversational one — always resolve it with a \
fresh query_transactions call (its results are already newest-first, so the first item \
is it) and use that id, even if you already have an id in mind from earlier in this \
conversation or the working set; the table can change between turns, and re-resolving \
is the only way to be sure you're acting on what's actually newest right now. Only use \
working-set/recently-referenced memory for a reference to something specific already \
discussed ("that one", "the coffee one"), never for "last"/"latest"/"most recent". \
Never report a delete/edit/add as successful unless the tool result actually confirms \
it — if it returns an error (e.g. transaction not found), tell the user it failed and \
why, then retry only if you can now resolve the right id; a wrong or stale id silently \
failing and being reported as success is worse than saying you couldn't find it. \
To delete more than one transaction — "delete all", "clear the table", any filtered \
bulk delete — use delete_transactions_matching, never delete_transaction in a loop over \
query_transactions results, since that tool only ever returns one page and would leave \
transactions behind. Always confirm with the user what will be deleted before calling \
delete_transactions_matching. Receipt line items are proposals only: \
extract_receipt never writes to the table; a card showing the proposed rows appears \
right below your reply, and the user edits or confirms it there before anything is \
saved. A "[uploaded receipt: <path>]" marker in the user's message means you MUST \
call extract_receipt with that exact path THIS turn — every single time, even if an \
earlier upload in this same conversation looked similar or produced the same-looking \
result. Never describe a "proposed transaction" (amounts, category, date) without \
having actually called extract_receipt in this turn and using its real result: \
copying or re-describing an earlier extraction instead of calling the tool again \
produces no proposal at all (there's nothing for the user to see or confirm) while \
looking to them like it worked, which is worse than a visible failure. If \
extract_receipt returns an error, say so — don't paper over it with a fabricated- \
looking but fake summary. After a successful extraction, reply with ONLY one short \
sentence naming the date, then stop — nothing else, no matter how tempting it is to \
be thorough: e.g. exactly "Extracted your receipt from 2026-09-25 — you can edit or \
confirm it below." (substitute the real date). Do NOT add a numbered or bulleted list \
of the items, do NOT restate any amount/category/description, do NOT add a closing \
line like "let me know if you need anything else" — the card right below your reply \
already shows every item/amount/category, so restating them is pure noise, not \
helpfulness, and padding the message with them is a mistake even if it feels more \
complete or polite. \
The table has no filter or edit controls of its own — every filter change \
and edit must go through your tools, including clearing a filter: call set_filter with \
no arguments, never just say it's cleared without calling it. The table's default view \
is the last 30 days, so after clearing, describe it that way (e.g. "back to the last \
30 days") rather than "everything"/"all transactions". Same rule for exports: you \
must call export_transactions every time, even right after a previous export in this \
same conversation — never claim a file was exported without calling it this turn, \
that produces no file and misleads the user. Keep replies short and concrete."""


def count_tokens(text: str) -> int:
    return len(_enc.encode(text or ""))


def _content_json(row) -> dict:
    c = row["content"]
    return json.loads(c) if isinstance(c, str) else c


def _compact_json(row) -> dict | None:
    c = row["compact"]
    if c is None:
        return None
    return json.loads(c) if isinstance(c, str) else c


def compact_tool_result(tool_name: str, result: dict) -> dict:
    """Deterministic, cheap compaction for a tool result — no LLM call. Used once a
    tool message ages out of the most-recent turns."""
    if tool_name == "query_transactions" and isinstance(result.get("items"), list):
        items = result["items"]
        return {"summary": f"{tool_name}: {len(items)} rows returned, ids stored"}
    if tool_name == "add_transaction" and "id" in result:
        return {"summary": f"added transaction {result['id']}"}
    if tool_name == "extract_receipt" and isinstance(result.get("items"), list):
        return {"summary": f"extracted {len(result['items'])} receipt line items (proposed, not saved)"}
    text = json.dumps(result)
    return {"summary": text[:200] + ("..." if len(text) > 200 else "")}


def _row_to_message(row, full_detail: bool) -> BaseMessage:
    content = _content_json(row)
    role = row["role"]

    if role == "user":
        return HumanMessage(content=content.get("text", ""))

    if role == "assistant":
        tool_calls = content.get("tool_calls") or []
        return AIMessage(content=content.get("text", ""), tool_calls=tool_calls)

    if role == "tool":
        compact = _compact_json(row)
        if not full_detail and compact:
            payload = compact
        else:
            payload = content.get("result", content)
        return ToolMessage(
            content=json.dumps(payload, default=str),
            tool_call_id=content.get("tool_call_id", ""),
            name=content.get("name"),
        )

    raise ValueError(f"unknown message role: {role}")


def _group_into_turns(rows: list) -> list[list]:
    """Groups oldest-first rows into turns: a user message starts a new turn; the
    assistant/tool messages that follow belong to it. Keeps a tool call and its
    result in the same turn so trimming never separates them."""
    turns: list[list] = []
    current: list = []
    for row in rows:
        if row["role"] == "user" and current:
            turns.append(current)
            current = []
        current.append(row)
    if current:
        turns.append(current)

    # `rows` is a raw row-count window (chat_db.recent_messages LIMIT), which has no
    # notion of turn boundaries — it can start mid-turn, e.g. on a tool-result message
    # whose assistant tool_calls message fell just outside the limit. Sending an
    # orphaned tool message with no preceding tool_calls message breaks OpenAI's
    # message-order validation, so drop that incomplete leading fragment.
    if turns and turns[0][0]["role"] != "user":
        turns = turns[1:]
    return turns


def build_context(
    thread: dict,
    preferences: dict | None,
    recent_rows: list,  # oldest-first, from chat_db.recent_messages
    current_user_text: str,
    current_images: list[str] | None = None,
) -> list[AnyMessage]:
    budget = int(CONTEXT_WINDOW * (1 - OUTPUT_RESERVE_FRACTION))
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

    turns = _group_into_turns(recent_rows)
    selected: list[list] = []
    for i, turn in enumerate(reversed(turns)):
        full_detail = i < FULL_DETAIL_TURNS
        turn_tokens = 0
        rendered = []
        for row in turn:
            msg = _row_to_message(row, full_detail)
            rendered.append(msg)
            turn_tokens += count_tokens(str(msg.content))
        if used + turn_tokens > budget:
            break
        selected.append(rendered)
        used += turn_tokens
    selected.reverse()

    messages: list[AnyMessage] = [SystemMessage(content=sys_text)]
    for turn in selected:
        messages.extend(turn)

    if current_images:
        content_blocks: list[str | dict[str, Any]] = [{"type": "text", "text": current_user_text}]
        for url in current_images:
            content_blocks.append({"type": "image_url", "image_url": {"url": url}})
        messages.append(HumanMessage(content=content_blocks))
    else:
        messages.append(HumanMessage(content=current_user_text))

    return messages
