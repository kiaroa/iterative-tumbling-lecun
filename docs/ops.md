# Operations (Phase 6a)

## Structured logging

Every `/route` response is logged as one JSON record (`tollroute/logging.py`,
attached to the root logger by `tollroute.api`'s startup `lifespan`) carrying
the full gate chain for every option returned, not just the one selected -
"why this route" debugging usually means "why not that one". Example (one
line, pretty-printed here):

```json
{
  "level": "INFO",
  "logger": "tollroute.route",
  "message": "route computed",
  "origin": {"lat": 47.322, "lon": 5.041},
  "destination": {"lat": 45.764, "lon": 4.836},
  "vehicle_class": 1,
  "vot_eur_per_hour": 20.0,
  "options": [
    {"route_id": "a1b2c3d4e5f6a7b8", "labels": ["fastest"], "gates": [123, 456],
     "toll_eur": 8.4, "duration_s": 5312.0, "distance_m": 198000.0},
    {"route_id": "9f8e7d6c5b4a3210", "labels": ["cheapest"], "gates": [789],
     "toll_eur": 0.0, "duration_s": 6100.0, "distance_m": 210000.0}
  ]
}
```

## `/health`

```
GET /health
```

Returns `200` with `{"osrm_reachable": true, "matrix_loaded": true, "gate_count": <n>}`
when OSRM answers a `/nearest` probe and the startup graph loaded at least
one gate/edge; `503` with the same body (fields reflecting whichever check
failed) otherwise. Deliberately does **not** check data freshness (staleness
of the underlying fare/matrix data) - that is an external process's
responsibility per spec, not this endpoint's.

## One-command pipeline rebuild

```sh
./scripts/rebuild.sh
```

Runs the full OSM -> OSRM -> matrices/DB pipeline end to end from a fresh
checkout:

1. `osrm/build_france.sh` - downloads the Geofabrik France PBF (skipped if
   already present and size-matches) and runs `osrm-extract` / `osrm-partition`
   / `osrm-customize` with `osrm/car_toll.lua`.
2. Serves the built extract via `docker compose up -d` (`OSRM_NETWORK=france`),
   auto-detecting the host bind-mount path the same way `build_france.sh`
   does (docker-outside-of-docker - see `osrm/README.md`), then polls
   `/nearest` until OSRM answers.
3. `python3 -m tollroute.matrices` - precomputes the four national
   duration/distance `.npy` matrices (`data/matrices/`).
4. `python3 -m tollroute.etl.build_national` - rebuilds the graph-ready
   national SQLite DB (remediation, quarantines, snapping, class-config
   seed).
5. `python3 -m tollroute.etl.access_anchors` - precomputes toll-free access
   anchors against the now-built DB's gates table.

Steps 3 and 4 both only need a reachable OSRM and are independent of each
other; step 5 needs the DB step 4 produces, so it always runs last.

Override `OSRM_HOST_DIR` if auto-detection fails (see `osrm/README.md`) and
`OSRM_BASE_URL` if OSRM is served somewhere other than `http://localhost:5000`.

Start the API itself (loads the DB and matrices `rebuild.sh` produced) with:

```sh
uvicorn tollroute.api:app
```

## Free-text geocoding (Phase 6b)

`/route` accepts either coordinates or a free-text address per endpoint -
`origin_lat`/`origin_lon` (and the `destination_*` equivalents) or
`origin_address`/`destination_address`, not both. A free-text address is
resolved to lat/lon via the French government's Base Adresse Nationale (BAN)
search API (`api-adresse.data.gouv.fr`, no key required) before anything
else runs, so the routing core itself is unchanged - `tollroute/geocode.py`
owns the resolution step. A `422` means the address could not be resolved
(unreachable geocoder after one retry, or no match); a `400` means the
request mixed both input forms, or gave neither, for one endpoint.

```sh
curl "http://localhost:8000/route?origin_address=Dijon&destination_address=Lyon&vehicle_class=1"
```

returns the same result as the equivalent `origin_lat`/`origin_lon`/
`destination_lat`/`destination_lon` call.
