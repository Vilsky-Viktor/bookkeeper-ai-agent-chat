variable "project_id" {
  description = "GCP project to provision everything into. Must already exist (Terraform doesn't create projects)."
  type        = string
}

variable "region" {
  description = "Region for regional resources (Cloud Run, Cloud SQL, the receipts bucket, Artifact Registry)."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "A short label used in resource names/labels. Single-environment setup for now (see terraform/README.md) — this just tags resources, it doesn't create per-environment copies of anything."
  type        = string
  default     = "prod"
}

variable "web_origin" {
  description = "The deployed frontend's origin (e.g. https://smaker-ai.web.app), used for the receipts bucket's CORS rule — the browser PUTs receipt uploads directly to a v4 signed URL, cross-origin from this host (see storage.py's production branch)."
  type        = string
}

# --- LLM provider config (non-secret) — mirrors the non-secret half of .env.example.
# LLM_API_KEY itself is NOT a variable here; see secret_manager.tf and this module's
# README for how the real key gets in.

variable "llm_provider" {
  description = "openai (default), anthropic, or google — see the root README's 'Swapping the LLM provider'."
  type        = string
  default     = "openai"
}

variable "llm_model" {
  type    = string
  default = "gpt-4o"
}

variable "llm_fallback_model" {
  type    = string
  default = "gpt-4o-mini"
}

variable "llm_summary_model" {
  type    = string
  default = "gpt-4o-mini"
}

# --- LangSmith (optional — see services/agent/app/langsmith_obs.py). Off by default:
# turning it on before a real LANGSMITH_API_KEY value has been added (see
# secret_manager.tf) just means every trace upload fails silently, which is harmless
# but noisy — flip this once you've added a real key.

variable "langsmith_tracing" {
  type    = bool
  default = false
}

# --- Cloud Run images — Terraform doesn't build or push these itself; see
# .github/workflows/{agent,transactions}.yml for that (CI pushes on every merge to
# main, deploys on a version tag). Defaults point at Google's public "hello"
# placeholder so `terraform apply` succeeds before CI has ever pushed a real image.
# cloud_run.tf's `lifecycle { ignore_changes = [...] }` means once CI has deployed a
# real image, re-running `terraform apply` won't reset it back to these defaults —
# these variables only matter for the very first apply on a brand new project.

variable "agent_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "transactions_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

# agent enqueues Cloud Tasks HTTP tasks that POST back to its own
# /internal/summarize (see tasks.py) — Cloud Tasks needs a real, reachable URL for
# that, but a Cloud Run service can't reference its own computed .uri from within
# its own resource block (a genuine Terraform cycle, not just an inconvenience).
# Same bootstrap as agent_image/transactions_image above: left empty on a first
# apply (tasks.py's production path would fail with a KeyError until this is set —
# harmless, since nothing enqueues a real summarize task in a deployment that's
# otherwise still using the "hello" placeholder image anyway), then set from
# `terraform output -raw agent_url` and applied again.
variable "agent_url" {
  type    = string
  default = ""
}

# --- Cloud SQL sizing — small/cheap defaults appropriate for this app's scale; bump
# via tfvars for real load rather than editing these.

variable "cloud_sql_tier" {
  description = "Cloud SQL machine tier. db-f1-micro is the cheapest shared-core tier — fine for low traffic, not for production load."
  type        = string
  default     = "db-f1-micro"
}

# --- CI/CD (GitHub Actions) — see ci_cd.tf.

variable "github_repository" {
  description = "GitHub \"owner/repo\" slug this Workload Identity Federation provider trusts — only workflows running in this exact repo can impersonate the CI/CD service account."
  type        = string
  default     = "Vilsky-Viktor/bookkeeper-ai-agent-chat"
}
