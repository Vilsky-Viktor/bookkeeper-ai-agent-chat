# Runtime identities. Resource-specific grants (Secret Manager access, bucket access,
# Cloud Tasks enqueue, Cloud SQL client) live next to the resource they're granted on
# (secret_manager.tf, storage.tf, cloud_tasks.tf, cloud_sql.tf) rather than here, so
# each file is a complete picture of who can touch that one resource.
#
# No agent-sa -> transactions-sa (or tasks-invoker-sa -> agent-sa) `run.invoker`
# binding exists here on purpose: both Cloud Run services are public (see
# cloud_run.tf) because the web frontend calls `transactions` directly, bypassing
# `agent` (see the Caddyfile's routing) — Cloud Run's own IAM is all-or-nothing per
# service, so it can't gate just the internal routes. Those (`POST /categorize`,
# `POST /internal/summarize`) are gated in application code instead
# (`require_service_caller`), which is what actually needs the OIDC token
# tasks-invoker-sa mints — no Cloud Run IAM grant required for that token to exist.

resource "google_service_account" "agent" {
  project      = var.project_id
  account_id   = "agent-sa"
  display_name = "agent service (Cloud Run runtime identity)"
}

resource "google_service_account" "transactions" {
  project      = var.project_id
  account_id   = "transactions-sa"
  display_name = "transactions service (Cloud Run runtime identity)"
}

# The identity Cloud Tasks uses to sign the OIDC token attached to its HTTP target
# when it calls agent's POST /internal/summarize — kept separate from agent-sa
# itself (least privilege: this identity's only job is proving "this request really
# came from Cloud Tasks", it has no other permissions).
resource "google_service_account" "tasks_invoker" {
  project      = var.project_id
  account_id   = "tasks-invoker-sa"
  display_name = "Cloud Tasks OIDC token identity for the summarize queue"
}
