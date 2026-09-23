# SMAKER.ai — bookkeeping chat

A B2C bookkeeping app: a chat pane driven by a LangGraph agent (OpenAI) sits next to a
transactions table. Two independent FastAPI services front two Postgres databases; a
local Docker Compose stack stands in for every GCP piece the design targets (Firebase
Auth/Firestore, Cloud Storage, Cloud Tasks, Cloud Run, Hosting rewrites), so the only
thing that talks to the real internet is the OpenAI API and a free public
exchange-rate lookup.

## Quickstart

1. `cp .env.example .env` and set `LLM_API_KEY` (an OpenAI key).
2. `mkdir -p gcs/receipts-local`
3. `docker compose up --build` (or `docker-compose up --build` on the standalone CLI).
4. Open `http://localhost:8080` and sign in — the Auth emulator shows a fake Google
   account picker; add any test account, no real Google account needed.
5. Reset everything with `docker compose down -v` (also drops the Postgres volume).

**First boot is slow to become responsive (15–30s):** the `agent` container imports the
full LangGraph/LangChain/OpenAI/Langfuse stack at startup, and `firebase-tools`
downloads the Firestore emulator JAR on first run. Watch `docker compose logs -f` for
"Uvicorn running" (both FastAPI services) and "All emulators ready" (Firebase).

Useful side doors while it's running:
- `http://localhost:4000` — Firebase Emulator UI (inspect signed-in users/tokens)
- `localhost:5432` — Postgres (`owner`/`owner_pw`, databases `bookkeeping` and `chat`)

Two of the four app containers (`agent`, `transactions`) bake their code into the
image at build time — editing their source requires `docker compose up -d --build
<service>` to take effect, a plain `restart` won't pick it up. `web` bind-mounts
`./web` and runs Vite's dev server, so frontend edits hot-reload immediately.

## What it does

- **Chat-driven transactions.** Add, edit, delete (one at a time or bulk by filter),
  and query transactions in natural language. The agent resolves a vague reference
  ("that one", "the coffee one") from transactions already touched this conversation,
  or searches the whole table by description text ("the bagel one") when it isn't —
  or, unambiguously, from an explicit `#` reference button on any table row, which
  drops a `[transaction: <id>]` marker into the message box.
- **Analysis.** "How much did I spend on dining last month?" always calls a real
  aggregates endpoint — the model is instructed to never state a number from memory
  or from the conversation summary.
- **Filtering.** "Show USD expenses over 100 from last month" drives the table's
  filter directly; the table has no filter controls of its own, everything routes
  through chat.
- **CSV export.** "Export this view" builds a CSV client-side from the table's current
  filter and drops it into the chat as a clickable file attachment.
- **Voice input.** Record a message with the mic button; it's transcribed
  (Whisper) server-side and dropped into the message box for you to review or edit
  before sending — same as typing it, nothing is sent automatically.
- **Receipts.** Upload a photo or PDF; GPT-4o vision extracts line items and
  categorizes each one, and the UI shows editable proposed rows — nothing is written
  until you confirm. There's no separate merchant field: a merchant/place name, when
  identifiable, is folded straight into the item's description. Category corrections
  (made via chat or by editing a proposed row) are learned per normalized description
  and reused on future similar purchases, with an LLM fallback that recognizes
  near-duplicate wording it doesn't match exactly.
- **Exchange rates.** "What's 50 USD in EUR?" calls a free, keyless daily reference
  rate covering 300+ currencies — explicitly a reference rate, never used to silently
  convert or alter a transaction's actual stated
  amount/currency.
- **Live updates.** A same-tab SSE event updates the table instantly; a Firestore
  `sync/{uid}` document signals other open tabs/devices to refetch (each client tags
  its own writes with a client ID so it doesn't re-trigger itself).
- **Chat memory.** Threads persist in Postgres and survive reloads/devices. Once a
  thread's message history exceeds the context window's recent-message budget, the
  overflow folds into a rolling per-thread summary (a background task, off the hot
  path) that records intents/decisions, never specific amounts, since a lossy summary
  must never be trusted for numbers.
- **Localization.** Ten languages — English, Spanish, Indonesian, French, German,
  Portuguese, Hebrew, Russian, Ukrainian, Arabic — selectable per account. Not just UI
  strings: the chat model is instructed to reply in the selected language regardless
  of what language the user types in, receipt line items get translated into it, the
  category column's built-in labels are translated for display (the stored/matched
  value stays the English key), and Hebrew/Arabic flip the whole layout to RTL via
  logical CSS properties (not just a `dir` attribute flip).
