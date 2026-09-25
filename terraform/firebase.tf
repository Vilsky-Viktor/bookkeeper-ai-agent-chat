# Links the GCP project to Firebase and provisions Firestore (native mode, used only
# for the sync/{uid} live-update signal — see lib/sync.ts) and a Hosting site.
#
# NOT provisioned here: firestore.rules content and firebase.json's Hosting rewrite
# rules. Those stay `firebase deploy --only firestore:rules,hosting` steps run with
# firebase-tools, same as this repo's existing firebase/ directory — Terraform's
# Firebase resources manage the containers (the project link, the database, the
# site), not their content. Firebase Auth's Google sign-in provider similarly still
# needs enabling once, by hand, in the Firebase console (Authentication > Sign-in
# method) — there's no stable Terraform resource for toggling individual sign-in
# providers as of this module's writing.

resource "google_firebase_project" "default" {
  provider = google-beta
  project  = var.project_id

  depends_on = [google_project_service.this]
}

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_firebase_project.default]
}

resource "google_firebase_hosting_site" "default" {
  provider = google-beta
  project  = var.project_id
  site_id  = var.project_id

  depends_on = [google_firebase_project.default]
}
