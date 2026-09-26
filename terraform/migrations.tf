# Schema migrations (db/migrations) run as a Cloud Run Job over the same built-in
# Cloud SQL connector the services use, so the database is never exposed to CI.
# .github/workflows/db.yml builds the image (db/Dockerfile) and executes the job;
# like the services, CI owns the image and Terraform everything else.

resource "random_password" "migrator" {
  length  = 32
  special = false # keeps the DSN free of characters that need URL-encoding
}

# Users created through Cloud SQL are members of cloudsqlsuperuser, so this one can
# create tables, policies and grants — which app_user/chat_user deliberately can't.
resource "google_sql_user" "migrator" {
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  name     = "migrator"
  password = random_password.migrator.result
}

locals {
  migrate_databases = {
    bookkeeping = google_sql_database.bookkeeping.name
    chat        = google_sql_database.chat.name
  }
}

resource "google_secret_manager_secret" "migrate_database_url" {
  for_each  = local.migrate_databases
  project   = var.project_id
  secret_id = "${var.environment}-migrate-${each.key}-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_version" "migrate_database_url" {
  for_each = local.migrate_databases
  secret   = google_secret_manager_secret.migrate_database_url[each.key].id
  # dbmate's form of a Unix-socket DSN (the services' asyncpg DSNs use ?host=).
  secret_data = format(
    "postgres://%s:%s@/%s?socket=/cloudsql/%s&sslmode=disable",
    google_sql_user.migrator.name,
    random_password.migrator.result,
    each.value,
    google_sql_database_instance.main.connection_name,
  )
}

resource "google_service_account" "migrate" {
  project      = var.project_id
  account_id   = "${var.environment}-migrate"
  display_name = "Schema migration job"
}

resource "google_secret_manager_secret_iam_member" "migrate_database_url" {
  for_each  = local.migrate_databases
  project   = var.project_id
  secret_id = google_secret_manager_secret.migrate_database_url[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migrate.email}"
}

resource "google_project_iam_member" "cloudsql_client_migrate" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.migrate.email}"
}

resource "google_cloud_run_v2_job" "migrate" {
  project  = var.project_id
  name     = "${var.environment}-migrate"
  location = var.region

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }

  template {
    template {
      service_account = google_service_account.migrate.email
      max_retries     = 0 # a failed migration needs a human, not a retry

      containers {
        image = var.migrate_image

        env {
          name = "BOOKKEEPING_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.migrate_database_url["bookkeeping"].secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "CHAT_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.migrate_database_url["chat"].secret_id
              version = "latest"
            }
          }
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
  }

  depends_on = [
    google_secret_manager_secret_version.migrate_database_url,
    google_secret_manager_secret_iam_member.migrate_database_url,
    google_project_iam_member.cloudsql_client_migrate,
  ]
}
