#!/usr/bin/env bash
# HiveOS v0.1 staging rollback (T-S0-4). Runs ON the server.
# Usage: bash deploy/rollback.sh [tag]   (default: .rollback-tag written by last deploy)
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

# .env is root-owned (chmod 600) - compose reads it, so run as root
if [[ $EUID -ne 0 ]]; then echo "FATAL: run with sudo (compose needs to read root-owned .env)"; exit 1; fi

TAG="${1:-$(cat .rollback-tag 2>/dev/null || true)}"
[[ -n "$TAG" ]] || { echo "FATAL: no rollback tag (.rollback-tag missing) and none given"; exit 1; }

echo "[rollback] reverting api to tag=$TAG"
IMAGE_TAG="$TAG" docker compose -f docker-compose.staging.yml up -d

ok=0
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8100/api/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[[ $ok -eq 1 ]] || { echo "[rollback] FAILED healthcheck on tag=$TAG"; exit 1; }

echo "$TAG" > .previous-tag
echo "[rollback] healthy on tag=$TAG"
