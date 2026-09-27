# Deploying to GCP

`terraform/` provisions the real GCP resources this local stack stands in for: two
Cloud Run services, Cloud SQL (the same `bookkeeping`/`chat` databases), the receipts
bucket, a Cloud Tasks queue, Secret Manager secrets, Artifact Registry, the Firebase
project link + a Web App, and a Workload Identity Federation setup for CI/CD (no
long-lived GCP key stored anywhere). It does *not* cover Firebase Auth's Google
sign-in provider (enabled once by hand in the console).
The schema is applied by the `migrate` Cloud Run Job, which every release runs
before deploying the services.
The one service-to-service call, Cloud Tasks → `agent`'s `POST /internal/summarize`,
is authenticated with a real Google-signed OIDC token, not a stub — `service_auth.py`
verifies signature, a fixed audience, and the expected caller identity; `integrations/tasks.py` is
the minter. (`agent` → `transactions` calls just forward the user's own JWT.)
`agent`'s own callback URL (where Cloud Tasks POSTs back to) is derived
per-request from the triggering request's `Host` header rather than an env var —
no manual bootstrap step needed, see `terraform/README.md`'s "Service-to-service
auth" for why. See `terraform/README.md` for the full walkthrough.

CI/CD (`.github/workflows/`): a pull request runs the checks of whatever it touches
(`agent.yml`, `transactions.yml` — both via the shared `python-service.yml` — plus
`web.yml` and `db.yml`); a push to `main` also builds and pushes images (and the web
build) without deploying. **Releases are one tag for everything:** `git tag v1.2.3 &&
git push --tags` runs `release.yml`, which checks and builds all four pieces at that
commit and, only if every one passes, deploys in dependency order — migrations,
then `transactions`, then `agent`, then `web` — so a schema change lands before the
code that needs it and an API before its callers. One-time setup (copying
Terraform outputs into GitHub repo variables) is in `terraform/README.md`'s
"GitHub Actions setup".
