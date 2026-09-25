# Both services are public (`allUsers` invoker) on purpose — see
# service_accounts.tf's comment: the web frontend calls `transactions` directly
# (Caddyfile routes /api/transactions/* straight there, bypassing `agent`), so
# Firebase Hosting rewrites need to reach both services directly, same shape as
# Caddy locally. Cloud Run's own IAM is all-or-nothing per service, so it can't gate
# just the internal routes (POST /categorize, POST /internal/summarize) — those are
# gated in application code instead (require_service_caller).
#
# Env vars below are docker-compose.yml's `environment:` blocks translated for
# production: every `*_EMULATOR_HOST` / `STORAGE_MODE` / `TASKS_MODE` /
# `SKIP_SERVICE_AUTH` local-only var is dropped entirely (their absence is what
# selects each module's production branch), GOOGLE_CLOUD_PROJECT becomes
# var.project_id, and DATABASE_URL/CHAT_DATABASE_URL/LLM_API_KEY/LANGSMITH_API_KEY
# come from Secret Manager instead of being inlined.

resource "google_cloud_run_v2_service" "transactions" {
  project  = var.project_id
  name     = "${var.environment}-transactions"
  location = var.region

  template {
    service_account = google_service_account.transactions.email

    containers {
      image = var.transactions_image

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "LLM_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.llm_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "LLM_MODEL"
        value = var.llm_model
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }
  }

  depends_on = [
    google_project_service.this,
    google_secret_manager_secret_version.database_url,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "transactions_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.transactions.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "agent" {
  project  = var.project_id
  name     = "${var.environment}-agent"
  location = var.region

  template {
    service_account = google_service_account.agent.email

    containers {
      image = var.agent_image

      env {
        name = "CHAT_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.chat_database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "LLM_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.llm_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "LANGSMITH_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.langsmith_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "TRANSACTIONS_URL"
        value = google_cloud_run_v2_service.transactions.uri
      }
      env {
        name  = "RECEIPTS_BUCKET"
        value = google_storage_bucket.receipts.name
      }
      env {
        name  = "LLM_PROVIDER"
        value = var.llm_provider
      }
      env {
        name  = "LLM_MODEL"
        value = var.llm_model
      }
      env {
        name  = "LLM_FALLBACK_MODEL"
        value = var.llm_fallback_model
      }
      env {
        name  = "LLM_SUMMARY_MODEL"
        value = var.llm_summary_model
      }
      env {
        name  = "LANGSMITH_TRACING"
        value = var.langsmith_tracing ? "true" : "false"
      }
      env {
        name  = "LANGSMITH_PROJECT"
        value = var.environment
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }
  }

  depends_on = [
    google_project_service.this,
    google_secret_manager_secret_version.chat_database_url,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "agent_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.agent.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
