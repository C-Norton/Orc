# ─────────────────────────────────────────────
# Database password — randomly generated
# ─────────────────────────────────────────────

resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# ─────────────────────────────────────────────
# Cloud SQL — Postgres 15, private IP only
# ─────────────────────────────────────────────

resource "google_sql_database_instance" "orc_bot_db" {
  name             = "orc-bot-db"
  database_version = "POSTGRES_15"
  region           = var.region

  # Prevent accidental destruction — remove this flag before running
  # terraform destroy, or use: terraform destroy -target=... carefully.
  deletion_protection = true

  settings {
    tier = "db-f1-micro"

    # Private IP only — no public endpoint exposed.
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.orc_vpc.id
    }

    backup_configuration {
      enabled    = true
      start_time = "03:00" # 3am UTC — low-traffic window

      # 7-day point-in-time recovery window.
      # Requires transaction log retention, enabled below.
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    # 60-day query log retention via Cloud Logging.
    # database_flags sets log_min_duration_statement to capture all queries;
    # adjust to e.g. 1000 (ms) in production to avoid noise.
    database_flags {
      name  = "log_min_duration_statement"
      value = "-1" # -1 = disabled (no slow query threshold); set to ms value if desired
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = false
      record_client_address   = false
    }

    maintenance_window {
      day          = 7   # Sunday
      hour         = 4   # 4am UTC
      update_track = "stable"
    }

    user_labels = {
      app = "orc-bot"
      env = "prod"
    }
  }

  depends_on = [
    google_service_networking_connection.private_vpc_connection,
  ]
}

# ─────────────────────────────────────────────
# Database and user
# ─────────────────────────────────────────────

resource "google_sql_database" "orc_bot" {
  name     = "orc_bot"
  instance = google_sql_database_instance.orc_bot_db.name
}

resource "google_sql_user" "orc_bot" {
  name     = "orc_bot"
  instance = google_sql_database_instance.orc_bot_db.name
  password = random_password.db_password.result
}

# ─────────────────────────────────────────────
# Log sink — 60-day retention in Cloud Logging
# ─────────────────────────────────────────────

# GCP's default log retention is 30 days. This log bucket extends it to 60.
resource "google_logging_project_bucket_config" "orc_bot_logs" {
  project        = var.project_id
  location       = "global"
  bucket_id      = "orc-bot-logs"
  retention_days = 60
  description    = "ORC bot application and database logs — 60-day retention"
}

resource "google_logging_project_sink" "orc_bot_sink" {
  name        = "orc-bot-log-sink"
  destination = "logging.googleapis.com/projects/${var.project_id}/locations/global/buckets/orc-bot-logs"

  # Capture logs from the bot VM and Cloud SQL instance.
  filter = <<-EOT
    resource.labels.instance_id="${google_compute_instance.orc_bot_vm.instance_id}"
    OR resource.type="cloudsql_database"
    AND resource.labels.database_id="${var.project_id}:${google_sql_database_instance.orc_bot_db.name}"
  EOT

  unique_writer_identity = true
}
