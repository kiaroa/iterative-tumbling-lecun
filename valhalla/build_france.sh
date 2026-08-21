#!/usr/bin/env bash
# Build Valhalla tiles for the full and toll-free France instances.
#
# Steps:
#   1. Install osmium-tool if not present.
#   2. Strip toll=yes ways from france.osm.pbf → france-notoll.osm.pbf.
#   3. Build tiles for the full instance (valhalla/data/full/).
#   4. Build tiles for the notoll instance (valhalla/data/notoll/).
#
# Each instance mounts its data/ subdirectory as /custom_files inside the
# Valhalla container. The container auto-generates valhalla.json and builds
# tiles from the PBF on first run, then serves on subsequent runs.
#
# After this script completes, start the services with:
#   VALHALLA_DATA_DIR=$(./build_france.sh --print-host-dir) docker compose up -d
# or set VALHALLA_DATA_DIR manually (see docker-compose.yml).
#
# docker-outside-of-docker: if running inside a devcontainer, volume mounts
# resolve against the HOST filesystem. Set VALHALLA_HOST_DIR to the host-side
# path of this valhalla/ directory to override auto-detection.
set -euo pipefail

VALHALLA_IMAGE="${VALHALLA_IMAGE:-valhalla/valhalla:run-latest}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OSRM_PBF="${SCRIPT_DIR}/../osrm/data/france.osm.pbf"
FULL_DATA_DIR="${SCRIPT_DIR}/data/full"
NOTOLL_DATA_DIR="${SCRIPT_DIR}/data/notoll"
NOTOLL_PBF="${NOTOLL_DATA_DIR}/france-notoll.osm.pbf"

# -- Resolve host-side path for docker -v (docker-outside-of-docker) --------
if [ -n "${VALHALLA_HOST_DIR:-}" ]; then
    HOST_DIR="$VALHALLA_HOST_DIR"
else
    # Try to detect host path from running devcontainer (same trick as osrm/build_france.sh).
    HOST_WORKSPACE=$(docker inspect "$(hostname)" 2>/dev/null \
        | python3 -c "import sys,json; mounts=[m for m in json.load(sys.stdin)[0]['Mounts'] if m['Destination']=='/workspace']; print(mounts[0]['Source'] if mounts else '')" 2>/dev/null || true)
    if [ -n "$HOST_WORKSPACE" ]; then
        HOST_DIR="${HOST_WORKSPACE}/valhalla"
    else
        HOST_DIR="$SCRIPT_DIR"
    fi
fi
HOST_FULL_DATA_DIR="${HOST_DIR}/data/full"
HOST_NOTOLL_DATA_DIR="${HOST_DIR}/data/notoll"

echo "==> Host data dirs: full=${HOST_FULL_DATA_DIR}  notoll=${HOST_NOTOLL_DATA_DIR}"

mkdir -p "$FULL_DATA_DIR" "$NOTOLL_DATA_DIR"

# -- 1. osmium-tool -----------------------------------------------------------
if ! command -v osmium &>/dev/null; then
    echo "==> Installing osmium-tool ..."
    sudo apt-get install -y osmium-tool
fi

# -- 2. Strip toll ways -------------------------------------------------------
# French autoroutes carry toll=yes on route=road relations, not directly on
# ways, so `w/toll=yes` alone misses them. Two-pass approach:
#   a) Extract all ways that are either directly tagged toll=yes or are members
#      of a relation tagged toll=yes (-r = complete referenced objects).
#   b) Collect their way IDs, then use osmium getid --invert-match to exclude
#      those ways from the full PBF.
if [ -f "$NOTOLL_PBF" ]; then
    echo "==> france-notoll.osm.pbf already present; skipping strip."
else
    echo "==> Stripping toll ways from france.osm.pbf (two-pass: relations + direct) ..."
    TOLL_REFS="${NOTOLL_DATA_DIR}/toll_refs.osm.pbf"
    TOLL_IDS="${NOTOLL_DATA_DIR}/toll_way_ids.txt"

    # Pass 1: collect all toll-tagged objects (relations with toll=yes and
    # their member ways via -r, plus ways directly tagged toll=yes).
    osmium tags-filter -r "$OSRM_PBF" r/toll=yes w/toll=yes -o "$TOLL_REFS"

    # Pass 2+3: write notoll PBF directly via pyosmium, excluding toll way IDs.
    # (osmium getid has no --invert-match; pyosmium avoids an intermediate ID file.)
    python3 -c "
