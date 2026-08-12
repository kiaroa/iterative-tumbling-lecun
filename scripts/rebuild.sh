#!/usr/bin/env bash
# Phase 6a: one-command pipeline rebuild, OSM -> OSRM -> matrices/DB, so the
# service can be rebuilt from a fresh checkout without re-deriving the step
# order from IMPLEMENTATION_PLAN.md's Phase 3a/3b/4b-follow-up/5b-follow-up-1
# entries by hand. See docs/ops.md for what each step does and why the order
# matters (matrices/DB build need a live OSRM; access-anchors needs the DB
# build's gates table).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
OSRM_DIR="${REPO_ROOT}/osrm"

echo "== [1/5] osrm-extract/partition/customize (France) =="
"${OSRM_DIR}/build_france.sh"

# docker-outside-of-docker: docker compose resolves bind-mount sources
# against the HOST filesystem, not this container's /workspace (see
# osrm/README.md) - reuse build_france.sh's own auto-detection so this script
# needs no manual host-path config either.
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

echo "== [2/5] serve OSRM (OSRM_NETWORK=france) =="
export OSRM_NETWORK=france
export OSRM_DATA_DIR="${OSRM_HOST_DIR}/data"
(cd "$OSRM_DIR" && docker compose up -d)

echo "== waiting for OSRM to answer /nearest =="
OSRM_BASE_URL="${OSRM_BASE_URL:-http://localhost:5000}"
for _ in $(seq 1 60); do
  if curl -sf "${OSRM_BASE_URL}/nearest/v1/car/2.3522,48.8566" >/dev/null; then
    echo "OSRM is up."
    break
  fi
  sleep 2
done
if ! curl -sf "${OSRM_BASE_URL}/nearest/v1/car/2.3522,48.8566" >/dev/null; then
  echo "ERROR: OSRM did not become reachable at ${OSRM_BASE_URL}" >&2
  exit 1
fi

echo "== [3/5] precompute national gate-to-gate matrices =="
(cd "$REPO_ROOT" && python3 -m tollroute.matrices)

echo "== [4/5] build the national graph-ready DB =="
(cd "$REPO_ROOT" && python3 -m tollroute.etl.build_national)

echo "== [5/5] precompute toll-free access anchors =="
(cd "$REPO_ROOT" && python3 -m tollroute.etl.access_anchors)

echo "REBUILD_COMPLETE: OSRM serving, matrices + national DB + access anchors rebuilt."
