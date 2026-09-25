# One Postgres instance, two databases (bookkeeping, chat) — mirrors
# docker-compose.yml's single `postgres` service with db/init/'s two schema files.
# Terraform provisions the instance/databases/users; it does NOT run
# db/init/001_schema.sql / 002_chat.sql (table DDL + RLS policies) — that stays a
# migration step you run against the instance below (e.g. via the Cloud SQL Auth
# Proxy + psql) after apply. See terraform/README.md.

resource "google_sql_database_instance" "main" {
  project             = var.project_id
  name                = "${var.environment}-bookkeeping"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = true

  settings {
    tier = var.cloud_sql_tier
    backup_configuration {
      enabled    = true
      start_time = "03:00"
    }
  }

  depends_on = [google_project_service.this]
}

resource "google_sql_database" "bookkeeping" {
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  name     = "bookkeeping"
}

resource "google_sql_database" "chat" {
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  name     = "chat"
}

resource "random_password" "app_user" {
  length  = 32
  special = false # keeps the generated DSN below free of characters that need URL-encoding
}

resource "random_password" "chat_user" {
  length  = 32
  special = false
}

resource "google_sql_user" "app_user" {
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  name     = "app_user"
  password = random_password.app_user.result
}

resource "google_sql_user" "chat_user" {
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  name     = "chat_user"
  password = random_password.chat_user.result
}

# Cloud Run's built-in Cloud SQL connector exposes the instance over a Unix socket at
# /cloudsql/<connection_name> (wired up in cloud_run.tf's `volumes` block) — both
# services already read one DSN env var (DATABASE_URL / CHAT_DATABASE_URL) via plain
# os.environ reads, so storing the whole computed DSN as one secret and sourcing it
# as one Cloud Run env var needs zero application code changes.

resource "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = "${var.environment}-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  secret_data = format(
    "postgresql://%s:%s@/%s?host=/cloudsql/%s",
    google_sql_user.app_user.name,
    random_password.app_user.result,
    google_sql_database.bookkeeping.name,
    google_sql_database_instance.main.connection_name,
  )
}

resource "google_secret_manager_secret" "chat_database_url" {
  project   = var.project_id
  secret_id = "${var.environment}-chat-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_version" "chat_database_url" {
  secret = google_secret_manager_secret.chat_database_url.id
  secret_data = format(
    "postgresql://%s:%s@/%s?host=/cloudsql/%s",
    google_sql_user.chat_user.name,
    random_password.chat_user.result,
    google_sql_database.chat.name,
    google_sql_database_instance.main.connection_name,
  )
}

resource "google_secret_manager_secret_iam_member" "database_url_transactions" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.transactions.email}"
}

resource "google_secret_manager_secret_iam_member" "chat_database_url_agent" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.chat_database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent.email}"
}

# Cloud SQL's own IAM surface is project-level (roles/cloudsql.client), not
# per-instance — both runtime identities that connect via the Cloud Run Cloud SQL
# volume need it.
resource "google_project_iam_member" "cloudsql_client_agent" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_project_iam_member" "cloudsql_client_transactions" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.transactions.email}"
}