import osmium
class IDExtract(osmium.SimpleHandler):
    def __init__(self): super().__init__(); self.way_ids = set()
    def way(self, w): self.way_ids.add(w.id)
h = IDExtract()
h.apply_file('$TOLL_REFS')
toll_ids = h.way_ids
print(f'==> {len(toll_ids)} toll ways to exclude')

class NotollWriter(osmium.SimpleHandler):
    def __init__(self, writer):
        super().__init__(); self.writer = writer; self.dropped = 0
    def node(self, n): self.writer.add_node(n)
    def way(self, w):
        if w.id in toll_ids: self.dropped += 1
        else: self.writer.add_way(w)
    def relation(self, r): self.writer.add_relation(r)

writer = osmium.SimpleWriter('$NOTOLL_PBF', overwrite=True)
try:
    h2 = NotollWriter(writer)
    h2.apply_file('$OSRM_PBF', locations=False)
    print(f'==> Dropped {h2.dropped} ways')
finally:
    writer.close()
"
    rm -f "$TOLL_REFS"
    echo "==> Stripped PBF written to ${NOTOLL_PBF} ($(du -sh "$NOTOLL_PBF" | cut -f1))"
fi

# -- Helper: build tiles for one instance ------------------------------------
build_tiles() {
    local label="$1"
    local host_data_dir="$2"
    local pbf_name="$3"   # filename only, must already be in host_data_dir

    echo ""
    echo "==> Building tiles for ${label} (${pbf_name}) ..."

    # Step 1: generate valhalla.json config (writes to /custom_files/valhalla.json)
    docker run --rm \
        -v "${host_data_dir}:/custom_files" \
        "$VALHALLA_IMAGE" \
        bash -c "
            valhalla_build_config \
                --mjolnir-tile-dir /custom_files/valhalla_tiles \
                --mjolnir-timezone /custom_files/valhalla_tiles/timezones.sqlite \
                --mjolnir-admin /custom_files/valhalla_tiles/admins.sqlite \
            > /custom_files/valhalla.json
            # Raise matrix limits: 100×100 blocks = 10,000 pairs; allow 50,000 with margin.
            python3 -c \"
import json, sys
with open('/custom_files/valhalla.json') as f: cfg = json.load(f)
cfg.setdefault('service_limits', {}).setdefault('auto', {})
cfg['service_limits']['auto']['max_matrix_locations'] = 500
cfg['service_limits']['auto']['max_matrix_location_pairs'] = 50000
cfg['service_limits']['auto']['max_matrix_distance'] = 5000000.0
cfg['service_limits']['auto']['max_matrix_time'] = 86400.0
with open('/custom_files/valhalla.json', 'w') as f: json.dump(cfg, f, indent=2)
\"
        "

    # Step 2: build tiles
    docker run --rm \
        -v "${host_data_dir}:/custom_files" \
        "$VALHALLA_IMAGE" \
        valhalla_build_tiles -c /custom_files/valhalla.json "/custom_files/${pbf_name}"

    echo "==> Tiles built for ${label}."
}

# -- 3. Full instance tiles ---------------------------------------------------
if [ -d "${FULL_DATA_DIR}/valhalla_tiles" ] && [ "$(ls -A "${FULL_DATA_DIR}/valhalla_tiles")" ]; then
    echo "==> Full tiles already present; skipping full build."
else
    # Hard-link the source PBF so the container can find it without a copy.
    if [ ! -f "${FULL_DATA_DIR}/france.osm.pbf" ]; then
        ln "$OSRM_PBF" "${FULL_DATA_DIR}/france.osm.pbf" || \
            cp "$OSRM_PBF" "${FULL_DATA_DIR}/france.osm.pbf"
    fi
    build_tiles "full" "$HOST_FULL_DATA_DIR" "france.osm.pbf"
fi

# -- 4. Notoll instance tiles -------------------------------------------------
if [ -d "${NOTOLL_DATA_DIR}/valhalla_tiles" ] && [ "$(ls -A "${NOTOLL_DATA_DIR}/valhalla_tiles")" ]; then
    echo "==> Notoll tiles already present; skipping notoll build."
else
    build_tiles "notoll" "$HOST_NOTOLL_DATA_DIR" "france-notoll.osm.pbf"
fi

echo ""
echo "==> Done. Start services with:"
echo "    VALHALLA_DATA_DIR=${HOST_DIR}/data docker compose up -d"
