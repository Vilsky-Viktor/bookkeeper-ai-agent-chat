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

# --- Cloud Run images — Terraform doesn't build or push these (that's CI's job, not
# covered by this module). Defaults point at Google's public "hello" placeholder so
# `terraform apply` succeeds before a real image has ever been pushed to the
# Artifact Registry repo this module creates; swap these after your first CI build.

variable "agent_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "transactions_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

# --- Cloud SQL sizing — small/cheap defaults appropriate for this app's scale; bump
# via tfvars for real load rather than editing these.

variable "cloud_sql_tier" {
  description = "Cloud SQL machine tier. db-f1-micro is the cheapest shared-core tier — fine for low traffic, not for production load."
  type        = string
  default     = "db-f1-micro"
}
