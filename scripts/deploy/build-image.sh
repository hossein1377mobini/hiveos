#!/usr/bin/env bash
# HiveOS v0.1 local smoke: build api image the same way CI does (T-S0-4 helper).
# Usage: bash scripts/deploy/build-image.sh [tag]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
TAG="${1:-dev-local}"
docker build -f infrastructure/api.Dockerfile -t "hiveos/api:$TAG" .
echo "built: hiveos/api:$TAG"
