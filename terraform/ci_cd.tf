# Workload Identity Federation — GitHub Actions impersonates google_service_account.ci_cd
# via a short-lived, per-run OIDC token instead of a long-lived JSON key stored as a
# GitHub secret. See .github/workflows/{agent,transactions,web}.yml (each job that
# talks to GCP starts with google-github-actions/auth using this pool/provider) and
# terraform/README.md's "GitHub Actions setup" section for the repo variables this
# feeds into.

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.this]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  # Only workflow runs in this exact repo can present a token this pool accepts —
  # not "any GitHub repo", and not even a fork of this one.
  attribute_condition = "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "ci_cd" {
  project      = var.project_id
  account_id   = "github-ci-cd"
  display_name = "GitHub Actions CI/CD (image push + deploy)"
}

# The actual "GitHub Actions can impersonate this SA" binding — scoped to the
# principalSet for this one repo's attribute.repository, not the whole pool.
resource "google_service_account_iam_member" "ci_cd_workload_identity_user" {
  service_account_id = google_service_account.ci_cd.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_artifact_registry_repository_iam_member" "ci_cd_artifact_writer" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.services.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.ci_cd.email}"
}

# roles/run.developer (not roles/run.admin): can deploy revisions, can't delete
# services or touch IAM on them.
resource "google_project_iam_member" "ci_cd_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.ci_cd.email}"
}

# Deploying a Cloud Run revision that runs *as* agent-sa/transactions-sa requires
# the deployer to be allowed to act as that runtime identity.
resource "google_service_account_iam_member" "ci_cd_actas_agent" {
  service_account_id = google_service_account.agent.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.ci_cd.email}"
}

resource "google_service_account_iam_member" "ci_cd_actas_transactions" {
  service_account_id = google_service_account.transactions.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.ci_cd.email}"
}

resource "google_project_iam_member" "ci_cd_hosting_admin" {
  project = var.project_id
  role    = "roles/firebasehosting.admin"
  member  = "serviceAccount:${google_service_account.ci_cd.email}"
}
