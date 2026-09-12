#!/usr/bin/env bash
# HiveOS staging disk housekeeping. Deploy/transfer tars in ~ are transient bundles
# already consumed into docker image builds; purge >48h. Rotate old DB dumps.
set -e
find /home/ubuntu -maxdepth 1 -type f \( -name "*.tar.gz" -o -name "*.tar" -o -name "*.tgz" \) -mtime +2 -delete 2>/dev/null || true
find /opt/hiveos/backups -type f -mtime +7 -name "*.dump" -delete 2>/dev/null || true
