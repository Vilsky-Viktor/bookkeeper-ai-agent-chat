# Common tasks. `make` (or `make help`) lists them.

# The Compose plugin if it works, else the standalone docker-compose binary.
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo docker-compose)

.DEFAULT_GOAL := help
.PHONY: help up down logs rebuild migrate migration check check-agent check-transactions check-web \
	format eval-chat eval-categorize reset

help: ## List the available tasks
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-20s %s\n", $$1, $$2}'

up: ## Start the whole stack (builds images on first run)
	$(COMPOSE) up -d --build

down: ## Stop the stack (keeps all data)
	$(COMPOSE) down

logs: ## Follow logs: all services, or one with s=<service>
	$(COMPOSE) logs -f --tail=100 $(s)

rebuild: ## Rebuild one service after a dependency change: make rebuild s=agent
	@test -n "$(s)" || { echo "usage: make rebuild s=<service>"; exit 1; }
	$(COMPOSE) up -d --build --no-deps $(s)

migrate: ## Apply pending database migrations
	$(COMPOSE) up migrate

migration: ## New migration file: make migration db=bookkeeping|chat name=add_something
	@test -n "$(db)" -a -n "$(name)" || { echo "usage: make migration db=bookkeeping|chat name=<name>"; exit 1; }
	@test -d db/migrations/$(db) || { echo "no such database: $(db)"; exit 1; }
	@f=db/migrations/$(db)/$$(date -u +%Y%m%d%H%M%S)_$(name).sql; \
		printf -- '-- migrate:up\n\n\n-- migrate:down\n\n' > $$f && echo "created $$f"

check: check-agent check-transactions check-web ## Format check, lint and tests for all three projects

check-agent: ## Checks for services/agent
	cd services/agent && uv run poe check

check-transactions: ## Checks for services/transactions
	cd services/transactions && uv run poe check

# Inside the running web container, so a local pnpm install isn't needed.
check-web: ## Checks for web (lint, format, tests, production build)
	$(COMPOSE) exec -T web sh -c "pnpm run lint && pnpm run format:check && pnpm run test && pnpm run build"

format: ## Auto-format all three projects
	cd services/agent && uv run poe format
	cd services/transactions && uv run poe format
	$(COMPOSE) exec -T web pnpm run format

eval-chat: ## Chat-model eval; pass options with args="--models gpt-4o-mini --runs 3"
	$(COMPOSE) exec agent uv run python -m evals.chat_model_eval $(args)

eval-categorize: ## Categorizer eval; pass options with args="--models gpt-4o gpt-4o-mini"
	$(COMPOSE) exec transactions uv run python -m evals.categorize_eval $(args)

reset: ## Delete ALL local data (database, test accounts, receipts), after confirming
	@printf "This deletes the local database, emulator accounts and receipts. Type 'yes' to continue: "; \
		read answer; test "$$answer" = yes || { echo "cancelled"; exit 1; }
	$(COMPOSE) down -v
	rm -rf firebase/emulator-data gcs
