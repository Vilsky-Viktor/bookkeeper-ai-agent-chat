# SMAKER.ai — bookkeeping chat

A B2C bookkeeping app: a chat pane (LangGraph agent, OpenAI) next to a transactions
table, backed by two FastAPI services over Postgres. Originally scaffolded from
`bookkeeping-chat-gcp-architecture.pdf`'s local dev setup — every GCP piece has a
container or emulator stand-in, so the only external dependency is the OpenAI API.

## Quickstart

1. `cp .env.example .env` and set `LLM_API_KEY` (an OpenAI key).
2. `mkdir -p gcs/receipts-local`
3. `docker compose up --build` (or `docker-compose up --build` on the standalone CLI).
4. Open `http://localhost:8080` and sign in — the Auth emulator shows a fake Google
   account picker; add any test account, no real Google account needed.
5. Reset everything with `docker compose down -v` (drops the Postgres volume too).

**First boot is slow to become responsive (15–30s):** the `agent` container imports the
full LangGraph/LangChain/OpenAI/Langfuse stack at startup, and `firebase-tools`
downloads the Firestore emulator JAR on first run. Watch `docker compose logs -f` for
"Uvicorn running" (both FastAPI services) and "All emulators ready" (Firebase).

Useful side doors while it's running:
- `http://localhost:4000` — Firebase Emulator UI (inspect signed-in users/tokens)
- `localhost:5432` — Postgres (`owner`/`owner_pw`, databases `bookkeeping` and `chat`)

## What it does

- **Chat-driven transactions.** Add, edit, delete (single or bulk-filtered), and query
  transactions in natural language. The agent resolves "that one"/"the coffee one"
  from recently-referenced transactions or the current thread — or from an explicit
  `#` reference button on any table row, which drops an exact `[transaction: <id>]`
  marker into the message box so there's no ambiguity.
- **Analysis.** "How much did I spend on dining last month?" calls a real
  aggregates endpoint — the model is instructed to never state a number from memory.
- **Filtering.** "Show USD expenses over 100 from last month" drives the table's
  filter directly; the table has no filter controls of its own.
- **CSV export.** "Export this view" builds a CSV client-side from the table's current
  filter and drops it into the chat as a clickable attachment.
- **Receipts.** Upload a photo or PDF; GPT-4o vision extracts line items, categorizes
  each one, and shows editable proposed rows — nothing is written until you confirm.
  Category corrections you make (via chat or on a receipt) are learned per normalized
  description and reused on future similar purchases, with an LLM fallback for
  near-duplicate wording it doesn't match exactly.
- **Exchange rates.** "What's 50 USD in EUR?" calls a free, keyless ECB daily-rate
  lookup (Frankfurter.app) — explicitly a reference rate, never used to silently alter
  a transaction's actual stated amount/currency.
- **Live updates.** A same-tab SSE event updates the table instantly; a Firestore
  `sync/{uid}` doc signals other tabs/devices to refetch.
- **Chat memory.** Threads persist in Postgres and survive reloads/devices; older
  messages fold into a rolling per-thread summary once the token budget is exceeded.
- **Localization.** Nine languages (English, Spanish, Indonesian, French, German,
  Portuguese, Hebrew, Russian, Ukrainian, Arabic), selectable per account. It's not
  just UI strings: the chat model replies in the selected language, receipt line
  items get translated into it, and Hebrew/Arabic flip the whole layout to RTL via
  logical CSS properties, not just a `dir` flag.
- **Dark/light theme**, persisted locally, no flash on reload.
- Per-user daily quotas (turns/receipts/tokens) and optional Langfuse tracing — every
  call site checks the keys are set and no-ops otherwise, so an empty `.env` still
  runs the full app.

## Layout

