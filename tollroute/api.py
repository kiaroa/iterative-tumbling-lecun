"""FastAPI wrapper over the routing core (Phase 1d) with Pareto response
shaping, guard rails and a cache (Phase 4b), now serving real per-request
lat/lon input with OSRM failure handling and lazy route geometry (Phase 4c).

Exposes `/route` (returns the `tollroute.response.shape_response` option set:
fastest/cheapest/best_value plus surviving Pareto points, each carrying a
`route_id`) and `/geometry/{route_id}` (fetches that option's real polyline
from OSRM on demand - the main response never blocks on it).

**Input change, flagged:** Phase 4b/4b-follow-up took city names resolved
against `tollroute.cli.GAZETTEER`; the spec's Phase 4c deliverable is
explicit ("Input: lat/lon coordinates"), and Phase 6b's free-text geocoding
wrapper is specced as a *later*, optional layer on top of an "unchanged
routing core" that already takes coordinates - so this phase moves `/route`
to `origin_lat`/`origin_lon`/`destination_lat`/`destination_lon` query
params. `tollroute.cli` keeps its own city-name gazetteer for the CLI, which
calls `tollroute.graph`/`tollroute.routing` directly and never goes through
this module.

**Cache key deviation, flagged (see `tollroute/response.py`'s docstring for
the fuller reasoning):** the spec's Phase 4b cache key is
`(snapped_entry_gate_id, snapped_exit_gate_id, class, VoT_bucket)`, which
presumes a per-request nearest-gate resolution step that decouples
entry/exit-gate choice from the graph search. Today, `add_access_edges`
connects the origin/destination to *every* candidate gate and lets Dijkstra
pick the best one, so no single entry/exit gate id is known before the
search runs. The cache below keys on the exact origin/destination
coordinates instead - an exact-match concept like the spec's own gate-id
key, just on coordinates rather than resolved gate ids, so it dedupes real
repeat requests without silently snapping a genuinely different nearby
address onto a cached answer (rounding the *query itself* to a coarser grid
would change the actual OSRM legs computed, not just what counts as a cache
hit).

**Baseline-route-as-canary, flagged:** the spec lists "one baseline `/route`"
alongside the two `/table` calls without saying what it is used for. It is
issued first, inside `cached_shape`, because it is the cheapest possible
OSRM call and so doubles as the OSRM-availability check (with its own single
retry - `tollroute.osrm_client.baseline_route`) before the two heavier
`/table` batches run; its duration/distance is also surfaced on the response
as `baseline` (a "direct route, tolls allowed, ignoring the toll-minimising
graph entirely" reference point a client can display for comparison).

**Observability and ops (Phase 6a):** every `/route` response is logged as
one structured record carrying every option's full gate chain
(`tollroute.logging.log_route_response`) - see that module for the JSON
formatter. `/health` asserts OSRM reachability and that the startup graph
actually loaded gates/edges (not data freshness, which is an external
process's job per spec); see `docs/ops.md` for the one-command rebuild.

**Free-text geocoding (Phase 6b):** `/route` accepts an optional
`origin_address`/`destination_address` per endpoint as an alternative to
`{origin,destination}_{lat,lon}` - resolved via `tollroute.geocode` (the
BAN API) to lat/lon *before* anything else runs, so the routing core itself
never sees or needs to change. `match_tier`/`match_agreement` were already
present on every gate in every response before this phase (Phase 4b); this
just confirms that stays true regardless of which input form was used.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import asynccontextmanager
from functools import lru_cache

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tollroute import cost
from tollroute import geocode as geocode_mod
from tollroute import graph as graph_mod
from tollroute import logging as logging_mod
from tollroute import osrm_client as osrm_client_mod
from tollroute import response as response_mod
from tollroute import routing
from tollroute.etl.build_national import DEFAULT_NATIONAL_DB_PATH as DEFAULT_DB_PATH
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL

ROUTE_CACHE_MAXSIZE = 512
GEOMETRY_TTL_S = 60.0
HEALTH_CHECK_TIMEOUT_S = 2.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_mod.configure_logging()
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        app.state.graph = graph_mod.build_graph(conn)
        # Idempotent (only inserts when class_config is empty - see
        # tollroute/cost.py): dev DBs built before Phase 4a's loader change
        # never got seeded, and re-running the full loader here would wipe
        # the gates table's OSRM snap columns build_graph just depended on.
        cost.seed_class_config(conn)
        conn.commit()
        app.state.class_config = cost.load_class_config(conn)
    finally:
        conn.close()
    app.state.osrm_client = httpx.Client(base_url=DEFAULT_OSRM_BASE_URL, timeout=30.0)
    app.state.geocode_client = httpx.Client(base_url=geocode_mod.DEFAULT_GEOCODE_BASE_URL, timeout=30.0)
    app.state.geometry_cache: dict[str, tuple[float, list[tuple[float, float]]]] = {}

    @lru_cache(maxsize=ROUTE_CACHE_MAXSIZE)
    def cached_shape(
        origin_key: tuple[float, float], destination_key: tuple[float, float],
        vehicle_class: int, vot_bucket: float,
    ) -> dict:
        # Canary first (see module docstring): cheapest possible OSRM call,
        # so an unavailable OSRM is caught - with its own single retry -
        # before the two heavier /table batches below ever run.
        baseline = osrm_client_mod.baseline_route(app.state.osrm_client, origin_key, destination_key)

        g = _graph_copy(app.state.graph)
        origin_node, dest_node = graph_mod.add_access_edges(
            g, app.state.osrm_client, origin_key, destination_key
        )
        gate_conn = sqlite3.connect(DEFAULT_DB_PATH)
        try:
            shaped = response_mod.shape_response(
                g, origin_node, dest_node, vehicle_class, app.state.class_config,
                gate_conn, vot_threshold=vot_bucket,
            )
        finally:
            gate_conn.close()
        shaped["baseline"] = (
            {"duration_s": baseline["duration"], "distance_m": baseline["distance"]}
            if baseline is not None
            else None
        )
        return shaped

    app.state.cached_shape = cached_shape
    yield
    app.state.osrm_client.close()
    app.state.geocode_client.close()
    app.state.cached_shape.cache_clear()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _graph_copy(g: graph_mod.Graph) -> graph_mod.Graph:
    # add_access_edges mutates its graph argument in place (flagged as a
    # reuse hazard for this endpoint in Phase 1c's PROGRESS entry): each
    # request needs its own copy of the long-lived startup graph so one
    # request's origin/destination access edges can't leak into the next.
    # static_edge_count/static_edge_arrays are carried over by reference
    # (Phase 4c-follow-up-3): they're read-only per request and shared
    # unchanged across every copy of the startup graph, so build_edge_arrays
    # can still take its cached-static-prefix fast path.
    return graph_mod.Graph(
        nodes=list(g.nodes),
        node_index=dict(g.node_index),
        edges=list(g.edges),
        gate_coords=dict(g.gate_coords),
        access_anchors_entry=dict(g.access_anchors_entry),
        access_anchors_exit=dict(g.access_anchors_exit),
        freeflow_selfloop_gate_ids=set(g.freeflow_selfloop_gate_ids),
        static_edge_count=g.static_edge_count,
        static_edge_arrays=g.static_edge_arrays,
    )


def _route_id(origin: tuple[float, float], destination: tuple[float, float], gates: list[int]) -> str:
    """Deterministic id fingerprinting the Dijkstra result (spec: "keyed on
    Dijkstra result") - identical origin/destination/gate-chain reuses the
    same geometry cache entry rather than minting a fresh one every call.
    """
    key = f"{origin[0]:.5f},{origin[1]:.5f}|{destination[0]:.5f},{destination[1]:.5f}|{','.join(map(str, gates))}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _prune_geometry_cache(cache: dict) -> None:
    now = time.time()
    for rid in [rid for rid, entry in cache.items() if entry[0] <= now]:
        del cache[rid]


def _resolve_point(
    lat: float | None, lon: float | None, address: str | None, label: str
) -> tuple[float, float]:
    """Resolve one `/route` endpoint from either `{label}_lat`/`{label}_lon`
    or a free-text `{label}_address` (Phase 6b) - exactly one of the two
    forms must be given; the routing core downstream never learns which was
    used, since it only ever sees the resulting (lat, lon)."""
    has_coords = lat is not None and lon is not None
    if (lat is None) != (lon is None):
        raise ValueError(f"{label}: provide both {label}_lat and {label}_lon, or neither")
    if has_coords and address:
        raise ValueError(f"{label}: provide either {label}_lat/{label}_lon or {label}_address, not both")
    if address:
        return geocode_mod.geocode(app.state.geocode_client, address)
    if has_coords:
        return (lat, lon)
    raise ValueError(f"{label}: provide {label}_lat/{label}_lon or {label}_address")


@app.get("/route")
def get_route(
    origin_lat: float | None = None,
    origin_lon: float | None = None,
    destination_lat: float | None = None,
    destination_lon: float | None = None,
    origin_address: str | None = None,
    destination_address: str | None = None,
    vehicle_class: int = 1,
    vot_eur_per_hour: float | None = None,
):
    if vehicle_class not in app.state.class_config:
        raise HTTPException(status_code=400, detail="vehicle_class must be 1-5")

    try:
        origin = _resolve_point(origin_lat, origin_lon, origin_address, "origin")
        destination = _resolve_point(destination_lat, destination_lon, destination_address, "destination")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except geocode_mod.GeocodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # VoT bucket: round to the nearest whole EUR/h so near-identical
    # per-request overrides still hit the cache (judgement call - see
    # module docstring for the cache key's full reasoning).
    default_vot = app.state.class_config[vehicle_class].value_of_time_eur_per_hour
    vot_bucket = round(vot_eur_per_hour if vot_eur_per_hour is not None else default_vot)

    try:
        result = app.state.cached_shape(origin, destination, vehicle_class, float(vot_bucket))
    except routing.RouteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except osrm_client_mod.OSRMUnavailableError:
        return {"osrm_unavailable": True}

    # Assign/refresh a route_id per option and register its waypoints in the
    # lazy geometry cache (Phase 4c) - happens on every /route call, cache
    # hit or miss, so a repeat request keeps its geometry fetchable rather
    # than silently expiring while cached_shape's own lru_cache keeps
    # serving the shaped response indefinitely.
    _prune_geometry_cache(app.state.geometry_cache)
    expiry = time.time() + GEOMETRY_TTL_S
    options = [dict(o) for o in result["options"]]
    for option in options:
        # Use only TOLL-edge gate endpoints as geometry waypoints (Bug 1 fix):
        # gates visited only via TOLL_FREE edges lie on N-roads, not motorway
        # toll booths — using their coordinates as OSRM waypoints routes the
        # motorway between them and displays unpriced toll sections on the map.
        # When priced_gates is empty (genuinely toll-free route), waypoints
        # collapse to [origin, destination]: OSRM's single access leg correctly
        # flags any toll roads it encounters via access_leg_toll_roads.
        priced_gates = option.get("priced_gates") or []
        waypoints = [origin, *(app.state.graph.gate_coords[g] for g in priced_gates), destination]
        route_id = _route_id(origin, destination, priced_gates)
        # Recompute toll_leg_indices relative to priced_gates waypoints:
        # leg j+1 goes from priced_gates[j] to priced_gates[j+1], so the
        # leg that prices a toll section starting at from_gare_id is at
        # priced_gate_idx[from_gare_id] + 1.
        priced_gate_idx = {gid: i for i, gid in enumerate(priced_gates)}
        toll_leg_indices = set()
        for tg in option.get("toll_gates_detail", []):
            from_id = tg["from_gare_id"]
            if from_id in priced_gate_idx:
                toll_leg_indices.add(priced_gate_idx[from_id] + 1)
        app.state.geometry_cache[route_id] = (expiry, waypoints, toll_leg_indices)
        option["route_id"] = route_id

    logging_mod.log_route_response(origin, destination, vehicle_class, {**result, "options": options})

    return {
        "origin": {"lat": origin[0], "lon": origin[1]},
        "destination": {"lat": destination[0], "lon": destination[1]},
        **{k: v for k, v in result.items() if k != "options"},
        "options": options,
    }


def _osrm_reachable(client: httpx.Client) -> bool:
    """Cheap OSRM connectivity probe for `/health` (spec: "asserts OSRM
    reachability", not data freshness) - a `/nearest` lookup near a point
    inside the loaded France extract, accepting any HTTP response as proof
    of reachability regardless of its `code` field (a coordinate genuinely
    outside the graph would still answer, just with `NoSegment`)."""
    try:
        resp = client.get("/nearest/v1/car/2.3522,48.8566", timeout=HEALTH_CHECK_TIMEOUT_S)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


@app.get("/health")
def get_health():
    graph: graph_mod.Graph = app.state.graph
    matrix_loaded = len(graph.nodes) > 0 and len(graph.edges) > 0
    osrm_reachable = _osrm_reachable(app.state.osrm_client)
    body = {
        "osrm_reachable": osrm_reachable,
        "matrix_loaded": matrix_loaded,
        "gate_count": len(graph.gate_coords),
    }
    return JSONResponse(status_code=200 if (matrix_loaded and osrm_reachable) else 503, content=body)


@app.get("/favicon.ico")
def get_favicon():
    return JSONResponse(status_code=204)


@app.get("/geometry/{route_id}")
def get_geometry(route_id: str):
    _prune_geometry_cache(app.state.geometry_cache)
    entry = app.state.geometry_cache.get(route_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown or expired route_id")
    _expiry, waypoints, toll_leg_indices = entry

    try:
        geometry = osrm_client_mod.route_geometry(app.state.osrm_client, waypoints, toll_leg_indices)
    except osrm_client_mod.OSRMUnavailableError:
        return {"osrm_unavailable": True}

    return geometry
