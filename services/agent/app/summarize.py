"""Rolling summary, off the hot path (architecture doc, Chat memory > Context-window
handling, technique 3, p. 9). Folds messages that fell out of the context window into
threads.summary with a cheap model, then advances summarized_through with a
compare-and-set so a redelivered task is a no-op."""

import json
import logging

from langchain_core.messages import HumanMessage

from . import chat_db, llm

log = logging.getLogger("summarize")

SUMMARIZE_PROMPT = """You maintain a rolling summary of a bookkeeping chat, used as \
context for a future turn. Fold the new messages into the previous summary. Record \
intents and decisions ("user is reviewing September dining"), NOT specific amounts or \
totals as facts — those are re-queried from the database when needed, so a lossy \
summary must never be trusted for numbers. Keep it under 200 words.

Previous summary:
{previous_summary}

New messages to fold in:
{messages}

Write only the updated summary text, nothing else."""


def _render_message(row) -> str:
    content = row["content"]
    content = json.loads(content) if isinstance(content, str) else content
    role = row["role"]
    if role == "user":
        return f"user: {content.get('text', '')}"
    if role == "assistant":
        text = content.get("text", "")
        calls = content.get("tool_calls") or []
        call_desc = "; ".join(f"called {c.get('name')}" for c in calls)
        return f"assistant: {text} {('(' + call_desc + ')') if call_desc else ''}".strip()
    if role == "tool":
        return f"tool result ({content.get('name')}): {json.dumps(content.get('result', {}))[:200]}"
    return ""


async def run_summarize(uid: str, thread_id: str, through_seq: int) -> None:
    async with chat_db.uid_conn(uid) as conn:
        thread = await chat_db.get_thread(conn, uid, thread_id)
        if thread is None:
            return

        already_through = thread["summarized_through"]
        if already_through is not None and already_through >= through_seq:
            return  # redelivered task, already applied

        rows = await chat_db.messages_since(conn, uid, thread_id, already_through or 0)
        rows = [r for r in rows if r["seq"] <= through_seq]
        if not rows:
            return

        rendered = "\n".join(filter(None, (_render_message(r) for r in rows)))
        prompt = SUMMARIZE_PROMPT.format(previous_summary=thread["summary"] or "(none yet)", messages=rendered)

        model = llm.summary_model()
        response = await model.ainvoke([HumanMessage(content=prompt)])
        new_summary = response.content if isinstance(response.content, str) else str(response.content)

        await conn.execute(
            """
            UPDATE threads SET summary = $1, summarized_through = $2, updated_at = now()
            WHERE uid = $3 AND id = $4 AND (summarized_through IS NULL OR summarized_through < $2)
            """,
            new_summary,
            through_seq,
            uid,
            thread_id,
        )
    log.info("summarized thread %s through seq %s", thread_id, through_seq)
