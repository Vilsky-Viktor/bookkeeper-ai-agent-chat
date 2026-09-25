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
