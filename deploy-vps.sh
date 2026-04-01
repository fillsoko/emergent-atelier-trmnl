#!/usr/bin/env bash
# deploy-vps.sh — Complete one-shot deployment for emergent-atelier on REDACTED_VPS_IP
# Run this script on the VPS as root or a user with docker access.
# Usage: bash deploy-vps.sh
set -euo pipefail

REPO_URL="https://github.com/fillsoko/emergent-atelier-trmnl.git"
DEPLOY_DIR="/opt/emergent-atelier-trmnl"
TRMNL_DOMAIN="emergent-atelier.filipsokolowski.com"
CADDY_PROXY_SECRET="REDACTED_PROXY_SECRET"

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

# 2. Write .env (secrets pre-generated, TRMNL marketplace creds optional for now)
if [ ! -f .env ]; then
  echo "-> Writing .env..."
  cat > .env <<'ENVEOF'
CYCLE_SECRET=REDACTED_CYCLE_SECRET
TRMNL_STORE_KEY=REDACTED_STORE_KEY
CADDY_PROXY_SECRET=REDACTED_PROXY_SECRET
REQUIRE_PROXY_SECRET=true
TRMNL_PUBLIC_URL=https://emergent-atelier.filipsokolowski.com
TRMNL_CLIENT_ID=
TRMNL_CLIENT_SECRET=
ENVEOF
else
  echo "-> .env already exists, skipping (edit manually if needed)"
fi

# 3. Add Caddy reverse-proxy entry (idempotent)
CADDY_ENTRY="${TRMNL_DOMAIN} {
    header Strict-Transport-Security \"max-age=31536000; includeSubDomains\"
    reverse_proxy localhost:8001 {
        header_up X-Proxy-Secret ${CADDY_PROXY_SECRET}
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
