#!/bin/bash
# Start the portal, or update it to the newest code, once server-setup.sh has run (docs/deploy.md). Run as root:
#
#   /opt/entrylib/portal/deploy/launch.sh            # check the settings, build and start
#   /opt/entrylib/portal/deploy/launch.sh --update   # first fetch the newest portal code
#
# It refuses to start while a setting that only a person can give is missing.
set -euo pipefail

PORTAL="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PORTAL"

if [ "${1:-}" = "--update" ]; then
  git pull -q --ff-only
fi

[ -f .env ] || { echo "no .env: run deploy/server-setup.sh first" >&2; exit 1; }

value() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2-; }

missing=()
for name in PORTAL_DOMAIN POSTGRES_PASSWORD OPENALEX_API_KEY ORCID_CLIENT_ID ORCID_CLIENT_SECRET GITHUB_APP_ID; do
  [ -n "$(value "$name")" ] || missing+=("$name")
done
key="$(value GITHUB_APP_PRIVATE_KEY_PATH)"
if [ "$(value PORTAL_REGISTRY_MODE)" = "github" ] && { [ -z "$key" ] || [ ! -s "$key" ]; }; then
  missing+=("the GitHub App key file (GITHUB_APP_PRIVATE_KEY_PATH=${key:-unset})")
fi
if [ -n "$key" ] && [ -s "$key" ]; then
  # Compose mounts the key into the app's container as a file, where the app runs as its own user: the file is
  # readable, and its folder (server-setup.sh: root only) keeps it from anyone else on the server.
  chmod 0644 "$key"
fi
if [ "$(value POSTGRES_PASSWORD)" = "change-me" ]; then
  missing+=("POSTGRES_PASSWORD (still the example value)")
fi
if [ ${#missing[@]} -gt 0 ]; then
  echo "not started: fill in .env first (docs/deploy.md):" >&2
  printf '  %s\n' "${missing[@]}" >&2
  exit 1
fi

docker compose up -d --build --remove-orphans
# Caddy does not watch its Caddyfile: reload it, so a changed one takes effect (without dropping connections).
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile

domain="$(value PORTAL_DOMAIN)"
echo "waiting for the app..."
for _ in $(seq 60); do
  if docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" 2>/dev/null; then
    echo "the portal is running: https://$domain (check https://$domain/healthz and https://$domain/llms.txt)"
    exit 0
  fi
  sleep 5
done
echo "the app did not become healthy in 5 minutes: docker compose logs app" >&2
exit 1
