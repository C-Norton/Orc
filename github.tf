provider "github" {
  token = var.github_token
  owner = "C-Norton"
}

# ─────────────────────────────────────────────
# Enable required APIs
# ─────────────────────────────────────────────

resource "google_project_service" "iam_credentials" {
  service            = "iamcredentials.googleapis.com"
  disable_on_destroy = false
}

# ─────────────────────────────────────────────
# Workload Identity Federation
# ─────────────────────────────────────────────

# The pool is the top-level WIF container for this project.
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "orc-bot-github-pool"
  display_name              = "ORC Bot GitHub Actions Pool"
  description               = "WIF pool for GitHub Actions deployments"
}

# The provider within the pool — scoped to GitHub's OIDC issuer.
resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "orc-bot-github-provider"
  display_name                       = "GitHub Actions OIDC"

  attribute_mapping = {
    # Maps GitHub OIDC claims to Google attributes used in the binding below.
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  # Only tokens issued by GitHub's OIDC endpoint are accepted.
  attribute_condition = "attribute.repository == \"C-Norton/Orc\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# ─────────────────────────────────────────────
# Deploy service account
# ─────────────────────────────────────────────

# Separate from the VM's runtime service account — least privilege:
# this SA can only SSH via IAP and restart the systemd service.
resource "google_service_account" "deploy_sa" {
  account_id   = "orc-bot-deploy-sa"
  display_name = "ORC Bot GitHub Actions Deploy SA"
}

# Allow GitHub Actions (via WIF) to impersonate the deploy SA.
# Scoped to the specific repository — no other repo can impersonate this SA.
resource "google_service_account_iam_member" "wif_deploy_binding" {
  service_account_id = google_service_account.deploy_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/C-Norton/Orc"
}

# Allow the deploy SA to tunnel through IAP to the bot VM.
resource "google_iap_tunnel_instance_iam_member" "deploy_sa_iap" {
  project  = var.project_id
  zone     = var.zone
  instance = google_compute_instance.orc_bot_vm.name
  role     = "roles/iap.tunnelResourceAccessor"
  member   = "serviceAccount:${google_service_account.deploy_sa.email}"
}

# Allow the deploy SA to look up instance details (needed by gcloud compute ssh).
resource "google_project_iam_member" "deploy_sa_compute_viewer" {
  project = var.project_id
  role    = "roles/compute.viewer"
  member  = "serviceAccount:${google_service_account.deploy_sa.email}"
}

# Allow the deploy SA to use OS Login on the VM.
resource "google_project_iam_member" "deploy_sa_oslogin" {
  project = var.project_id
  role    = "roles/compute.osLogin"
  member  = "serviceAccount:${google_service_account.deploy_sa.email}"
}

# ─────────────────────────────────────────────
# GitHub Actions secrets — injected into the workflow
# ─────────────────────────────────────────────

resource "github_actions_secret" "wif_provider" {
  repository      = "Orc"
  secret_name     = "WIF_PROVIDER"
  plaintext_value = google_iam_workload_identity_pool_provider.github.name
}

resource "github_actions_secret" "deploy_sa_email" {
  repository      = "Orc"
  secret_name     = "DEPLOY_SA_EMAIL"
  plaintext_value = google_service_account.deploy_sa.email
}

resource "github_actions_secret" "gcp_project_id" {
  repository      = "Orc"
  secret_name     = "GCP_PROJECT_ID"
  plaintext_value = var.project_id
}

resource "github_actions_secret" "vm_zone" {
  repository      = "Orc"
  secret_name     = "VM_ZONE"
  plaintext_value = var.zone
}

resource "github_actions_secret" "vm_name" {
  repository      = "Orc"
  secret_name     = "VM_NAME"
  plaintext_value = google_compute_instance.orc_bot_vm.name
}

# ─────────────────────────────────────────────
# Branch protection on master
# ─────────────────────────────────────────────

resource "github_branch_protection" "master" {
  repository_id = "Orc"
  pattern       = "master"

  # Require the Actions checks to pass before merge.
  required_status_checks {
    strict   = true # Branch must be up to date with master before merge.
    contexts = ["test"]  # Must match the job name in deploy.yml.
  }

  # Enforce the protection rules for admins too.
  enforce_admins = false  # Set to true once you're comfortable with the workflow.

  # Require at least one approval on PRs.
  # Set to 0 for solo development if you find this too friction-heavy.
  required_pull_request_reviews {
    required_approving_review_count = 0
    dismiss_stale_reviews           = true
  }

  # Prevent direct pushes to master — all changes must come through a PR.
  allows_force_pushes = false
  allows_deletions    = false
}
