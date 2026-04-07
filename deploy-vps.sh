#!/usr/bin/env bash
# deploy-vps.sh — Complete one-shot deployment for emergent-atelier
# Run this script on the VPS as root or a user with docker access.
# Usage: bash deploy-vps.sh
set -euo pipefail

REPO_URL="https://github.com/fillsoko/emergent-atelier-trmnl.git"
# Detect existing clone; fall back to /opt if not found in home directory
if [ -d "$HOME/emergent-atelier-trmnl/.git" ]; then
  DEPLOY_DIR="$HOME/emergent-atelier-trmnl"
else
  DEPLOY_DIR="/opt/emergent-atelier-trmnl"
fi
# Read deployment domain from environment; must be set by the operator.
TRMNL_DOMAIN="${TRMNL_DOMAIN:-}"
if [ -z "$TRMNL_DOMAIN" ]; then
  echo "ERROR: TRMNL_DOMAIN is not set."
  echo "  Export it before running: export TRMNL_DOMAIN=emergent-atelier.example.com"
  exit 1
fi

# CADDY_PROXY_SECRET must be pre-set in the environment or loaded from .env.
# Generate with: openssl rand -hex 32
if [ -z "${CADDY_PROXY_SECRET:-}" ]; then
  echo "ERROR: CADDY_PROXY_SECRET must be set in the environment before running this script."
  echo "  source .env && bash deploy-vps.sh"
  echo "  # or: export CADDY_PROXY_SECRET=\$(openssl rand -hex 32)"
  exit 1
fi

echo "=== Emergent Atelier VPS Deploy ==="

# 1. Clone or update repo
if [ -d "$DEPLOY_DIR/.git" ]; then
  echo "-> Pulling latest main..."
  git -C "$DEPLOY_DIR" pull origin main
else
  echo "-> Cloning repo to $DEPLOY_DIR..."
  git clone "$REPO_URL" "$DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"

# 2. Require .env — never generate secrets automatically.
# On first deploy, copy .env.example and fill in all values before running.
if [ ! -f .env ]; then
  echo "ERROR: .env not found in $DEPLOY_DIR."
  echo "  Create it from the template:"
  echo "    cp .env.example .env"
  echo "    \$EDITOR .env"
  echo ""
  echo "Required secrets to generate:"
  echo "  CYCLE_SECRET:       openssl rand -hex 32"
  echo "  CADDY_PROXY_SECRET: openssl rand -hex 32"
  echo "  TRMNL_STORE_KEY:    python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
  echo "  VOTE_IP_SALT:       openssl rand -hex 32"
  exit 1
else
  echo "-> .env found"
fi

# 3. Add Caddy reverse-proxy entry (idempotent)
CADDY_ENTRY="${TRMNL_DOMAIN} {
    header Strict-Transport-Security \"max-age=31536000; includeSubDomains\"
    reverse_proxy localhost:8001 {
        header_up X-Proxy-Secret \${CADDY_PROXY_SECRET}
    }
}"

if grep -q "$TRMNL_DOMAIN" /etc/caddy/Caddyfile 2>/dev/null; then
  echo "-> Caddy entry already present, skipping"
else
  echo "-> Adding Caddy entry for $TRMNL_DOMAIN..."
  echo "" >> /etc/caddy/Caddyfile
  echo "$CADDY_ENTRY" >> /etc/caddy/Caddyfile
  caddy reload --config /etc/caddy/Caddyfile
  echo "-> Caddy reloaded"
fi

# 4. Start container
echo "-> Starting Docker container..."
docker-compose up -d --build

# 5. Verify
echo "-> Waiting 10s for container to start..."
sleep 10

echo "-> Verifying /image.png..."
HTTP_CODE=$(curl -s -o /tmp/ea_test.png -w "%{http_code}" "https://${TRMNL_DOMAIN}/image.png" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  FILE_TYPE=$(file /tmp/ea_test.png 2>/dev/null)
  echo "SUCCESS! HTTP 200 — $FILE_TYPE"
  echo ""
  echo "=== DEPLOYMENT COMPLETE ==="
  echo "Public URL: https://${TRMNL_DOMAIN}/image.png"
else
  echo "WARNING: Got HTTP $HTTP_CODE from https://${TRMNL_DOMAIN}/image.png"
  echo "Check container logs: docker-compose logs -f"
fi
