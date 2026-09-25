# Receipts bucket — mirrors fake-gcs-server locally. storage.py's production branch
# (STORAGE_MODE unset) generates a v4 signed PUT URL and hands it straight to the
# browser, so — unlike the local direct-POST-through-Caddy path — this bucket needs
# CORS allowing a cross-origin PUT from the deployed web app.

resource "google_storage_bucket" "receipts" {
  project                     = var.project_id
  name                        = "${var.project_id}-receipts"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  cors {
    origin          = [var.web_origin]
    method          = ["PUT"]
    response_header = ["Content-Type"]
    max_age_seconds = 3600
  }

  depends_on = [google_project_service.this]
}

resource "google_storage_bucket_iam_member" "receipts_agent" {
  bucket = google_storage_bucket.receipts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.agent.email}"
}
