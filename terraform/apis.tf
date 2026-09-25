# Every GCP API this module's resources need enabled on the project. Terraform
# resources that depend on one of these should list it in `depends_on` so a fresh
# project doesn't hit "API not enabled" errors on first apply.

locals {
  required_apis = [
    "run.googleapis.com",                  # Cloud Run
    "sqladmin.googleapis.com",             # Cloud SQL
    "secretmanager.googleapis.com",        # Secret Manager
    "cloudtasks.googleapis.com",           # Cloud Tasks
    "firestore.googleapis.com",            # Firestore (sync/{uid} live-update signal)
    "storage.googleapis.com",              # Cloud Storage (receipts bucket)
    "artifactregistry.googleapis.com",     # Artifact Registry (Cloud Run images)
    "identitytoolkit.googleapis.com",      # Firebase Auth
    "firebase.googleapis.com",             # Firebase project link + Hosting
    "cloudresourcemanager.googleapis.com", # IAM bindings on the project
    "iam.googleapis.com",                  # service accounts
  ]
}

resource "google_project_service" "this" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false # don't disable project-wide APIs just because this module is torn down
}
