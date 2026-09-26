# Terraform — GCP production topology

Provisions the real GCP resources the root `docker-compose.yml` stack stands in for
locally: two Cloud Run services (`agent`, `transactions`), a Cloud SQL Postgres
instance (`bookkeeping` + `chat` databases), a Cloud Storage bucket for receipts, a
Cloud Tasks queue, Secret Manager secrets, Artifact Registry, and the Firebase
project link + Firestore database. See each `.tf` file's header comment for the
reasoning behind that piece.

## What this does NOT cover

- **Running the schema migrations.** `migrations.tf` provisions the `migrate` Cloud
  Run Job (dbmate + `db/migrations/`, as a dedicated `migrator` database user), but
  running it is CI's job: `.github/workflows/db.yml` on a `db-v*` tag. Verify on the
  first run that `migrator` can connect after the baseline revokes `CONNECT` from
  `PUBLIC` (it relies on Cloud SQL users inheriting `cloudsqlsuperuser`, the
  databases' owner).
- **Firestore security rules / Hosting rewrites.** `firebase/firestore.rules` and a
  Hosting `firebase.json` rewrite config (routing `/api/chat/*` → the `agent` Cloud
  Run URL, `/api/transactions/*` → `transactions`, same shape as the local
  `Caddyfile`) deploy via `firebase deploy --only firestore:rules,hosting` with
  `firebase-tools`, not Terraform — this module only provisions the Firestore
  database and the Hosting site container.
- **Firebase Auth's Google sign-in provider** — enable it once by hand in the
  Firebase console (Authentication > Sign-in method). No stable Terraform resource
  covers this as of this module's writing.
- **Building/pushing container images**, beyond providing the identity/permissions
  for it. `agent_image`/`transactions_image` default to a public placeholder so
  `apply` succeeds on a brand new project; `.github/workflows/{agent,transactions}.yml`
  push real images to the Artifact Registry repo this module creates and deploy them
  directly via `gcloud`/`deploy-cloudrun` (not by changing these variables — see
  `cloud_run.tf`'s `lifecycle.ignore_changes` and "GitHub Actions setup" below).

## Service-to-service auth

`services/agent/app/service_auth.py` and
`services/transactions/app/service_auth.py`'s `require_service_caller` verify a
Google-signed OIDC ID token in `X-Serverless-Authorization` — signature/expiry via
Google's public certs, a fixed `AUDIENCE` string both the minting side and the
verifying side agree on (not a real URL — see each file's docstring), and that the
signer is the one specific service account expected to be calling
(`AGENT_SERVICE_ACCOUNT` for `POST /categorize`, `TASKS_INVOKER_SERVICE_ACCOUNT` for
`POST /internal/summarize`), both wired in as env vars by `cloud_run.tf`. Locally
it's skipped entirely via `SKIP_SERVICE_AUTH=true`.

`services/agent/app/tasks.py`'s `enqueue_summarize()` mints the Cloud Tasks side of
that: it creates an explicitly-named HTTP task (so Cloud Tasks itself provides
cross-instance dedup, not just the in-process set) targeting
`<this service's own origin>/internal/summarize` with an OIDC token minted as
`tasks-invoker-sa`. That origin isn't an env var — a Cloud Run service can't
reference its own computed `.uri` from within its own resource block (a real
Terraform cycle), and patching it in after deploy would just get overwritten by the
next unrelated `terraform apply` (the `env` block is a list Terraform treats as
authoritative; `lifecycle.ignore_changes` can't target one entry within it).
Instead, `main.py`'s `chat()` derives it per-request from the triggering request's
`Host` header — always correct, no bootstrap step, no env var to keep in sync.
`receipts.py`'s `extract_receipt` tool mints its own token the same way on the
`agent` → `transactions` side, as whatever identity `agent`'s own Cloud Run
revision runs as (`agent-sa`, via Application Default Credentials — no explicit
credential file).

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
1. `terraform apply`.
2. Add real secret values (see below).
3. Copy the CI/CD outputs into GitHub repo variables (see "GitHub Actions setup"
   below), then push `git tag db-v0.1.0 && git push --tags` to create the schema,
   then the service tags (`agent-v0.1.0`, `transactions-v0.1.0`, `web-v0.1.0`) to
   trigger a real first deploy — from here on, CI owns
   the deployed image, not `terraform.tfvars`'s `agent_image`/`transactions_image`.

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

### GitHub Actions setup

`.github/workflows/{agent,transactions,web}.yml` authenticate to GCP via Workload
Identity Federation — no long-lived key ever leaves GCP or sits in a GitHub secret.
After `terraform apply`, copy six outputs into the repo's **Settings > Secrets and
variables > Actions > Variables** tab (repository *variables*, not secrets — none of
this is sensitive, that's the point of WIF):

| Terraform output | GitHub repo variable |
|---|---|
| `ci_cd_service_account_email` | `GCP_CI_CD_SERVICE_ACCOUNT` |
| `workload_identity_provider` | `GCP_WORKLOAD_IDENTITY_PROVIDER` |
| `firebase_web_app_api_key` | `VITE_FIREBASE_API_KEY` |
| `firebase_web_app_auth_domain` | `VITE_FIREBASE_AUTH_DOMAIN` |
| `firebase_web_app_project_id` | `VITE_FIREBASE_PROJECT_ID` |
| `receipts_bucket` | `VITE_RECEIPTS_BUCKET` |

Plus `var.project_id` and `var.region` themselves as `GCP_PROJECT_ID` /
`GCP_REGION`. `terraform output` prints all of these at once; `terraform output -raw
<name>` for a single value without the surrounding quotes.

The Workload Identity Pool provider's `attribute_condition` (see `ci_cd.tf`) trusts
only `var.github_repository` — if you forked this repo or renamed it, update that
variable and re-apply before CI will authenticate successfully.

The root `firebase.json`'s Hosting rewrites hardcode `serviceId: "prod-agent"` /
`"prod-transactions"` and `region: "us-central1"` (JSON has no variable
interpolation) — these must match `var.environment`/`var.region`'s actual values.
Since both default to `prod`/`us-central1` this only matters if you've changed
either in `terraform.tfvars`.

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
