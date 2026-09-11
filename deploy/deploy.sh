#!/usr/bin/env sh
# HiveOS v0.1 one-command staging deploy (zero-open bundle).
# Usage: sh deploy/deploy.sh          (from the repo root, after copying .env)
set -e
cd "$(dirname "$0")/.."

if [ ! -f frontend/dist/index.html ]; then
    echo "!! frontend/dist missing - build it first: cd frontend && npm ci && npx vite build"
    exit 1
fi
if [ ! -f deploy/.env ]; then
    echo "!! deploy/.env missing - copy deploy/.env.example to deploy/.env and fill it"
    exit 1
fi

docker compose -f deploy/docker-compose.staging.yml --env-file deploy/.env up -d --build
echo "-- waiting for the API health --"
PORT="'${HIVEOS_HTTP_PORT:-80}'"
for i in $(seq 1 30); do
    if curl -fsS "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
        echo "[ok] HiveOS is up: http://localhost:$PORT (panel: /admin)"
        exit 0
    fi
    sleep 2
done
echo "!! API did not become healthy in 60s - check: docker compose -f deploy/docker-compose.staging.yml logs backend"
exit 1
