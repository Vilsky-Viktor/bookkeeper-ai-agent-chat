"""The rolling-summary prompt (summarize.py)."""

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
