output "agent_url" {
  value = google_cloud_run_v2_service.agent.uri
}

output "transactions_url" {
  value = google_cloud_run_v2_service.transactions.uri
}

output "receipts_bucket" {
  value = google_storage_bucket.receipts.name
}

output "cloud_sql_connection_name" {
  value = google_sql_database_instance.main.connection_name
}

output "artifact_registry_repository" {
  description = "Push images here, e.g. <region>-docker.pkg.dev/<project>/<this>/agent:<tag>"
  value       = google_artifact_registry_repository.services.name
}

output "secrets_needing_a_real_value" {
  description = "Still holding the Terraform-seeded placeholder — see terraform/README.md's 'Adding real secret values'."
  value = [
    google_secret_manager_secret.llm_api_key.secret_id,
    google_secret_manager_secret.langsmith_api_key.secret_id,
  ]
}

# --- CI/CD — copy these into GitHub repo *variables* (not secrets; none of this is
# sensitive — that's the point of Workload Identity Federation) per
# terraform/README.md's "GitHub Actions setup" section.

output "ci_cd_service_account_email" {
  description = "-> repo variable GCP_CI_CD_SERVICE_ACCOUNT"
  value       = google_service_account.ci_cd.email
}

output "workload_identity_provider" {
  description = "-> repo variable GCP_WORKLOAD_IDENTITY_PROVIDER"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "firebase_web_app_api_key" {
  description = "-> repo variable VITE_FIREBASE_API_KEY"
  value       = data.google_firebase_web_app_config.default.api_key
}

output "firebase_web_app_auth_domain" {
  description = "-> repo variable VITE_FIREBASE_AUTH_DOMAIN"
  value       = data.google_firebase_web_app_config.default.auth_domain
}

output "firebase_web_app_project_id" {
  description = "-> repo variable VITE_FIREBASE_PROJECT_ID (same as project_id, listed for copy-paste convenience)"
  value       = var.project_id
}