- **Dark/light theme**, persisted locally, no flash of the wrong theme on reload.
- Per-user daily quotas (chat turns, receipts, tokens — configurable via
  `DAILY_TURN_LIMIT`/`DAILY_RECEIPT_LIMIT`) and optional Langfuse tracing; every
  Langfuse call site checks its keys are set and no-ops otherwise, so an empty `.env`
  still runs the full app.

## Architecture at a glance

```
Browser ── Caddy (:8080) ──┬── /api/chat/*         → agent (FastAPI + LangGraph, SSE)
                            ├── /api/transactions/* → transactions (FastAPI)
                            ├── /gcs/*              → fake-gcs (receipt storage)
                            └── / (everything else) → web (Vite dev server + HMR)

agent ──HTTP, forwards caller's own JWT──► transactions ──► Postgres "bookkeeping" (RLS)
agent ──asyncpg───────────────────────────────────────────► Postgres "chat" (RLS)
agent ──OpenAI (chat + gpt-4o vision)──► primary model, with a fallback model on failure
agent ──Firebase Auth emulator──► verify_id_token (never skipped, even locally)
agent ──Firestore emulator──► sync/{uid} live-update signal
agent ──currency-api (jsdelivr CDN)──► exchange-rate lookups (no key, free)
```

The agent never impersonates a user: every call it makes to the transactions service
forwards the caller's own verified JWT, so Postgres row-level security
(`current_setting('app.uid')`) is the real isolation boundary, not application code —
the agent has no elevated identity of its own.

### Backend — two independent FastAPI services, each owning its own Postgres database

