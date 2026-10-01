#!/usr/bin/env bash
# Deploy RockDove server to the shared team host (non-root, dev mode).
# Uses the merged branch (Jev + neo4j routing + relay).
#
# Host:     crviser@100.101.120.123   (hostname "martillo")
# Method:   rsync --exclude (no git, no local .env, no mocks/binaries)
# Port:     8090 via docker-compose.override.yml (8080 is taken on that host)
# Stack:    server + redis + neo4j (keycloak starts but is unused in dev mode)
# Auth:     OIDC disabled (dev mode) + per-agent device tokens.
#
# Usage:
#   ./scripts/deploy-shared.sh [host]
# Default host: crviser@100.101.120.123
set -euo pipefail

HOST="${1:-crviser@100.101.120.123}"
REMOTE_DIR="~/rockdove"

cd "$(dirname "$0")/.."        # repo root
REPO_ROOT="$(pwd)"

echo "==> [1/5] rsync repo (excluding local-only stuff) to ${HOST}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude 'client/agent/run/' \
  --exclude 'client/agent/.venv/' \
  --exclude 'client/node_modules/' \
  --exclude 'server/.venv/' \
  --exclude '*.xlsx' \
  --exclude '*.docx' \
  --exclude '*:Zone.Identifier' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  -e ssh "${REPO_ROOT}/" "${HOST}:${REMOTE_DIR}/"

echo "==> [2/5] write server .env (dev mode) on remote"
# Jev stays disabled on the shared host unless the team wants live decisions.
# Set JEV_ENABLED=true + OPENROUTER_API_KEY to enable AI routing there.
ssh "$HOST" "cat > ${REMOTE_DIR}/.env" <<'ENV'
SERVER_URL=http://localhost:8090
REDIS_URL=redis://localhost:6379/0
HEARTBEAT_TTL_S=30
OIDC_ENABLED=false
# INVITE_SECRET=change-me-in-production
# AGENT_SERVICE_TOKEN=rockdove-service-dev
JEV_ENABLED=false
ENV

echo "==> [3/5] bring up the stack on 8090 (override maps 8090:8080)"
ssh "$HOST" "cd ${REMOTE_DIR}/server && docker compose up --build -d"

echo "==> [4/5] wait for health"
ok=""
for i in $(seq 1 45); do
  if ssh "$HOST" "curl -sf http://localhost:8090/health >/dev/null 2>&1"; then
    echo "    server healthy after ${i}s"
    ok=1
    break
  fi
  sleep 1
done
if [ -z "$ok" ]; then
  echo "ERROR: server did not become healthy. Checking logs..."; exit 1
fi

echo ""
echo "==> [5/5] summary"
PUB_IP=$(echo "$HOST" | awk -F@ '{print $2}')
echo "    Server (docs):   http://${PUB_IP}:8090/docs"
echo "    Jev status:      http://${PUB_IP}:8090/jev/status"
echo "    Neo4j (browser): http://${PUB_IP}:7474  (neo4j/password123)"
echo ""
echo "Generar un device token por agente con (admin token requerido en OIDC;"
echo "en dev mode se acepta cualquier Bearer):"
echo "  curl -X POST http://${PUB_IP}:8090/device-tokens/ \\"
echo "    -H 'Authorization: Bearer any' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"label\":\"peer-bob\",\"peer_id\":\"peer-bob\",\"ttl_seconds\":null}'"