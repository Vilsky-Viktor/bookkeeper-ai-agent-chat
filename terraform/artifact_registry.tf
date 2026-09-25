# One repo for both service images — CI pushes here (docker build + docker push,
# not covered by this module); cloud_run.tf's agent_image/transactions_image
# variables default to a public placeholder image until CI has pushed a real one.

resource "google_artifact_registry_repository" "services" {
  project       = var.project_id
  location      = var.region
  repository_id = "${var.environment}-services"
  format        = "DOCKER"
  description   = "agent and transactions service images"

  depends_on = [google_project_service.this]
}
