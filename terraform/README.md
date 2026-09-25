# Terraform — GCP production topology

Provisions the real GCP resources the root `docker-compose.yml` stack stands in for
locally: two Cloud Run services (`agent`, `transactions`), a Cloud SQL Postgres
instance (`bookkeeping` + `chat` databases), a Cloud Storage bucket for receipts, a
Cloud Tasks queue, Secret Manager secrets, Artifact Registry, and the Firebase
project link + Firestore database. See each `.tf` file's header comment for the
reasoning behind that piece.

## What this does NOT cover

- **Database schema.** `db/init/001_schema.sql` and `002_chat.sql` (table
  definitions, row-level security policies) don't run automatically — Terraform
  provisions the instance/databases/users, not table DDL. Apply them yourself after
  the instance exists, e.g. via the [Cloud SQL Auth
  Proxy](https://cloud.google.com/sql/docs/postgres/connect-auth-proxy) + `psql`:
  ```bash
  cloud-sql-proxy $(terraform output -raw cloud_sql_connection_name) &
  psql "postgresql://postgres@localhost/bookkeeping" -f ../db/init/001_schema.sql
  psql "postgresql://postgres@localhost/chat" -f ../db/init/002_chat.sql
  ```
  (The instance's default `postgres` superuser has no password set by this module —
  set one with `gcloud sql users set-password postgres --instance=... --prompt-for-password`
  before this works, or use `gcloud sql connect` instead, which handles auth for you.)
- **Firestore security rules / Hosting rewrites.** `firebase/firestore.rules` and a
  Hosting `firebase.json` rewrite config (routing `/api/chat/*` → the `agent` Cloud
  Run URL, `/api/transactions/*` → `transactions`, same shape as the local
  `Caddyfile`) deploy via `firebase deploy --only firestore:rules,hosting` with
  `firebase-tools`, not Terraform — this module only provisions the Firestore
  database and the Hosting site container.
- **Firebase Auth's Google sign-in provider** — enable it once by hand in the
  Firebase console (Authentication > Sign-in method). No stable Terraform resource
  covers this as of this module's writing.
- **Building/pushing container images.** `agent_image`/`transactions_image` default
  to a public placeholder so `apply` succeeds before CI exists; point them at real
  images in the Artifact Registry repo this module creates once you have a build.

## Two known application-code gaps (not fixed by this module)

- `services/agent/app/service_auth.py` and
  `services/transactions/app/service_auth.py`'s `require_service_caller` — meant to
  verify a Google-signed OIDC token in `X-Serverless-Authorization` for
  service-to-service calls — is currently a stub that returns 501 whenever
  `SKIP_SERVICE_AUTH` isn't `"true"`. Deploying this infrastructure does not make
  that check work; `POST /categorize` and `POST /internal/summarize` will 501 in
  production until that's implemented.
- `services/agent/app/tasks.py`'s `enqueue_summarize()` only has a `TASKS_MODE=local`
  code path — the real Cloud Tasks enqueue call (`else` branch) raises
  `NotImplementedError`. The `google_cloud_tasks_queue` this module creates is ready
  for that code; nothing calls it yet.

## Usage

Prerequisites: [`terraform` >= 1.7](https://developer.hashicorp.com/terraform/install),
a GCP project with billing enabled, and `gcloud auth application-default login` run
locally (or a service account key — see the
[google provider auth docs](https://registry.terraform.io/providers/hashicorp/google/latest/docs/guides/getting_started)).

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in project_id, region, web_origin
terraform init
terraform plan    # review before applying anything billable
terraform apply
```

**First apply, in order:**
1. `terraform apply` — everything applies successfully except possibly the two Cloud
   Run services if you haven't set real `agent_image`/`transactions_image` values yet
   (the public placeholder image should work fine for a first apply, though).
2. Add real secret values (see below), then run the DB schema migration above.
3. `terraform apply` again after CI has pushed real images and you've set
   `agent_image`/`transactions_image` in `terraform.tfvars`.

### Adding real secret values

Terraform seeds `<environment>-llm-api-key` and `<environment>-langsmith-api-key`
with a placeholder value so Cloud Run can deploy on a fresh project. Replace them:

```bash
echo -n "sk-..."   | gcloud secrets versions add prod-llm-api-key --data-file=-
echo -n "lsv2_..." | gcloud secrets versions add prod-langsmith-api-key --data-file=-
```

Cloud Run resolves `secret_key_ref { version = "latest" }` **at deploy time**, not on
every cold start — adding a new secret version doesn't retroactively update an
already-running revision. Re-run `terraform apply` (or `gcloud run services update
<service> --region <region>`) after adding a real value to roll a new revision that
actually picks it up.

### State

Local `.tfstate` for now (single environment, solo/small-team use) — gitignored, not
checked in. To move to a GCS backend later (needed once more than one person applies,
or once there's more than one environment):
1. `gcloud storage buckets create gs://<project>-tfstate --uniform-bucket-level-access`
2. Uncomment the `backend "gcs" {}` block noted in `versions.tf`.
3. `terraform init -migrate-state`.

### Destroying

`google_sql_database_instance.main` has `deletion_protection = true` — `terraform
destroy` will fail on it until you flip that to `false` and apply once first. This is
deliberate friction against accidentally dropping the production database.
