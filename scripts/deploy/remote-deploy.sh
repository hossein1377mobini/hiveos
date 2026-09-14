#!/usr/bin/env bash
# HiveOS v0.1 staging deploy (T-S0-4). Runs ON the server from /opt/hiveos/app.
# Usage: sudo bash deploy/remote-deploy.sh <tag>
# Flow: write .env (DATABASE_URL from server-side secret) -> up -d -> alembic -> healthcheck.
# Health = api :8100 direct + host nginx :80 proxy (default site proxies to 127.0.0.1:8100).
# On failed healthcheck: automatic rollback to previous tag, then exit 1.
set -euo pipefail

# Needs root: reads /opt/hiveos/secrets, writes root-owned .env, drives compose (review R4-3).
if [[ $EUID -ne 0 ]]; then echo "FATAL: run with sudo (needs /opt/hiveos/secrets + root-owned .env)"; exit 1; fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

TAG="${1:?"usage: remote-deploy.sh <tag>"}"
SECRETS_DIR=/opt/hiveos/secrets
PREV_FILE="$APP_DIR/.previous-tag"
ROLLBACK_FILE="$APP_DIR/.rollback-tag"

[[ -f "$SECRETS_DIR/pg_password" ]] || { echo "FATAL: $SECRETS_DIR/pg_password missing"; exit 1; }

# preserve current running tag as rollback target (first deploy has none)
if [[ -f "$PREV_FILE" ]]; then cp "$PREV_FILE" "$ROLLBACK_FILE"; fi

# regenerate .env (chmod 600). ADR-022: secrets only in server-side files, never in git.
PG_PASS="$(cat "$SECRETS_DIR/pg_password")"
PG_ENC="$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$PG_PASS")"
umask 077
# Staging/prod required vars: read from server-side secrets (ADR-022) so a CI
# deploy keeps a fully valid .env. $(cat ) strips the trailing newline.
ADMIN_USER="$(cat "$SECRETS_DIR/system_admin_username")"
ADMIN_PASS="$(cat "$SECRETS_DIR/system_admin_password")"
SMS_SERVICE_ID="$(cat "$SECRETS_DIR/melipayamak_otp_service_id" 2>/dev/null || true)"

cat > "$APP_DIR/.env" <<EOF
IMAGE_TAG=$TAG
ENVIRONMENT=${ENVIRONMENT:-staging}
DATABASE_URL=postgresql+asyncpg://hiveos:$PG_ENC@db:5432/hiveos
SYSTEM_ADMIN_USERNAME=$ADMIN_USER
SYSTEM_ADMIN_PASSWORD=$ADMIN_PASS
INGESTION_ALLOWED_ROOTS=/opt/hiveos/ingestion
STORAGE_ROOT=/opt/hiveos/storage
WALLET_WELCOME_CREDIT=50
ADMIN_SESSION_TTL_HOURS=12
CORS_ORIGINS=https://staging.hivesystem.ir
SMS_PROVIDER=melipayamak
MELIPAYAMAK_OTP_SERVICE_ID=$SMS_SERVICE_ID
EOF
umask 022

# PO decision 2026-09-12: retrieval runs on this host. Defaults live in the
# compose file; these let the PO flip a provider without editing the image.
# Only append when unset, so a PO-set value survives the next deploy.
#
# The heredoc above rewrites .env from scratch, so any variable an operator
# added by hand and that is not repeated here is LOST on the next deploy.
# EMBEDDING_PROVIDER and RERANK_PROVIDER are load-bearing: without them the
# config default ("mock") applies and retrieval stops using the local ONNX
# models. LLM_PROVIDER is recorded here for accuracy and for the admin panel's
# report (admin.py reads settings.llm_provider directly); the live answer path
# resolves the provider from providers_pricing first and only falls back to this
# value, so it is descriptive rather than a switch.
# All three are append-only: an existing value always wins.
grep -q '^EMBEDDING_PROVIDER=' "$APP_DIR/.env" || echo "EMBEDDING_PROVIDER=onnx" >> "$APP_DIR/.env"
grep -q '^RERANK_PROVIDER=' "$APP_DIR/.env" || echo "RERANK_PROVIDER=onnx" >> "$APP_DIR/.env"
grep -q '^LLM_PROVIDER=' "$APP_DIR/.env" || echo "LLM_PROVIDER=openai-compatible" >> "$APP_DIR/.env"

# The int8 graphs the api container mounts read-only. Failing here beats a
# container that boots and then returns EMBEDDING_UNAVAILABLE on every upload.
if [[ ! -f /opt/models/bge-m3-onnx/model.onnx ]]; then
  echo "FATAL: /opt/models/bge-m3-onnx/model.onnx missing - upload the exported models first"
  exit 1
fi

# Host dirs bind-mounted into the api container (compose volumes). The api runs as
# uid 10001, so ownership must match or workspace/brain init fails with 500
# (WORKSPACE_INITIALIZATION_FAILED) - keep this before compose up.
mkdir -p /opt/hiveos/storage /opt/hiveos/ingestion
chown -R 10001:10001 /opt/hiveos/storage /opt/hiveos/ingestion
chmod 750 /opt/hiveos/storage /opt/hiveos/ingestion

echo "[deploy] docker compose up (tag=$TAG)"
docker compose -f docker-compose.staging.yml up -d

echo "[deploy] alembic upgrade head (one-off api container)"
docker compose -f docker-compose.staging.yml run --rm api uv run --no-sync alembic upgrade head

echo "[deploy] healthcheck (direct :8100 + host nginx :80)"
ok=0
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8100/api/health >/dev/null 2>&1 \
     && curl -fsS http://127.0.0.1:80/api/health >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 2
done

if [[ $ok -eq 1 ]]; then
  echo "$TAG" > "$PREV_FILE"
  echo "[deploy] healthy -> tag recorded: $TAG"
else
  echo "[deploy] FAILED healthcheck after 60s"
  if [[ -f "$ROLLBACK_FILE" ]]; then
    echo "[deploy] auto-rollback to $(cat "$ROLLBACK_FILE")"
    bash "$APP_DIR/deploy/rollback.sh" || true
  fi
  exit 1
fi