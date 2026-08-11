#!/usr/bin/env bash
# Phase 3a: national France OSRM MLD build, reusing the Phase 1a forked profile.
#
# Downloads the Geofabrik France extract (~5 GB PBF) and runs the full MLD pipeline
# (osrm-extract -> osrm-partition -> osrm-customize) in Docker with the same
# `car_toll.lua` profile as the regional Phase 1a build, producing `data/france.osrm.*`.
# Serve the result with `OSRM_NETWORK=france docker compose up -d` (france is the
# compose default; the regional extract is still servable with OSRM_NETWORK=bfc-ara).
#
# docker-outside-of-docker: this devcontainer shares the host's Docker daemon, so
# bind-mount sources in `docker run -v` resolve against the HOST filesystem, not this
# container's /workspace. The host path of osrm/ is auto-detected from whichever running
# container mounts /workspace; override with OSRM_HOST_DIR if detection fails.
set -euo pipefail

OSRM_IMAGE="${OSRM_IMAGE:-ghcr.io/project-osrm/osrm-backend:latest}"
NETWORK="france"
PBF_URL="${PBF_URL:-https://download.geofabrik.de/europe/france-latest.osm.pbf}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # container-side .../osrm
DATA_DIR="${SCRIPT_DIR}/data"
mkdir -p "$DATA_DIR"

# Resolve the HOST path of osrm/ for `docker run -v` (see README's docker-outside-of-docker note).
if [ -z "${OSRM_HOST_DIR:-}" ]; then
  host_ws=""
  for cid in $(docker ps -q); do
    m=$(docker inspect "$cid" \
      --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}' \
      2>/dev/null || true)
    if [ -n "$m" ]; then host_ws="$m"; break; fi
  done
  if [ -z "$host_ws" ]; then
    echo "ERROR: could not auto-detect the host /workspace mount; set OSRM_HOST_DIR" >&2
    exit 1
  fi
  OSRM_HOST_DIR="${host_ws}/osrm"
fi
echo "Host osrm dir (for docker -v): ${OSRM_HOST_DIR}"

# 1. Download the France PBF, skipping if already present with the expected remote size.
PBF="${DATA_DIR}/${NETWORK}.osm.pbf"
remote_size=$(curl -sSL -I "$PBF_URL" \
  | awk 'tolower($1)=="content-length:"{s=$2} END{gsub(/\r/,"",s); print s}')
if [ -f "$PBF" ] && [ -n "$remote_size" ] && [ "$(stat -c%s "$PBF")" = "$remote_size" ]; then
  echo "France PBF already present and size-matches (${remote_size} bytes); skipping download."
else
  echo "Downloading France PBF (${remote_size:-unknown} bytes) from ${PBF_URL} ..."
  curl -sSL -o "$PBF" "$PBF_URL"
  echo "Downloaded $(stat -c%s "$PBF") bytes to ${PBF}"
fi

run_osrm() { docker run --rm -v "${OSRM_HOST_DIR}:/data" "$OSRM_IMAGE" "$@"; }

# 2. MLD build. car_toll.lua + lib/ live at the mount root (/data), same as Phase 1a.
echo "== osrm-extract (France) =="
run_osrm osrm-extract -p /data/car_toll.lua "/data/data/${NETWORK}.osm.pbf"
echo "== osrm-partition (France) =="
run_osrm osrm-partition "/data/data/${NETWORK}.osrm"
echo "== osrm-customize (France) =="
run_osrm osrm-customize "/data/data/${NETWORK}.osrm"

echo "PHASE_3A_BUILD_DONE: data/${NETWORK}.osrm.* ready — serve with 'OSRM_NETWORK=france docker compose up -d'"
