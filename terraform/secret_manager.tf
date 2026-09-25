# Real values never touch Terraform state (beyond the placeholder below) or any
# .tf/.tfvars file; add the real ones after apply with:
#   echo -n "sk-..." | gcloud secrets versions add prod-llm-api-key --data-file=-
#   echo -n "lsv2_..." | gcloud secrets versions add prod-langsmith-api-key --data-file=-
# (see terraform/README.md). Mirrors how .env (gitignored, real values) vs
# .env.example (committed, keys only) already works for local dev.
#
# Each secret is seeded with an empty-string placeholder version so a fresh
# `terraform apply` can deploy Cloud Run successfully end-to-end (its secret_key_ref
# needs *some* version to exist) rather than failing outright until a real key is
# added by hand. Cloud Run pins the secret version it resolved to "latest" at deploy
# time — it does NOT hot-reload on `gcloud secrets versions add` — so after adding a
# real value, re-run `terraform apply` (or `gcloud run services update`) to roll a
# new revision that actually picks it up.

resource "google_secret_manager_secret" "llm_api_key" {
  project   = var.project_id
  secret_id = "${var.environment}-llm-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_version" "llm_api_key_placeholder" {
  secret      = google_secret_manager_secret.llm_api_key.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data] # don't fight a real value added via gcloud
  }
}

resource "google_secret_manager_secret" "langsmith_api_key" {
  project   = var.project_id
  secret_id = "${var.environment}-langsmith-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_version" "langsmith_api_key_placeholder" {
  secret      = google_secret_manager_secret.langsmith_api_key.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data] # don't fight a real value added via gcloud
  }
}

resource "google_secret_manager_secret_iam_member" "llm_api_key_agent" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.llm_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent.email}"
}

# transactions doesn't call an LLM directly for chat, but categorize.py's LLM
# fallback (services/transactions/app/categorize.py) does.
resource "google_secret_manager_secret_iam_member" "llm_api_key_transactions" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.llm_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.transactions.email}"
}

resource "google_secret_manager_secret_iam_member" "langsmith_api_key_agent" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.langsmith_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent.email}"
}
