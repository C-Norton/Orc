#!/bin/bash
# CHANGE: renamed from kaz-bot to orc-bot throughout
# Startup script for orc-bot VM.
# Runs on first boot and on every VM restart.
# Idempotent — safe to run multiple times.

set -euo pipefail
# CHANGE: removed logger -t pipe — logger lives in util-linux which isn't installed yet
# at the point this line executes. Writing directly to the log file is sufficient;
# systemd's journal captures stdout/stderr from the service unit anyway.
exec > >(tee /var/log/orc-startup.log) 2>&1

echo "=== orc-bot startup: $(date) ==="  # CHANGE: renamed


# ─────────────────────────────────────────────
# 1. System updates
# ─────────────────────────────────────────────

apt-get update -qq
apt-get install -y -qq \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    util-linux

# ─────────────────────────────────────────────
# 2. Install Docker (official repo)
# ─────────────────────────────────────────────

if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/debian \
      $(lsb_release -cs) stable" \
      > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -qq \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin

    systemctl enable docker
    systemctl start docker
    echo "Docker installed."
else
    echo "Docker already installed, skipping."
fi

# ─────────────────────────────────────────────
# 3. Fetch secrets from Secret Manager
# ─────────────────────────────────────────────
# CHANGE: section renamed from "Fetch Discord token" to "Fetch secrets";
#         now fetches both Discord token and DB password.
#         Uses the VM's service account — no credentials file needed.

PROJECT_ID=$(curl -sf \
    "http://metadata.google.internal/computeMetadata/v1/project/project-id" \
    -H "Metadata-Flavor: Google")

ACCESS_TOKEN=$(curl -sf \
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
    -H "Metadata-Flavor: Google" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Helper: fetch a secret version by name
fetch_secret() {
    local secret_name="$1"
    curl -sf \
        "https://secretmanager.googleapis.com/v1/projects/${PROJECT_ID}/secrets/${secret_name}/versions/latest:access" \
        -H "Authorization: Bearer ${ACCESS_TOKEN}" \
        | python3 -c "import sys,json,base64; print(base64.b64decode(json.load(sys.stdin)['payload']['data']).decode())"
}

DISCORD_TOKEN_VALUE=$(fetch_secret "orc-bot-discord-token")
DB_PASSWORD_VALUE=$(fetch_secret "orc-bot-db-password")
# CHANGE: added — fetch Discord public key and application ID from Secret Manager
DISCORD_PUBLIC_KEY_VALUE=$(fetch_secret "orc-bot-discord-public-key")
DISCORD_APP_ID_VALUE=$(fetch_secret "orc-bot-discord-app-id")

# Fetch Cloud SQL private IP from instance metadata attribute written by Terraform.
# The startup script cannot reference Terraform outputs directly; the private IP is
# passed in via a custom metadata key set during provisioning.
DB_PRIVATE_IP=$(curl -sf \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/db-private-ip" \
    -H "Metadata-Flavor: Google" || echo "")

# Write to a root-readable-only env file — not world-readable.
# CHANGE: added LOG_LEVEL (plain value, not a secret), DISCORD_PUBLIC_KEY, DISCORD_APP_ID
ENV_FILE="/etc/orc-bot.env"
cat > "$ENV_FILE" <<EOF
LOG_LEVEL=INFO
DISCORD_API_TOKEN=${DISCORD_TOKEN_VALUE}
DISCORD_PUBLIC_KEY=${DISCORD_PUBLIC_KEY_VALUE}
DISCORD_APP_ID=${DISCORD_APP_ID_VALUE}
DATABASE_URL=postgresql+psycopg2://orc_bot:${DB_PASSWORD_VALUE}@${DB_PRIVATE_IP}:5432/orc_bot
EOF
chmod 600 "$ENV_FILE"
echo "Secrets written to $ENV_FILE."

# ─────────────────────────────────────────────
# 4. Install Python 3.13 and system dependencies
# ─────────────────────────────────────────────
# Debian 13 (Trixie) ships Python 3.13 in its standard repos — no PPA needed.
# libpq-dev + gcc are required to build psycopg2 from source via pip.

apt-get install -y -qq \
    python3 \
    python3-venv \
    python3-pip \
    git \
    libpq-dev \
    gcc

echo "Python $(python3 --version) installed."

# ─────────────────────────────────────────────
# 5. Provision the bot directory and venv
# ─────────────────────────────────────────────
# CHANGE: replaced docker-compose.yml write with venv setup under /opt/orc.
# The repo itself is deployed here by GitHub Actions on each push to master.
# On first boot we create the directory and venv; Actions handles git clone/pull.

mkdir -p /opt/orc
chown -R root:root /opt/orc
chmod 755 /opt/orc

# Grant the deploy service account passwordless sudo for service restart only.
# The unique ID is passed in via instance metadata by Terraform — no API call needed.
DEPLOY_SA_UNIQUE_ID=$(curl -sf \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/deploy-sa-unique-id" \
    -H "Metadata-Flavor: Google" || echo "unknown")

DEPLOY_SA_USER="sa_${DEPLOY_SA_UNIQUE_ID}"

if [ "$DEPLOY_SA_UNIQUE_ID" != "unknown" ]; then
    echo "${DEPLOY_SA_USER} ALL=(ALL) NOPASSWD: /bin/systemctl restart orc-bot.service, /bin/systemctl is-active orc-bot.service" \
        > /etc/sudoers.d/orc-bot-deploy
    chmod 440 /etc/sudoers.d/orc-bot-deploy
    echo "Sudoers rule written for ${DEPLOY_SA_USER}."
else
    echo "WARNING: Could not read deploy SA unique ID from metadata — sudoers rule not written."
    echo "Run terraform apply to ensure the metadata attribute is set, then re-run startup.sh."
fi

# Create the venv if it doesn't exist yet.
if [ ! -d /opt/orc/.venv ]; then
    python3 -m venv /opt/orc/.venv
    echo "venv created at /opt/orc/.venv"
else
    echo "venv already exists, skipping creation."
fi

# ─────────────────────────────────────────────
# 6. systemd service — direct Python process
# ─────────────────────────────────────────────
# CHANGE: replaced Docker Compose systemd unit with a unit that runs
#         python main.py directly inside the venv. EnvironmentFile loads
#         /etc/orc-bot.env so secrets are available to the process without
#         being visible in 'ps' output or the unit file itself.

cat > /etc/systemd/system/orc-bot.service <<'SERVICE'
[Unit]
Description=ORC Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/orc
ExecStart=/opt/orc/.venv/bin/python main.py
EnvironmentFile=/etc/orc-bot.env
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=orc-bot

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable orc-bot.service
echo "orc-bot systemd service registered."

# Don't start yet — GitHub Actions will deploy the code and start the service
# on its first run. The service will fail to start without code in /opt/orc.
echo "Waiting for first GitHub Actions deploy before starting orc-bot."

echo "=== orc-bot startup complete: $(date) ==="
