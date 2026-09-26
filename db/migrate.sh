#!/bin/sh
# Applies pending migrations to both databases — locally (the `migrate` Compose
# service) and in production (the `migrate` Cloud Run Job, see db/Dockerfile).
# BOOKKEEPING_DATABASE_URL / CHAT_DATABASE_URL must be a user allowed to create
# tables and policies, not the app's own restricted roles.
set -eu
dbmate --url "$BOOKKEEPING_DATABASE_URL" --migrations-dir /db/migrations/bookkeeping --no-dump-schema --wait up
dbmate --url "$CHAT_DATABASE_URL" --migrations-dir /db/migrations/chat --no-dump-schema --wait up
