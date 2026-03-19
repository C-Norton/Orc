terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    # CHANGE: added random provider for DB password generation
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    # CHANGE: added GitHub provider for branch protection and Actions secrets
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# ─────────────────────────────────────────────
# Enable required APIs
# ─────────────────────────────────────────────

resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com",
    "iap.googleapis.com",
    "secretmanager.googleapis.com",
    "oslogin.googleapis.com",
    "sqladmin.googleapis.com",            # CHANGE: added for Cloud SQL
    "servicenetworking.googleapis.com",   # CHANGE: added for Cloud SQL private IP
    "iamcredentials.googleapis.com",      # CHANGE: added for Workload Identity Federation
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# ─────────────────────────────────────────────
# VPC and subnet
# ─────────────────────────────────────────────

# CHANGE: renamed kaz_vpc -> orc_vpc, updated name label
resource "google_compute_network" "orc_vpc" {
  name                    = "orc-bot-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.apis]
}

# CHANGE: renamed kaz_subnet -> orc_subnet, updated name label and network ref
resource "google_compute_subnetwork" "orc_subnet" {
  name                     = "orc-bot-subnet"
  region                   = var.region
  network                  = google_compute_network.orc_vpc.id
  ip_cidr_range            = "10.10.0.0/24"

  # Enable Private Google Access so the VM can reach Secret Manager
  # and Cloud SQL without a public IP.
  private_ip_google_access = true
}

# CHANGE: added private services IP range for Cloud SQL private IP peering
resource "google_compute_global_address" "private_services_range" {
  name          = "orc-bot-private-services-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.orc_vpc.id
}

# CHANGE: added service networking connection so Cloud SQL can use private IP
resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.orc_vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services_range.name]

  depends_on = [google_project_service.apis]
}

# ─────────────────────────────────────────────
# Firewall rules
# ─────────────────────────────────────────────

# Allow IAP to reach the VM on port 22 only.
# 35.235.240.0/20 is the Google IAP forwarding range.
# No direct public SSH port is opened.
# CHANGE: renamed resource and updated name label and network ref
resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "orc-bot-allow-iap-ssh"
  network = google_compute_network.orc_vpc.id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["orc-bot"] # CHANGE: tag renamed
}

# Allow the VM to make outbound HTTPS calls to:
#   - Discord Gateway / API       (discord.com, gateway.discord.gg)
#   - GCP APIs (Secret Manager)   (*.googleapis.com)
# CHANGE: renamed resource and updated name label, network ref, and tag
resource "google_compute_firewall" "allow_egress_apis" {
  name      = "orc-bot-allow-egress-apis"
  network   = google_compute_network.orc_vpc.id
  direction = "EGRESS"

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }

  destination_ranges = ["0.0.0.0/0"]
  target_tags        = ["orc-bot"] # CHANGE: tag renamed
}

# CHANGE: added egress rule allowing VM to reach Cloud SQL on port 5432 (private IP)
resource "google_compute_firewall" "allow_egress_cloudsql" {
  name      = "orc-bot-allow-egress-cloudsql"
  network   = google_compute_network.orc_vpc.id
  direction = "EGRESS"

  allow {
    protocol = "tcp"
    ports    = ["5432"]
  }

  # Cloud SQL private IP lives in the peered private services range (10.0.0.0/16).
  destination_ranges = ["10.0.0.0/16"]
  target_tags        = ["orc-bot"] # CHANGE: tag renamed
}

# Deny all other inbound traffic explicitly.
# CHANGE: renamed resource and updated name label and network ref
resource "google_compute_firewall" "deny_all_ingress" {
  name      = "orc-bot-deny-all-ingress"
  network   = google_compute_network.orc_vpc.id
  direction = "INGRESS"
  priority  = 65534

  deny {
    protocol = "all"
  }

  source_ranges = ["0.0.0.0/0"]
}

# ─────────────────────────────────────────────
# Service account — least privilege
# ─────────────────────────────────────────────

# CHANGE: renamed resource, account_id, and display_name
resource "google_service_account" "orc_bot_sa" {
  account_id   = "orc-bot-sa"
  display_name = "ORC Bot Service Account"
}

# Allow the SA to read secrets from Secret Manager only.
# CHANGE: updated member ref to orc_bot_sa
resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.orc_bot_sa.email}"
}

# Allow the SA to write logs.
# CHANGE: updated member ref to orc_bot_sa
resource "google_project_iam_member" "log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.orc_bot_sa.email}"
}

# CHANGE: added Cloud SQL client role so the VM can connect via private IP
resource "google_project_iam_member" "cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.orc_bot_sa.email}"
}

# ─────────────────────────────────────────────
# IAP SSH access for human operators
# ─────────────────────────────────────────────

# CHANGE: updated instance ref and member SA ref
resource "google_iap_tunnel_instance_iam_member" "ssh_users" {
  for_each = toset(var.ssh_users)

  project  = var.project_id
  zone     = var.zone
  instance = google_compute_instance.orc_bot_vm.name
  role     = "roles/iap.tunnelResourceAccessor"
  member   = "user:${each.key}@gmail.com"
}

# ─────────────────────────────────────────────
# VM instance
# ─────────────────────────────────────────────

# CHANGE: renamed resource, VM name, tags, labels; removed SQLite disk attachment;
#         updated network/subnet refs and service account ref
resource "google_compute_instance" "orc_bot_vm" {
  name         = "orc-bot-vm"
  machine_type = "e2-micro"
  zone         = var.zone

  tags = ["orc-bot"] # CHANGE: tag renamed

  labels = {
    app = "orc-bot" # CHANGE: label renamed
    env = "prod"
  }

  boot_disk {
    initialize_params {
      # Debian 12 (Bookworm) — stable, lightweight, good Docker support.
      image = "debian-cloud/debian-13"
      size  = 20
      type  = "pd-standard"
    }
  }

  # CHANGE: removed attached_disk block — no SQLite disk, DB is now Cloud SQL

  network_interface {
    network    = google_compute_network.orc_vpc.id    # CHANGE: updated ref
    subnetwork = google_compute_subnetwork.orc_subnet.id # CHANGE: updated ref

    # No public IP — access is via IAP only.
    # Outbound internet traffic routes through the default internet gateway
    # on GCP's network (ephemeral NAT). For stricter control, provision a
    # Cloud NAT resource and remove this access_config block entirely.
    access_config {}
  }

  service_account {
    email  = google_service_account.orc_bot_sa.email # CHANGE: updated ref
    scopes = ["cloud-platform"]
  }

  metadata = {
    # Enable OS Login for IAP SSH — more secure than metadata SSH keys.
    enable-oslogin = "TRUE"
    startup-script = file("${path.module}/startup.sh")
    # CHANGE: added — passes Cloud SQL private IP so startup.sh can build DATABASE_URL
    # without needing to reference Terraform outputs at runtime.
    db-private-ip  = google_sql_database_instance.orc_bot_db.private_ip_address
  }

  # Replace the VM if the boot disk image changes (e.g. OS upgrade).
  lifecycle {
    create_before_destroy = true
  }

  # CHANGE: removed kaz_data_disk dependency — no SQLite disk
  depends_on = [
    google_project_service.apis,
    google_service_networking_connection.private_vpc_connection, # CHANGE: added — Cloud SQL needs VPC peering first
  ]
}
