#!/usr/bin/env bash
# HiveOS v0.1 staging deploy (T-S0-4). Runs ON the server from /opt/hiveos/app.
# Usage: sudo bash deploy/remote-deploy.sh <tag>
# Flow: write .env (DATABASE_URL from server-side secret) -> up -d -> alembic -> healthcheck.
# Health = api :8100 direct + host nginx :80 proxy (default site proxies to 127.0.0.1:8100).
# On failed healthcheck: automatic rollback to previous tag, then exit 1.
set -euo pipefail

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
PG_PASS="$(sudo cat "$SECRETS_DIR/pg_password")"
PG_ENC="$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$PG_PASS")"
umask 077
cat > "$APP_DIR/.env" <<EOF
IMAGE_TAG=$TAG
ENVIRONMENT=${ENVIRONMENT:-staging}
DATABASE_URL=postgresql+asyncpg://hiveos:$PG_ENC@db:5432/hiveos
EOF
umask 022

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
