#!/usr/bin/env bash
# Run docker compose for the Zetaris stack with Coverage Detective's data mount.
#
#   scripts/zetaris/compose.sh up -d driver     # apply the mount (recreates the driver only)
#   scripts/zetaris/compose.sh ps
#
# Use this instead of a plain `docker compose` in the zetaris-platform folder: a plain
# `docker compose up -d` there recreates the driver WITHOUT the mount.
# ZETARIS_PLATFORM_DIR defaults to ~/zetaris-platform. Nothing in that folder is changed.
set -euo pipefail
REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PLATFORM="${ZETARIS_PLATFORM_DIR:-$HOME/zetaris-platform}"
export COVERAGE_DATA_DIR="$REPO/data/processed"
cd "$PLATFORM"
exec docker compose -f docker-compose.yml -f "$REPO/zetaris/docker-compose.coverage.yml" "$@"
