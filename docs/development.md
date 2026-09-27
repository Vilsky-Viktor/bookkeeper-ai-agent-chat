# Development

## Code quality tooling

Each Python service is its own independent [`uv`](https://docs.astral.sh/uv/) project
(own `pyproject.toml` + `uv.lock`, no shared config across services) with `black`,
`isort`, `mypy`, and `pytest` (+ `pytest-asyncio`) as dev dependencies (the
`dependency-groups.dev` group, installed automatically by `uv sync`), run via
[`poethepoet`](https://github.com/nat-n/poethepoet) tasks:

```bash
cd services/agent   # or services/transactions
uv sync              # only needed for local (non-Docker) use
uv run poe start         # run the service (what the Dockerfile's CMD uses)
uv run poe format        # blank lines (CLAUDE.md rule 2) + black + isort, writes
uv run poe format:check  # same, check-only
uv run poe lint          # mypy
uv run poe test          # pytest
uv run poe check         # format:check + lint + test, in one go
```

`lint` also runs inside the running containers (e.g. `docker compose exec agent uv
run poe lint`), which see the live `app/` folder. `format`, `format:check`, `test` and
`check` need the local (non-Docker) `uv sync` above instead: they use `tests/` and the
repo-level `scripts/blank_lines.py`, neither of which is in the container.

The coding rules are in [CLAUDE.md](../CLAUDE.md). Rule 2 (an empty line before every
block and `return`) is enforced: by `scripts/blank_lines.py` in both services'
`format`/`check` tasks, and by ESLint's `padding-line-between-statements` in the web
app (`pnpm run lint --fix` adds them).

Each service's `tests/` directory covers its business logic (money/idempotency/
categorization, context assembly, tool HTTP calls, quotas, pagination, etc.) with
mocked DB connections and HTTP transports — no live Postgres or network access needed
to run them — plus a handful of endpoint-level tests via FastAPI's `TestClient`,
covering both success and error paths (400/401/404/409/429/501 as appropriate).
The agent also has a `tests/test_contracts.py` that reads the other side's source file
and fails if a list it keeps a copy of drifts (categories and supported languages vs
the web app, zero-decimal currencies vs the transactions service) — the services share no code on purpose, so this
is what keeps those copies honest. The pull-request workflows also run on changes to
those other files.

The frontend uses [`pnpm`](https://pnpm.io/) plus ESLint (flat config,
`typescript-eslint` + React Hooks/Refresh plugins), Prettier, and
[Vitest](https://vitest.dev/) + React Testing Library:

```bash
cd web
pnpm install
pnpm run lint           # eslint .
pnpm run format          # prettier --write .
pnpm run format:check    # prettier --check .
pnpm run test            # vitest run
pnpm run test:watch      # vitest, watch mode
```

`pnpm-workspace.yaml`'s `allowBuilds`/`onlyBuiltDependencies` approve the three
packages here with native postinstall scripts (`esbuild`, `@firebase/util`,
`protobufjs`) — pnpm blocks arbitrary install scripts by default as a supply-chain
guard; everything else installs with no scripts run at all.

Tests run in `jsdom` with no real network/DOM: pure logic (`src/lib/*.test.ts` — CSV
building, the default filter's rolling date window, translation lookups, receipt
upload preparation) plus component tests (`src/components/*.test.tsx` —
`@testing-library/react`, mocking `lib/api.ts`/Firebase/`fetch` at the module
boundary rather than hitting a network). The chat pane is covered through its parts
— `useChatStream` (SSE events → UI state, with `fetchEventSource` mocked),
`ChatComposer`, `ReceiptProposalCard`, and `lib/chat.ts` — rather than the
`ChatPanel` shell that wires them together; `App.tsx` isn't covered yet.

## Database migrations

Schema changes are numbered SQL files in `db/migrations/bookkeeping/` and
`db/migrations/chat/`, applied by [dbmate](https://github.com/amacneil/dbmate), which
records what's applied in each database's `schema_migrations` table. To change the
schema, add a file (`dbmate new <name>` or copy the naming), with `-- migrate:up` and
`-- migrate:down` sections, then `docker compose up migrate`. The same
`db/migrate.sh` runs locally and in production; CI applies every migration to a fresh
database, twice, on each PR that touches `db/`.

## Layout

```
db/init/                     first-boot setup: the chat database and the app roles
db/migrations/               schema + RLS policies, per database (dbmate)
db/Dockerfile, migrate.sh    the migration runner (Compose `migrate`, Cloud Run Job)
docs/                        architecture, development, configuration, deployment
CLAUDE.md                    coding rules for this repo
scripts/blank_lines.py       the Python check for CLAUDE.md rule 2 (both services' poe tasks)
firebase/                    Firebase Auth emulator container; emulator-data/
                               holds its persisted state (gitignored)
gcs/                         local receipt storage (fake-gcs, one folder per bucket; gitignored)
Makefile                     common tasks — `make` lists them
services/transactions/       FastAPI — owns Postgres, CRUD, category corrections, idempotency
  pyproject.toml / uv.lock own uv project — deps, black/isort/mypy, poe tasks
  app/main.py, auth.py          app setup and user JWT auth
  app/helpers/                  filters.py (shared filter-clause builder), money.py
                                 (decimal string <-> minor units), serializers.py
  app/storage/                  pool.py (connection pool, RLS), corrections.py,
                                 idempotency.py
  app/models/                   Pydantic request/response models, by domain
  app/routers/aggregates.py     sums by currency/category/month
  app/routers/transactions/     list.py, create.py, patch.py, delete.py
services/agent/               FastAPI + LangGraph — owns chat DB, SSE chat, tools
  pyproject.toml / uv.lock own uv project — deps, black/isort/mypy, poe tasks
  app/main.py                   app setup only: lifespan, routers, /healthz
  app/auth.py, service_auth.py  user JWT and service-to-service (Cloud Tasks) auth
  app/routers/                  threads.py, preferences.py, uploads.py, transcribe.py,
                                 chat.py (SSE), internal.py (Cloud Tasks summarize)
  app/workflows/                main.py (router + main graph), receipt.py,
                                 categorize.py, assistant.py, state.py (graph states)
  app/prompts/                  assistant.py (system prompt), receipt.py (vision),
                                 categorize.py, summarize.py
  app/services/                 receipts.py (vision read), categorize.py, summarize.py
  app/integrations/             llm.py (model factory), tracing.py (LangSmith),
                                 tasks.py (Cloud Tasks)
  app/constants/                categories.py, languages.py
  app/helpers/                  images.py, receipts.py (merchant folding, majority
                                 category), dates.py, serializers.py, filters.py,
                                 tool_schema.py (compact tool schema)
  app/storage/                  chat_db.py (chat database), quotas.py (daily limits),
                                 bucket.py (receipt files: upload targets, reads)
  app/tools/                    crud.py, currency.py, utility.py, __init__.py's
                                 build_tools()
  app/context/                  tokens.py, messages.py, __init__.py's build_context()
  app/chat/                     runner.py (one chat turn end to end),
                                 streaming.py (runs one graph turn -> SSE),
                                 turns.py (marker-retry decision, failure recording,
                                 persisting a turn, summarization trigger)
  app/models/                   Pydantic models, by domain (turns, message_content,
                                 api, tool_results)
  evals/                        chat_model_eval.py (+ chat_cases.py, chat_fixtures.py,
                                 chat_models.py), categorize_eval.py — model
                                 comparisons (not shipped)
web/                          React + Vite + TypeScript — chat pane + transactions table
  eslint.config.js / .prettierrc.json  lint + format config
  src/lib/i18n/                  locales/<lang>.ts (typed against en.ts), LanguageProvider,
                                 useTranslation(), supported languages
  src/lib/useChatStream.ts, useThreadMessages.ts, useVoiceRecorder.ts, chat.ts
                                 chat pane logic (streaming, history, voice, helpers)
  src/lib/format.ts              amount formatting
  src/types/                     api.ts (backend request/response shapes), chat.ts
  src/components/                ChatPanel (+ ChatComposer, ReceiptProposalCard),
                                  TransactionsTable (+ AmountText), ReceiptModal,
                                  ConfirmDialog, …
Caddyfile                     Reverse proxy — same routing shape as Firebase Hosting rewrites
docker-compose.yml
terraform/                    GCP infrastructure as code — see docs/deployment.md
.github/workflows/             CI per part (PRs, main) + release.yml (tag v*: deploy all) —
                                see docs/deployment.md
services/Dockerfile          shared image for both Python services (`dev` target + prod)
firebase.json                  Firebase Hosting config (rewrites to the two Cloud Run
                                services) — distinct from firebase/firebase.json, which
                                is local-emulator-only
```
