# OSRM regional setup (Phase 1a)

Regional OSRM instance for the toll-minimising route service, covering the historic
Bourgogne, Franche-Comte, Auvergne and Rhone-Alpes regions (i.e. the modern
Bourgogne-Franche-Comte + Auvergne-Rhone-Alpes footprint the spec asks for — Geofabrik
still ships France as pre-2016 regions, so there is no single "Bourgogne-Franche-Comte"
or "Auvergne-Rhone-Alpes" extract to download directly).

## Profile

`car_toll.lua` is a fork of upstream `profiles/car.lua` (osrm-backend v26.8.0), kept as a
named file for future customisation. **Finding:** no functional edits were needed — the
upstream profile already declares `toll` in `classes` and `excludable`, and
`lib/way_handlers.lua`'s `handle_classification` already sets `forward_classes.toll` /
`backward_classes.toll` from `toll=yes` way tags. `lib/` alongside this profile is a copy
of the image's `/opt/lib`, required because a mounted profile outside `/opt` cannot resolve
`require('lib/set')` etc. against the image's internal path.

## Build pipeline

**Important — docker-outside-of-docker path translation.** This devcontainer shares the
host's Docker daemon, so bind-mount sources in `docker run -v` / `docker compose` are
resolved against the **host** filesystem, not this container's `/workspace`. Find the host
path once with:

```sh
docker inspect <this-devcontainer-id> --format '{{json .Mounts}}' | python3 -m json.tool | grep -B4 '"Destination": "/workspace"'
```

At the time of writing this resolved to `/home/hugh/build/toll-1-exploration`, so the osrm
directory's host path is `/home/hugh/build/toll-1-exploration/osrm`. Set:

```sh
export OSRM_HOST_DIR=/home/hugh/build/toll-1-exploration/osrm   # adjust per environment
```

1. Download the four Geofabrik regional extracts and merge into one PBF (already done in
   `data/bfc-ara.osm.pbf`; `osmium-tool` — `sudo apt-get install osmium-tool` — was used):
   ```sh
   cd osrm/data
   for r in bourgogne franche-comte auvergne rhone-alpes; do
     curl -sSL -o "$r.osm.pbf" "https://download.geofabrik.de/europe/france/$r-latest.osm.pbf"
   done
   osmium merge bourgogne.osm.pbf franche-comte.osm.pbf auvergne.osm.pbf rhone-alpes.osm.pbf \
     -o bfc-ara.osm.pbf --overwrite
   ```
2. MLD build (extract -> partition -> customize), all against `${OSRM_HOST_DIR}`:
   ```sh
   docker run --rm -v "${OSRM_HOST_DIR}:/data" ghcr.io/project-osrm/osrm-backend:latest \
     osrm-extract -p /data/car_toll.lua /data/data/bfc-ara.osm.pbf
   docker run --rm -v "${OSRM_HOST_DIR}:/data" ghcr.io/project-osrm/osrm-backend:latest \
     osrm-partition /data/data/bfc-ara.osrm
   docker run --rm -v "${OSRM_HOST_DIR}:/data" ghcr.io/project-osrm/osrm-backend:latest \
     osrm-customize /data/data/bfc-ara.osrm
   ```
3. Serve:
   ```sh
   OSRM_DATA_DIR="${OSRM_HOST_DIR}/data" docker compose up -d
   ```
4. Smoke test:
   ```sh
   ./smoke_test.sh
   ```

`data/` (raw and built OSRM files, ~1-2 GB) is gitignored — not committed.
