# Architecture

## At a glance

```
Browser ── Caddy (:8080) ──┬── /api/chat/*         → agent (FastAPI + LangGraph, SSE)
                            ├── /api/transactions/* → transactions (FastAPI)
                            ├── /gcs/*              → fake-gcs (receipt storage)
                            └── / (everything else) → web (Vite dev server + HMR)

agent ──HTTP, forwards caller's own JWT──► transactions ──► Postgres "bookkeeping" (RLS)
agent ──asyncpg───────────────────────────────────────────► Postgres "chat" (RLS)
agent ──LLM provider (chat + vision)──► primary model, with a fallback model on failure
agent ──Firebase Auth emulator──► verify_id_token (never skipped, even locally)
agent ──currency-api (jsdelivr CDN)──► exchange-rate lookups (no key, free)
```

The agent never impersonates a user: every call it makes to the transactions service
forwards the caller's own verified JWT, so Postgres row-level security
(`current_setting('app.uid')`) is the real isolation boundary, not application code —
the agent has no elevated identity of its own.

### Backend — two independent FastAPI services, each owning its own Postgres database

- **`services/transactions`** — the system of record.
  - `routers/transactions/` — keyset-paginated `GET /transactions` (`list.py`), batch
    `POST /transactions` (`create.py`), `PATCH /transactions/{id}` (`patch.py`,
    includes rescaling `amount_minor` if just the currency changes), single and
    filtered-bulk `DELETE` (`delete.py` — the bulk one exists because the agent's
    per-id delete loop only ever saw one page of results, so "delete all my
    transactions" was silently deleting just the first 50).
  - `routers/aggregates.py` — sums by currency/category/month, same filter set as the
    list endpoint.
  - `helpers/` — pure helpers:
    - `filters.py` — the filter-clause builder shared by `list.py`, `delete.py`, and
      `aggregates.py` (currency/category/type/date range/amount range/description →
      SQL `WHERE` clause), so the three don't drift out of sync with each other.
    - `money.py` — amounts are stored as integer minor units (`amount_minor`), scaled
      by each currency's ISO 4217 exponent (most currencies 2 decimals, some 0 or 3),
      so aggregation never touches floating point.
    - `serializers.py` — row → API JSON shape.
  - `storage/` — the connection pool and the SQL-backed modules:
    - `pool.py` — the connection pool; `uid_conn()` sets `app.uid` for row-level
      security.
    - `corrections.py` — the user's category corrections, keyed on the normalized
      description (no merchant field): saved when the user changes a category (table
      edit, or a receipt's proposed one), listed via `GET /corrections` for the
      agent's categorizer. This service calls no LLM.
    - `idempotency.py` — every mutating endpoint requires an `Idempotency-Key`
      header; the same key with the same request body replays the stored response, a
      different body gets a 409.
  - `models/` — Pydantic request/response models, organized by domain
    (`transactions.py`, `aggregates.py`, `corrections.py`, `api.py`) — every FastAPI
    endpoint validates through one of these via `response_model=` rather than
    returning a plain dict.
- **`services/agent`** — a multi-agent LangGraph graph, built per request in
  `workflows/` (no checkpointer: it runs once per HTTP request and history lives in
  the chat DB, not graph state; hand-built `StateGraph`s rather than
  `langgraph.prebuilt`, so the emitted SSE event shape is fully controlled):

  ```
  chat (main graph)
  ├─ router ─ an upload? ──► receipt_workflow ── the user typed a note? ──► receipt_followup
  │                            load → read → categorize → propose → report
  └─ otherwise ───────────► assistant (call_model ⇄ tools)
  categorize (shared subgraph): load_corrections → classify
     used by receipt_workflow and by the assistant's add_transaction
  ```

  - `router` — plain code, no model call: routes on whether the turn has an upload.
  - `receipt_workflow` — deterministic: download the image, read it with the vision
    prompt (the user's note, e.g. "this was yesterday", goes into that prompt), run
    the `categorize` subgraph, build the proposal and send the card. It records itself
    in history as an `extract_receipt` tool call, so later turns can refer to it. With
    no note, it also sends a fixed reply (a notice key the web app translates), so
    no chat model is called.
  - `receipt_followup` — the assistant, specialized for the turn after a receipt:
    its own instructions (confirm the card, answer the question) and **read-only**
    tools. The receipt is saved only when the user confirms the card. With add/edit/
    delete in reach, the model was seen saving it itself, then "editing" it.
  - `assistant` — the general bookkeeping agent with every tool below.
  - `categorize` — corrections first, then one model call for the rest
    (`services/categorize.py`).
  - `integrations/` — `llm.py`: a primary model with a one-shot fallback to a secondary model on
    failure/timeout, a 60s overall call timeout, per-purpose output-token caps, and an
    in-process concurrency cap; `tracing.py`: LangSmith run tags per turn;
    `tasks.py`: Cloud Tasks for the rolling summary (an in-process stand-in when
    `TASKS_MODE=local`).
  - `workflows/` — `main.py` (router and wiring), `receipt.py`, `categorize.py`,
    `assistant.py` (the model ⇄ tools loop), `state.py` (the graphs' state types).
    The nodes talk to the outside through custom events (`ui_event`, `tool_record`,
    `notice`) that `chat/streaming.py` turns into SSE.
  - `prompts/` — `assistant.py` (the system prompt, plus the receipt follow-up's
    instructions), `receipt.py` (vision extraction), `categorize.py` (category
    definitions and matching rules), `summarize.py` (rolling summary).
  - `services/` — the single model jobs: `receipts.py` (reading a receipt with the
    vision model), `categorize.py` (the categorizer), `summarize.py` (the rolling
    summary).
  - `helpers/` — pure helpers: `images.py` (PDF render and downscale before the
    vision call), `receipts.py` (merchant folding, majority category), `dates.py`
    (the user's "today"), `serializers.py` (chat DB rows → API models),
    `filters.py` (tool filter params), `tool_schema.py` (the compact tool schema the
    model gets on every call: collapsed docstrings, plain optional params).
  - `storage/` — `chat_db.py` (the chat database: pool and queries), `quotas.py`
    (daily usage limits) and `bucket.py` (receipt files in Cloud Storage).
  - `constants/` — `categories.py` (the built-in category list; the web app has the
    same keys) and `languages.py` (the supported languages).
  - `context/` — prompt assembly: `tokens.py` (token
    counting, `HISTORY_TOKEN_BUDGET`), `messages.py` (turn grouping + per-row
    rendering, older tool results compacted), and `__init__.py`'s `build_context()`
    (preferences, working set, rolling summary, then unsummarized turns newest-first
    within the budget, never splitting a tool call from its result) and
    `first_kept_seq()` (where the kept history starts, so trimmed rows get summarized).
  - `chat/` — `runner.py` runs one chat turn end to end (save the message, build
    context, run the main graph, persist, turn failures into error events), so
    `routers/chat.py`'s `/api/chat/chat` is just the HTTP layer; `streaming.py` runs one graph
    turn via `astream_events` and translates it into the SSE wire format;
    `turns.py` decides whether a `[transaction: <id>]` marker turn
    actually called the tool it claimed to, records a fallback assistant message when
    a turn fails outright (so the thread never ends up with an unanswered user message
    poisoning the next turn's context), persists a completed turn (assistant message,
    tool results, working set, quota), and triggers summarization by message count.
  - `tools/` — see the table below; `crud.py`/`currency.py`/`utility.py` each build
    one group of tools, `__init__.py`'s `build_tools()` composes them per request
    (and `MUTATING_TOOLS` names the ones the follow-up agent doesn't get).
  - `models/` — Pydantic models by domain (`turns.py` — per-turn state shared
    between `chat/streaming.py` and `chat/turns.py`; `message_content.py` — the
    `messages.content` DB column's shape, by role; `api.py` — FastAPI request/
    response bodies; `tool_results.py` — every tool's return shape). Every LangChain
    tool constructs one of these and calls `.model_dump()` right before returning,
    rather than building a raw dict inline.

### Agent tools

| Tool | Purpose |
|---|---|
| `add_transaction` | Add an expense or income. No category argument — it's categorized automatically (corrections first, then the categorizer). |
| `edit_transaction` | Edit fields on an existing transaction by id. Resolves an explicit `[transaction: <id>]` marker with priority. |
| `delete_transaction` | Delete one transaction by id. |
| `delete_transactions_matching` | Delete every transaction matching a filter (or all of them) in one server-side operation. |
| `query_transactions` | List or (`aggregate=true`) sum transactions matching a filter, including a description substring search. |
| `get_exchange_rate` | Daily reference rate between two currencies, for the user's reference only. |
| `get_total_in_currency` | Sum transactions (optionally filtered) and convert the result into one target currency — the multiply-and-sum happens in code, never left to the model to compute in its reply. |
| `set_filter` | Drive the transactions table's filter from chat. |
| `export_transactions` | Signal the UI to build and attach a CSV of the table's current view. |

Receipts aren't a tool: the `receipt_workflow` reads an upload into one proposed (never
written) row, with its total, a summarized description and the majority category of
its items.

### Frontend
React 19 + Vite 6 + TypeScript. TanStack Query for server cache, invalidated by the
SSE `table_changed` event, and refetched on window focus and every 60 s while focused
(how other tabs' and devices' changes show up). Tailwind CSS v4
for styling (dark mode via a class toggle + `@custom-variant`, RTL via logical
properties), `lucide-react` for icons, `@microsoft/fetch-event-source` for SSE (plain
`EventSource` can't send an auth header or a POST body).

Key files: `src/lib/i18n/` (`locales/<lang>.ts` — one file per language, typed
against `en.ts` so a missing key is a compile error; `LanguageProvider`, RTL/`dir`
handling, `useTranslation()`),
`src/components/ChatPanel.tsx` (the chat pane — composes the pieces below, and exposes
an imperative `insertReference` handle so the table's `#` button can drop a marker
into the chat input), `src/lib/useChatStream.ts` (sends a turn and turns its SSE
events into UI state), `src/lib/useThreadMessages.ts` (thread history + paging back),
`src/lib/useVoiceRecorder.ts` (press-and-hold voice input), `src/lib/chat.ts` (chat
message/receipt types and pure helpers), `src/components/ChatComposer.tsx` (message
box with the upload and mic buttons), `src/components/ReceiptProposalCard.tsx` (the
editable receipt proposal), `src/components/TransactionsTable.tsx` (every column editable
in place — date/category/amount/currency/description — via `lib/api.ts`'s
`patchTransaction`/`deleteTransaction`), `src/components/ConfirmDialog.tsx` (a
styled `window.confirm()` stand-in, used by the delete button above).

### Local infrastructure
- **`firebase/`** — a container running the Firebase Auth emulator plus the Emulator
  UI (`firebase-tools`), so sign-in works with zero real Google Cloud project.
- **`fake-gcs-server`** — an in-memory GCS-compatible server for receipt storage;
  `services/agent/app/storage/bucket.py` returns a signed GCS URL in production or a direct
  local upload URL here, and the frontend can't tell the difference.
- **Caddy** (`Caddyfile`) — reverse proxy in front of everything, same routing shape
  as the production design's Firebase Hosting rewrites, with SSE responses flushed
  immediately instead of buffered.
- **Postgres 16** — two databases (`bookkeeping`, `chat`), each with its own
  least-privilege role and row-level security policy keyed off `app.uid`.
  `db/init/000_setup.sql` creates the second database and the roles on first boot;
  the schema comes from `db/migrations/`, applied by the one-shot `migrate` service
  before the app services start.
