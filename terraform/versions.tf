terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    # A handful of Firebase resources (google_firebase_project,
    # google_firebase_hosting_site) are still beta-only — see firebase.tf.
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Local state for now (single-environment, solo/small-team use) — a `*.tfstate`
  # file next to these configs, gitignored. To move to a GCS backend later (needed
  # once more than one person applies, or once there's more than one environment):
  #   1. Create a bucket: gcloud storage buckets create gs://<project>-tfstate
  #      --uniform-bucket-level-access
  #   2. Uncomment a `backend "gcs" { bucket = "<project>-tfstate" prefix = "terraform/state" }`
  #      block here.
  #   3. Run `terraform init -migrate-state`.
}
