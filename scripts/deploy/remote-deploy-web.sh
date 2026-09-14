#!/usr/bin/env bash
# HiveOS frontend deploy. Runs ON the server from /opt/hiveos/app.
#
# Usage: sudo bash deploy/remote-deploy-web.sh <dist-tarball> <tag>
#
# Why this exists: CI published only the API image, so every frontend change
# needed a manual copy into /var/www/hiveos/dist. Whenever that was forgotten
# the repo moved ahead of the live site with no failing check anywhere. This
# script closes that gap and is called from the same CI job.
#
# The swap is a directory rename, not an untar over the live tree: a request
# arriving mid-copy would otherwise see index.html referencing an asset that is
# not there yet, and the page would 404 on its own bundle.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "FATAL: run with sudo (owns /var/www/hiveos)"; exit 1; fi

TARBALL="${1:?"usage: remote-deploy-web.sh <dist-tarball> <tag>"}"
TAG="${2:?"usage: remote-deploy-web.sh <dist-tarball> <tag>"}"
WEB_ROOT=/var/www/hiveos
LIVE="$WEB_ROOT/dist"
STAGING="$WEB_ROOT/.dist-incoming-$$"
BACKUP_DIR="$WEB_ROOT/webbak"

[[ -f "$TARBALL" ]] || { echo "FATAL: tarball not found: $TARBALL"; exit 1; }

echo "[web] deploying frontend $TAG"

# Extract beside the live tree, then verify before anything is swapped.
rm -rf "$STAGING"
mkdir -p "$STAGING"
tar -xzf "$TARBALL" -C "$STAGING"

# A build that lost its entry point would take the site down. Check the pieces
# index.html actually references are present, since that is what the browser
# asks for.
if [[ ! -f "$STAGING/index.html" ]]; then
  echo "FATAL: tarball has no index.html - refusing to deploy"
  rm -rf "$STAGING"
  exit 1
fi
missing=0
while IFS= read -r asset; do
  [[ -z "$asset" ]] && continue
  if [[ ! -f "$STAGING/$asset" ]]; then
    echo "FATAL: index.html references a missing asset: $asset"
    missing=1
  fi
done < <(grep -oE 'assets/[A-Za-z0-9_.-]+\.(js|css)' "$STAGING/index.html" | sort -u)
if [[ $missing -eq 1 ]]; then
  echo "FATAL: incomplete build - refusing to deploy"
  rm -rf "$STAGING"
  exit 1
fi

echo "[web] previous dist -> $TAG"

# Keep the previous tree so a bad deploy is one mv away from being undone.
if [[ -d "$LIVE" ]]; then
  mkdir -p "$BACKUP_DIR"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  tar -czf "$BACKUP_DIR/dist-before-$TAG-$STAMP.tgz" -C "$WEB_ROOT" dist
  # Retain the most recent 5: this is a rollback aid, not an archive.
  ls -1t "$BACKUP_DIR"/dist-before-*.tgz 2>/dev/null | tail -n +6 | xargs -r rm -f
fi

# Swap. The old tree is moved aside rather than deleted so the rename of the
# new one into place cannot fail on a non-empty directory.
OLD="$WEB_ROOT/.dist-previous-$$"
if [[ -d "$LIVE" ]]; then mv "$LIVE" "$OLD"; fi
mv "$STAGING" "$LIVE"
rm -rf "$OLD"

chown -R www-data:www-data "$LIVE"
find "$LIVE" -type d -exec chmod 755 {} \;
find "$LIVE" -type f -exec chmod 644 {} \;

# Report what is actually referenced now. Stale hashed chunks are harmless
# (index.html names none of them) and are left alone: deleting files inside a
# live tree risks removing something a cached page still asks for.
echo "[web] served assets:"
grep -oE 'assets/[A-Za-z0-9_.-]+\.(js|css)' "$LIVE/index.html" | sort -u | sed 's/^/  /'

# Prove it through nginx, not just on disk.
if ! curl -fsS http://127.0.0.1/ -o /dev/null; then
  echo "FATAL: host nginx is not serving the new build"
  exit 1
fi

echo "[web] done: $TAG"
