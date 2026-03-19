variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-east1"
}

variable "zone" {
  description = "GCP zone"
  type        = string
  default     = "us-east1-b"
}

variable "ssh_users" {
  description = "List of OS Login / metadata SSH users to grant IAP tunnel access"
  type        = list(string)
  default     = ["cnorton9", "channing"]
}

variable "discord_token" {
  description = "Discord bot token (written to Secret Manager, not stored in state)"
  type        = string
  sensitive   = true
}

# CHANGE: added — Discord public key from Developer Portal > General Information
variable "discord_public_key" {
  description = "Discord application public key (written to Secret Manager)"
  type        = string
  sensitive   = true
}

# CHANGE: added — Discord application ID from Developer Portal > General Information
variable "discord_app_id" {
  description = "Discord application ID (written to Secret Manager)"
  type        = string
  sensitive   = true
}

# CHANGE: removed data_disk_size_gb — no SQLite disk, DB is now Cloud SQL

variable "bot_image" {
  # CHANGE: updated example image name from kaz-bot to orc-bot
  description = "Docker image to run (e.g. gcr.io/your-project/orc-bot:latest)"
  type        = string
  default     = ""
}

# CHANGE: added — GitHub personal access token for the GitHub provider
# Needs scopes: repo (for branch protection + secrets), workflow
variable "github_token" {
  description = "GitHub personal access token (repo + workflow scopes)"
  type        = string
  sensitive   = true
}
