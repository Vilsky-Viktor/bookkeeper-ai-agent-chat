# Backs the rolling-summary background job — see services/agent/app/tasks.py's
# enqueue_summarize(), which creates an HTTP task here whose target is
# POST <AGENT_URL>/internal/summarize, with an OIDC token minted as tasks-invoker-sa
# (see service_accounts.tf) that agent's require_service_caller verifies on the way
# back in. cloud_run.tf wires CLOUD_TASKS_LOCATION/CLOUD_TASKS_QUEUE/
# TASKS_INVOKER_SERVICE_ACCOUNT/AGENT_URL into agent's env for this.

resource "google_cloud_tasks_queue" "summarize" {
  project  = var.project_id
  name     = "${var.environment}-summarize"
  location = var.region

  rate_limits {
    max_concurrent_dispatches = 5
    max_dispatches_per_second = 5
  }

  retry_config {
    max_attempts = 5
  }

  depends_on = [google_project_service.this]
}

resource "google_cloud_tasks_queue_iam_member" "summarize_agent_enqueuer" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_tasks_queue.summarize.name
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${google_service_account.agent.email}"
}

# So agent-sa is allowed to mint a token as tasks-invoker-sa when it eventually
# builds the OIDC-token HTTP target request (Cloud Tasks acts on the caller's
# behalf here, not its own service identity).
resource "google_service_account_iam_member" "agent_can_act_as_tasks_invoker" {
  service_account_id = google_service_account.tasks_invoker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.agent.email}"
}
