output "vm_name" {
  description = "Name of the bot VM"
  value       = google_compute_instance.orc_bot_vm.name # CHANGE: updated ref
}

output "vm_zone" {
  description = "Zone the VM is running in"
  value       = google_compute_instance.orc_bot_vm.zone # CHANGE: updated ref
}

output "iap_ssh_command" {
  description = "Command to SSH into the VM via IAP"
  # CHANGE: updated VM ref
  value       = "gcloud compute ssh ${google_compute_instance.orc_bot_vm.name} --zone=${var.zone} --tunnel-through-iap --project=${var.project_id}"
}

output "service_account_email" {
  description = "Service account used by the VM"
  value       = google_service_account.orc_bot_sa.email # CHANGE: updated ref
}

output "discord_secret_name" {
  description = "Secret Manager secret name for the Discord token"
  value       = google_secret_manager_secret.discord_token.name
}

# CHANGE: added outputs for the two new Discord secrets
output "discord_public_key_secret_name" {
  description = "Secret Manager secret name for the Discord public key"
  value       = google_secret_manager_secret.discord_public_key.name
}

output "discord_app_id_secret_name" {
  description = "Secret Manager secret name for the Discord application ID"
  value       = google_secret_manager_secret.discord_app_id.name
}

# CHANGE: replaced data_disk_name output with Cloud SQL outputs
output "cloudsql_instance_name" {
  description = "Cloud SQL instance name"
  value       = google_sql_database_instance.orc_bot_db.name
}

output "cloudsql_private_ip" {
  description = "Private IP address of the Cloud SQL instance (used in DATABASE_URL)"
  value       = google_sql_database_instance.orc_bot_db.private_ip_address
}

output "cloudsql_connection_name" {
  description = "Cloud SQL connection name (project:region:instance)"
  value       = google_sql_database_instance.orc_bot_db.connection_name
}

output "db_password_secret_name" {
  description = "Secret Manager secret name for the DB password"
  value       = google_secret_manager_secret.db_password.name
}

output "log_bucket_name" {
  description = "Cloud Logging bucket for 60-day log retention"
  value       = google_logging_project_bucket_config.orc_bot_logs.bucket_id
}

# CHANGE: added — WIF and deploy SA outputs for reference
output "wif_provider_name" {
  description = "Full WIF provider resource name (also written to GitHub Actions secret)"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deploy_sa_email" {
  description = "Deploy service account email (also written to GitHub Actions secret)"
  value       = google_service_account.deploy_sa.email
}
