# Links the GCP project to Firebase (for Firebase Auth) and provisions a Hosting site.
#
# NOT provisioned here: firebase.json's Hosting rewrite rules — `firebase deploy
# --only hosting` (release.yml) ships them; Terraform manages the site, not its
# content. Firebase Auth's Google sign-in provider similarly still
# needs enabling once, by hand, in the Firebase console (Authentication > Sign-in
# method) — there's no stable Terraform resource for toggling individual sign-in
# providers as of this module's writing.

resource "google_firebase_project" "default" {
  provider = google-beta
  project  = var.project_id

  depends_on = [google_project_service.this]
}

resource "google_firebase_hosting_site" "default" {
  provider = google-beta
  project  = var.project_id
  site_id  = var.project_id

  depends_on = [google_firebase_project.default]
}

# Registers a Firebase Web App so the deployed frontend has a real apiKey/authDomain
# to build against (web/src/lib/firebase.ts reads these via VITE_FIREBASE_* — see
# outputs.tf). A Firebase web API key is meant to be public/embedded in client-side
# code by design (it identifies the project, it isn't a secret), so this doesn't go
# through Secret Manager.
resource "google_firebase_web_app" "default" {
  provider     = google-beta
  project      = var.project_id
  display_name = "${var.environment}-web"

  depends_on = [google_firebase_project.default]
}

data "google_firebase_web_app_config" "default" {
  provider   = google-beta
  project    = var.project_id
  web_app_id = google_firebase_web_app.default.app_id
}
