"""Rolling summary, off the hot path. Folds messages that fell out of the context window
into threads.summary with a cheap model, then advances summarized_through with a
compare-and-set so a redelivered task is a no-op."""

import json
import logging

from langchain_core.messages import HumanMessage

from ..integrations import llm
from ..prompts.summarize import SUMMARIZE_PROMPT
from ..storage import chat_db

log = logging.getLogger("summarize")


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
        response = await model.ainvoke(
            [HumanMessage(content=prompt)], config={"run_name": "summarize", "tags": ["summarize"]}
        )
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
