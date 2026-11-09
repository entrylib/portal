#!/bin/bash
# Prepare a fresh Ubuntu 24.04 server for the portal (design §13, docs/deploy.md). Run as root, once; running it
# again changes nothing that is already set up. cloud-init.yaml runs it when the Droplet is created.
#
# It installs Docker, a firewall, swap, automatic security updates and a daily restart of the app, and writes .env
# with production values and a generated database password. It does not start the portal: fill in .env and the
# GitHub App key first, then run deploy/launch.sh.
set -euo pipefail

ROOT=/opt/entrylib
PORTAL="$ROOT/portal"
SECRETS="$ROOT/secrets"
export DEBIAN_FRONTEND=noninteractive

log() { echo "entrylib setup: $*"; }

# Docker, from Docker's own repository (Ubuntu's packages lag behind compose features the portal uses).
if ! command -v docker >/dev/null; then
  log "installing Docker"
  apt-get update -q
  apt-get install -yq ca-certificates curl git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# Container logs rotate instead of filling the disk.
if [ ! -f /etc/docker/daemon.json ]; then
  echo '{"log-driver": "local", "log-opts": {"max-size": "20m", "max-file": "5"}}' > /etc/docker/daemon.json
  systemctl restart docker
fi

# Firewall: SSH, HTTP (certificates and the redirect to HTTPS) and HTTPS only.
apt-get install -yq ufw unattended-upgrades
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

# Security updates install themselves.
echo 'APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";' > /etc/apt/apt.conf.d/20auto-upgrades

# 2 GB of swap, so building the images does not run out of memory.
if ! swapon --show | grep -q .; then
  log "adding swap"
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# The portal's code.
mkdir -p "$ROOT"
if [ ! -d "$PORTAL/.git" ]; then
  git clone -q https://github.com/entrylib/portal "$PORTAL"
fi

# Secrets live outside the checkout, readable by root only.
install -d -m 700 "$SECRETS"

# .env: production values and a generated database password. Values only a person can give are left empty, and
# launch.sh refuses to start until they are filled in.
if [ ! -f "$PORTAL/.env" ]; then
  log "writing $PORTAL/.env"
  umask 077
  cat > "$PORTAL/.env" <<EOF
# The portal's settings (docs/deploy.md). Never commit or share this file.
PORTAL_DOMAIN=entrylib.org
PORTAL_ENV=production
POSTGRES_PASSWORD=$(openssl rand -hex 32)

PORTAL_GIT_NAME=EntryLib
PORTAL_GIT_EMAIL=registry@entrylib.org

# Fill these in (docs/deploy.md says where each comes from):
OPENALEX_API_KEY=
ORCID_BASE=https://orcid.org
ORCID_CLIENT_ID=
ORCID_CLIENT_SECRET=
PORTAL_REGISTRY_MODE=github
GITHUB_REGISTRY=entrylib/registry
GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY_PATH=$SECRETS/github-app.pem
EOF
  umask 022
fi

# The app restarts every day at 04:17 UTC, which installs the newest claimset (design §10, deploy/start.sh).
cat > /etc/systemd/system/entrylib-restart.service <<EOF
[Unit]
Description=Restart the EntryLib app (installs the newest claimset)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$PORTAL
ExecStart=/usr/bin/docker compose restart app
EOF
cat > /etc/systemd/system/entrylib-restart.timer <<'EOF'
[Unit]
Description=Restart the EntryLib app daily

[Timer]
OnCalendar=*-*-* 04:17:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now entrylib-restart.timer >/dev/null

log "done. Next: fill in $PORTAL/.env, put the GitHub App key at $SECRETS/github-app.pem, then run $PORTAL/deploy/launch.sh"
