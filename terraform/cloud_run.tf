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

  # Once .github/workflows/transactions.yml has deployed a real image, this stops
  # Terraform from resetting it back to var.transactions_image's placeholder on the
  # next `terraform apply` — CI owns the image from here, Terraform owns everything
  # else about the service.
  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }

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
      env {
        # service_auth.py checks POST /categorize's caller's token email against
        # this — only agent-sa is authorized to call that endpoint.
        name  = "AGENT_SERVICE_ACCOUNT"
        value = google_service_account.agent.email
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

  # Same reasoning as transactions above — CI owns the image post-first-deploy.
  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }

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
        # tasks.py's production enqueue path — where the queue lives and which
        # identity Cloud Tasks mints its callback token as. TASKS_INVOKER_SERVICE_ACCOUNT
        # doubles as service_auth.py's expected caller for POST /internal/summarize.
        name  = "CLOUD_TASKS_LOCATION"
        value = var.region
      }
      env {
        name  = "CLOUD_TASKS_QUEUE"
        value = google_cloud_tasks_queue.summarize.name
      }
      env {
        name  = "TASKS_INVOKER_SERVICE_ACCOUNT"
        value = google_service_account.tasks_invoker.email
      }
      # No AGENT_URL env var: a Cloud Run service can't reference its own computed
      # .uri from within its own resource block (a genuine Terraform cycle), and
      # patching it in after the fact (CI, or a local-exec provisioner here) would
      # conflict with Terraform's own authoritative ownership of this env list —
      # the next `terraform apply` would just reset it back out again. Instead,
      # main.py's chat() derives it per-request from the Host header (see tasks.py's
      # docstring) — always correct, no bootstrap step needed.
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
