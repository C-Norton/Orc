# ─────────────────────────────────────────────
# Secret Manager — bot credentials
# ─────────────────────────────────────────────

# CHANGE: renamed secret_id and labels from kaz-bot to orc-bot
resource "google_secret_manager_secret" "discord_token" {
  secret_id = "orc-bot-discord-token"

  replication {
    auto {}
  }

  labels = {
    app = "orc-bot"
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "discord_token" {
  secret      = google_secret_manager_secret.discord_token.id
  secret_data = var.discord_token
}

# CHANGE: added — Discord public key secret
resource "google_secret_manager_secret" "discord_public_key" {
  secret_id = "orc-bot-discord-public-key"

  replication {
    auto {}
  }

  labels = {
    app = "orc-bot"
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "discord_public_key" {
  secret      = google_secret_manager_secret.discord_public_key.id
  secret_data = var.discord_public_key
}

# CHANGE: added — Discord application ID secret
resource "google_secret_manager_secret" "discord_app_id" {
  secret_id = "orc-bot-discord-app-id"

  replication {
    auto {}
  }

  labels = {
    app = "orc-bot"
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "discord_app_id" {
  secret      = google_secret_manager_secret.discord_app_id.id
  secret_data = var.discord_app_id
}

# CHANGE: added DB password secret — value comes from random_password in database.tf
resource "google_secret_manager_secret" "db_password" {
  secret_id = "orc-bot-db-password"

  replication {
    auto {}
  }

  labels = {
    app = "orc-bot"
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}

# WorldAnvil API key — placeholder for future use.
# Uncomment when ready to integrate WorldAnvil.
#
# resource "google_secret_manager_secret" "worldanvil_token" {
#   secret_id = "orc-bot-worldanvil-token"   # CHANGE: updated name prefix
#   replication { auto {} }
#   labels = { app = "orc-bot" }             # CHANGE: updated label
#   depends_on = [google_project_service.apis]
# }
#
# resource "google_secret_manager_secret_version" "worldanvil_token" {
#   secret      = google_secret_manager_secret.worldanvil_token.id
#   secret_data = var.worldanvil_token
# }