- **`services/transactions`** — the system of record.
  - `routers/transactions.py` — keyset-paginated `GET/POST /transactions`, batch
    create, `PATCH`/single `DELETE`, and a filtered bulk `DELETE` (added because the
    agent's per-id delete loop only ever saw one page of results — "delete all my
    transactions" was silently deleting just the first 50). Filters include a
    case-insensitive description substring match.
  - `routers/aggregates.py` — sums by currency/category/month.
  - `categorize.py` — corrections-first, LLM-fallback categorization, keyed on the
    normalized transaction description (no merchant field).
  - `money.py` — amounts are stored as integer minor units (`amount_minor`), scaled
    by each currency's ISO 4217 exponent (most currencies 2 decimals, some 0 or 3),
    so aggregation never touches floating point.
  - `idempotency.py` — every mutating endpoint requires an `Idempotency-Key` header;
    the same key with the same request body replays the stored response, a different
    body gets a 409.
- **`services/agent`** — a LangGraph `StateGraph` (not `langgraph.prebuilt`'s agent,
  so the emitted SSE event shape is fully controlled): a `call_model` node bound to
  the tools below, conditionally routed to a `ToolNode`, looping back until the model
  stops calling tools. No checkpointer — the graph runs once per HTTP request and
  history lives in the chat DB, not graph state.
  - `llm.py` — a primary model with a one-shot fallback to a secondary model on
    failure/timeout, a 60s overall call timeout, and an in-process concurrency cap.
  - `context.py` — token-budgeted prompt assembly: system prompt, preferences,
    working set (recently-touched transactions), the rolling summary if present, then
    as many recent turns as fit the budget, newest-first, never splitting a tool call
    from its result.
  - `tools.py` — see the table below.
  - `quotas.py` / `summarize.py` / `tasks.py` — daily usage limits, the rolling
    summary job, and the in-process stand-in for Cloud Tasks (`TASKS_MODE=local`).

### Agent tools

| Tool | Purpose |
|---|---|
| `add_transaction` | Add an expense or income. No category argument — the transactions service categorizes it. |
| `edit_transaction` | Edit fields on an existing transaction by id. Resolves an explicit `[transaction: <id>]` marker with priority. |
| `delete_transaction` | Delete one transaction by id. |
| `delete_transactions_matching` | Delete every transaction matching a filter (or all of them) in one server-side operation. |
| `query_transactions` | List or (`aggregate=true`) sum transactions matching a filter, including a description substring search. |
| `get_exchange_rate` | Daily reference rate between two currencies, for the user's reference only. |
| `set_filter` | Drive the transactions table's filter from chat. |
| `export_transactions` | Signal the UI to build and attach a CSV of the table's current view. |
| `extract_receipt` | Vision-extract line items from an uploaded receipt image/PDF, categorize each, and propose (never write) rows. |

### Frontend
React 19 + Vite 6 + TypeScript. TanStack Query for server cache, invalidated by the
same-tab SSE `table_changed` event or the cross-tab Firestore signal. Tailwind CSS v4
for styling (dark mode via a class toggle + `@custom-variant`, RTL via logical
properties), `lucide-react` for icons, `@microsoft/fetch-event-source` for SSE (plain
`EventSource` can't send an auth header or a POST body).

Key files: `src/lib/i18n.tsx` (translation dictionaries, RTL/`dir` handling,
`useTranslation()`), `src/lib/sync.ts` (the Firestore live-update listener),
`src/components/ChatPanel.tsx` (message list + SSE streaming input, exposes an
imperative `insertReference` handle so the table's `#` button can drop a marker into
the chat input), `src/components/TransactionsTable.tsx`.

### Local infrastructure
- **`firebase/`** — a container running the Auth and Firestore emulators plus the
  Emulator UI (`firebase-tools`), so sign-in and the live-update signal work with zero
  real Google Cloud project.
- **`fake-gcs-server`** — an in-memory GCS-compatible server for receipt storage;
  `services/agent/app/storage.py` returns a signed GCS URL in production or a direct
  local upload URL here, and the frontend can't tell the difference.
- **Caddy** (`Caddyfile`) — reverse proxy in front of everything, same routing shape
  as the production design's Firebase Hosting rewrites, with SSE responses flushed
  immediately instead of buffered.
- **Postgres 16** — two databases (`bookkeeping`, `chat`), each with its own
  least-privilege role and row-level security policy keyed off `app.uid`, created by
  `db/init/001_schema.sql` and `002_chat.sql` on first boot.

## Environment variables (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `LLM_API_KEY` | yes | OpenAI API key |
| `LLM_MODEL` | no | default `gpt-4o` — chat + receipt vision |
| `LLM_FALLBACK_MODEL` | no | default `gpt-4o-mini` |
| `LLM_SUMMARY_MODEL` | no | default `gpt-4o-mini` — rolling chat summary |
| `TRANSCRIBE_MODEL` | no | default `whisper-1` — voice-input transcription |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | no | tracing no-ops if unset |

`DAILY_TURN_LIMIT` (default 200) and `DAILY_RECEIPT_LIMIT` (default 50) are also
overridable but aren't in `.env.example` since the defaults are fine for local dev.
Everything else — database URLs, emulator hosts, storage mode — is wired directly in
`docker-compose.yml` and doesn't need to be set by hand.

## Layout

```
db/init/                     Postgres schema + RLS policies (bookkeeping DB, chat DB)
firebase/                    Auth + Firestore emulator container
gcs/receipts-local/          fake-gcs-server's on-disk backing store
services/transactions/       FastAPI — owns Postgres, CRUD, categorization, idempotency
  app/routers/                 transactions.py, aggregates.py, categorize.py
  app/categorize.py            corrections-first, LLM-fallback categorization
  app/money.py                 decimal string <-> integer minor-unit conversion
services/agent/               FastAPI + LangGraph — owns chat DB, SSE chat, tools
  app/tools.py                  add/edit/delete_transaction(s), query, set_filter,
                                 export, extract_receipt, get_exchange_rate
  app/context.py                system prompt + token-budgeted context assembly
  app/languages.py              supported chat/receipt-translation languages
  app/graph.py                  the LangGraph StateGraph (model ⇄ tools loop)
web/                          React + Vite + TypeScript — chat pane + transactions table
  src/lib/i18n.tsx               translation dictionaries, RTL handling, useTranslation()
  src/lib/sync.ts                Firestore cross-tab live-update listener
  src/components/                ChatPanel, TransactionsTable, ReceiptModal, Tooltip, …
Caddyfile                     Reverse proxy — same routing shape as Firebase Hosting rewrites
docker-compose.yml
```

## Known gaps

- `get_exchange_rate` returns a *daily* reference rate, not live tick-by-tick market
  data.
- Production-only concerns (App Check, an external load balancer, real Cloud Tasks,
  an eval gate, Terraform/CI, Cloud Run autoscaling) are intentionally out of scope —
  this is a local dev stack, not a deployable one.