```
db/init/                     Postgres schema + RLS policies (bookkeeping DB, chat DB)
firebase/                    Auth + Firestore emulator container
services/transactions/       FastAPI — owns Postgres, CRUD, categorization, idempotency
  app/routers/                 transactions.py (CRUD + bulk delete), categorize.py
  app/categorize.py            corrections-first, LLM-fallback categorization
  app/money.py                 decimal string <-> integer minor-unit conversion
services/agent/               FastAPI + LangGraph — owns chat DB, SSE chat, tools
  app/tools.py                  add/edit/delete_transaction(s), query, set_filter,
                                 export, extract_receipt, get_exchange_rate
  app/context.py                system prompt + token-budgeted context assembly
  app/languages.py              supported chat/receipt-translation languages
web/                          React + Vite + TypeScript — chat pane + transactions table
  src/lib/i18n.tsx               translation dictionaries, RTL handling, useTranslation()
  src/components/                ChatPanel, TransactionsTable, ReceiptModal, Tooltip, …
Caddyfile                     Reverse proxy — same routing shape as Firebase Hosting rewrites
docker-compose.yml
```

## Architecture at a glance

```
Browser ── Caddy (:8080) ──┬── / (everything else)        → web (Vite dev server)
                            ├── /api/chat/*                → agent (FastAPI + LangGraph)
                            ├── /api/transactions/*         → transactions (FastAPI)
                            └── /gcs/*                       → fake-gcs (receipt storage)

agent ──HTTP (user's JWT forwarded)──► transactions ──► Postgres (bookkeeping DB, RLS)
agent ──asyncpg────────────────────────────────────────► Postgres (chat DB, RLS)
agent ──OpenAI (chat + vision)──► gpt-4o / gpt-4o-mini
agent ──Firebase Auth emulator──► verify_id_token (never skipped, even locally)
agent ──Firestore emulator──► sync/{uid} live-update signal
```

The agent never impersonates a user — every call to the transactions service forwards
the caller's own verified JWT, so Postgres row-level security (keyed off
`current_setting('app.uid')`) is the actual isolation boundary, not application code.

### Frontend
React 19 + Vite 6 + TypeScript, TanStack Query for server cache (invalidated by the SSE
`table_changed` event in-tab, or the Firestore signal cross-tab), Tailwind CSS v4 for
styling, `lucide-react` for icons, `@microsoft/fetch-event-source` for SSE (plain
`EventSource` can't send an auth header or a POST body).

### Backend
Two independent FastAPI services, each owning its own Postgres database:
- **transactions** — the system of record. CRUD, keyset-paginated listing, aggregates,
  categorization (corrections table first, then an LLM classifier), idempotency-key
  replay on every mutating endpoint.
- **agent** — a LangGraph `StateGraph` (not `langgraph.prebuilt`, so the SSE event
  shape is fully controlled) running a model→tools→model loop per HTTP request. No
  checkpointer: the graph runs once per turn and history lives in the chat DB instead.

## Environment variables (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `LLM_API_KEY` | yes | OpenAI API key |
| `LLM_MODEL` | no | default `gpt-4o` — chat + receipt vision |
| `LLM_FALLBACK_MODEL` | no | default `gpt-4o-mini` |
| `LLM_SUMMARY_MODEL` | no | default `gpt-4o-mini` — rolling chat summary |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | no | tracing no-ops if unset |

Everything else (database URLs, emulator hosts, storage mode) is wired directly in
`docker-compose.yml` for local dev and doesn't need to be set by hand.

## Known gaps

- `query_transactions` only supports the filters the architecture doc specifies
  (currency/category/type/date/amount) — no free-text search, so the agent can only
  resolve a vague reference ("the bagel one") from the current thread's recently
  touched transactions, not the whole table.
- The exchange-rate tool returns the ECB's *daily* reference rate, not live
  tick-by-tick market data.
- Production-only concerns (App Check, an external load balancer, real Cloud Tasks,
  an eval gate, Terraform/CI) are intentionally out of scope — this is a local dev
  stack, not a deployable one. See the architecture doc's "Production readiness"
  section for what that would add.
