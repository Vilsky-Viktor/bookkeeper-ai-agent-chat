# SMAKER.ai — bookkeeping chat

A B2C bookkeeping app: a chat pane driven by a LangGraph agent sits next to a
transactions table. Two independent FastAPI services front two Postgres databases; a
local Docker Compose stack stands in for every GCP piece the design targets (Firebase
Auth, Cloud Storage, Cloud Tasks, Cloud Run, Hosting rewrites), so the only
thing that talks to the real internet is the LLM provider's API (OpenAI by default —
see [Swapping the LLM provider](docs/configuration.md#swapping-the-llm-provider)) and a free public exchange-rate lookup.

⭐ If you find this project useful, please consider giving it a star ⭐ — it helps a lot!

![SMAKER.ai screenshot](smaker-screenshot.png)

## Quickstart

1. `cp .env.example .env` and set `LLM_API_KEY` (an OpenAI key).
2. `make up` (or `docker compose up --build`).
3. Open `http://localhost:8080` and sign in — the Auth emulator shows a fake Google
   account picker; add any test account, no real Google account needed.
4. `make reset` deletes all local data (database, emulator accounts, receipts) after
   asking for confirmation.

`make` lists every task: `check` (format check, lint and tests for all three
projects), `logs`, `rebuild s=<service>`, `migrate`, `migration db=… name=…`,
`format`, `eval-chat`, `eval-categorize`. Data survives restarts: Postgres in a named
volume, emulator accounts in `firebase/emulator-data/`, receipts in `gcs/`.

**First boot is slow to become responsive (15–30s):** the `agent` container imports the
full LangGraph/LangChain/LangSmith stack at startup, and `firebase-tools` needs a
moment on first run. Watch `docker compose logs -f` for
"Uvicorn running" (both FastAPI services) and "All emulators ready" (Firebase).

Useful side doors while it's running:
- `http://localhost:4000` — Firebase Emulator UI (inspect signed-in users/tokens)
- `localhost:5432` — Postgres (`owner`/`owner_pw`, databases `bookkeeping` and `chat`)

All three app containers hot-reload: `web` bind-mounts `./web` and runs Vite's dev
server; `agent` and `transactions` bind-mount their `app/` folders and run uvicorn with
`--reload` (`uv run poe dev`). Edits take effect within seconds, no rebuild. Only a
dependency change (`pyproject.toml`/`uv.lock`) needs `docker compose up -d --build
--no-deps <service>`.

The Firebase Auth emulator keeps its test accounts in
`firebase/emulator-data/` (gitignored): imported on start, exported when the
container stops, so test users survive restarts and rebuilds. Delete the folder to
start clean.

Both Python services build from one shared `services/Dockerfile`: its `dev` target
is what `docker-compose.yml` uses (every dependency including dev tools, port 8000
matching the `Caddyfile`'s internal routing), and its final stage is the lean
production image CI builds for Cloud Run (no dev tools, non-root user, listens on
Cloud Run's injected `$PORT` — see [Deploying to GCP](docs/deployment.md)).

## What it does

- **Chat-driven transactions.** Add, edit, delete (one at a time or bulk by filter),
  and query transactions in natural language. The agent resolves a vague reference
  ("that one", "the coffee one") from transactions already touched this conversation,
  or searches the whole table by description text ("the bagel one") when it isn't —
  or, unambiguously, from an explicit `#` reference button on any table row, which
  drops a `[transaction: <id>]` marker into the message box. "Today", "yesterday" and
  receipt dates resolve in the user's own timezone: the browser sends it with each
  message and the agent computes the date from its own clock (`app/dates.py`).
- **Directly editable table.** Every column (date via a native date picker, category
  via a dropdown built from the same list the categorizer uses, amount,
  currency, description — full text on hover via a tooltip once it's truncated) is
  also editable in place, and each row has its own delete button, gated behind a
  custom confirmation dialog (`ConfirmDialog.tsx`, styled to match the rest of the
  app) since deleting is irreversible — chat isn't the only way to change a
  transaction, just the natural-language one.
- **Analysis.** "How much did I spend on dining last month?" always calls a real
  aggregates endpoint — the model is instructed to never state a number from memory
  or from the conversation summary.
- **Filtering.** "Show USD expenses over 100 from last month" drives the table's
  filter directly; the table has no filter controls of its own, everything routes
  through chat.
- **CSV export.** "Export this view" builds a CSV client-side from the table's current
  filter and drops it into the chat as a clickable file attachment.
- **Voice input.** Record a message with the mic button; it's transcribed
  server-side (`gpt-4o-mini-transcribe` by default) and dropped into the message box
  for you to review or edit before sending — same as typing it, nothing is sent
  automatically.
- **Receipts.** Upload a photo or PDF; the configured vision model (`gpt-4o` by
  default — see [Swapping the LLM provider](docs/configuration.md#swapping-the-llm-provider)) reads the receipt's grand total, date and
  merchant, plus a short summary and the names of the items bought. That becomes ONE
  proposed transaction for the total (per-item price splitting proved unreliable
  across real receipts). Its category is the one most of the items fall into: each
  item name goes through the same categorizer as chat adds, and the majority wins (a tie
  goes to whichever category appears first on the receipt). The UI shows the proposal
  as an editable row (description on its own line; category, amount and currency
  below) — nothing is written until you confirm. Confirming also records "saved N
  transactions" in the chat thread, so the message survives a reload and the model
  knows the receipt was saved. The category is a dropdown built from the same
  built-in list the categorizer uses. There's no separate merchant field: a merchant name, when identifiable, is folded into the description.
  Text typed with the upload is a note to the receipt reader first ("this was
  yesterday" sets the date), then a follow-up agent confirms the card and answers any
  question in it. A plain upload (no typed text) skips the chat model entirely: the
  reply is a fixed sentence, since the outcome is fully determined. Photos are
  downscaled in the browser before upload (1600px long side, JPEG, phone rotation
  applied), so that's also what's stored; PDFs upload as-is. All
  of a receipt's items are categorized in a single model call.
  Category corrections (made via chat or by editing a proposed row) are learned per
  normalized description and reused on future similar purchases, with an LLM
  fallback that recognizes near-duplicate wording it doesn't match exactly.
- **Exchange rates.** "What's 50 USD in EUR?" calls a free, keyless daily reference
  rate covering 300+ currencies — explicitly a reference rate, never used to silently
  convert or alter a transaction's actual stated
  amount/currency.
- **Live updates.** The tab you're using updates the table instantly (an SSE event
  from the agent, or its own edit). Other tabs and devices refetch when their window
  regains focus, and every 60 seconds while focused — no separate sync service.
- **Chat memory.** Threads persist in Postgres and survive reloads/devices. The model
  sees a rolling per-thread summary plus the messages it doesn't cover yet: once a
  thread has more than 24 unsummarized messages, everything but the newest ~12 (cut
  at a turn boundary) is folded into the summary by a background task, off the hot
  path. History sent per call is also capped at `LLM_HISTORY_TOKEN_BUDGET` tokens,
  and anything that cap trims is folded into the summary too, so nothing is silently
  forgotten. The summary records intents/decisions, never specific amounts, since a
  lossy summary must never be trusted for numbers.
- **Localization.** Ten languages — English, Spanish, Indonesian, French, German,
  Portuguese, Hebrew, Russian, Ukrainian, Arabic — selectable per account. Not just UI
  strings: the chat model is instructed to reply in the selected language regardless
  of what language the user types in, receipt descriptions get translated into it, the
  category column's built-in labels are translated for display (the stored/matched
  value stays the English key), and Hebrew/Arabic flip the whole layout to RTL via
  logical CSS properties (not just a `dir` attribute flip). Every translation lives
  in the web app (`web/src/lib/i18n/locales/`): fixed replies from the backend (a
  receipt's outcome, errors, daily limits) arrive as a key plus params, a "notice"
  (`services/agent/app/models/notices.py`), which the chat shows in the current
  language — also after switching languages, and in reloaded history.
- **Dark/light theme**, persisted locally, no flash of the wrong theme on reload.
- Per-user daily quotas (chat turns, receipts, tokens — configurable via
  `DAILY_TURN_LIMIT`/`DAILY_RECEIPT_LIMIT`) and optional LangSmith tracing; it
  activates purely from environment variables, so an empty `.env` still runs the full
  app with tracing simply never turning on.

## Documentation

- [Architecture](docs/architecture.md): the services, the multi-agent graph, the agent's
  tools, the frontend and the local infrastructure.
- [Development](docs/development.md): code quality tooling, database migrations and the
  repo layout. The coding rules are in [CLAUDE.md](CLAUDE.md).
- [Configuration and LLMs](docs/configuration.md): environment variables, swapping the
  LLM provider, keeping costs down and the model evals.
- [Deploying to GCP](docs/deployment.md).

## Known gaps

- `get_exchange_rate` returns a *daily* reference rate, not live tick-by-tick market
  data.
- Production-only concerns not covered by `terraform/` or `.github/workflows/` —
  App Check, an external load balancer beyond Firebase Hosting, running the model
  eval as a CI gate (it exists, but is run by hand), Cloud
  Run autoscaling tuning, a GCS backend for Terraform state (still local, see
  `terraform/README.md`) — are intentionally out of scope for now.
