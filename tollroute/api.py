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
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import asynccontextmanager
from functools import lru_cache

import httpx
from fastapi import FastAPI, HTTPException

from tollroute import cost
from tollroute import graph as graph_mod
from tollroute import osrm_client as osrm_client_mod
from tollroute import response as response_mod
from tollroute import routing
from tollroute.etl.build_national import DEFAULT_NATIONAL_DB_PATH as DEFAULT_DB_PATH
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL

ROUTE_CACHE_MAXSIZE = 512
GEOMETRY_TTL_S = 60.0


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    app.state.cached_shape.cache_clear()


app = FastAPI(lifespan=lifespan)


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
        access_anchors=dict(g.access_anchors),
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


def _prune_geometry_cache(cache: dict[str, tuple[float, list[tuple[float, float]]]]) -> None:
    now = time.time()
    for rid in [rid for rid, (expiry, _wp) in cache.items() if expiry <= now]:
        del cache[rid]


@app.get("/route")
def get_route(
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    vehicle_class: int = 1,
    vot_eur_per_hour: float | None = None,
):
    if vehicle_class not in app.state.class_config:
        raise HTTPException(status_code=400, detail="vehicle_class must be 1-5")

    origin = (origin_lat, origin_lon)
    destination = (destination_lat, destination_lon)

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
        gates = option["gates"]
        waypoints = [origin, *(app.state.graph.gate_coords[g] for g in gates), destination]
        route_id = _route_id(origin, destination, gates)
        app.state.geometry_cache[route_id] = (expiry, waypoints)
        option["route_id"] = route_id

    return {
        "origin": {"lat": origin_lat, "lon": origin_lon},
        "destination": {"lat": destination_lat, "lon": destination_lon},
        **{k: v for k, v in result.items() if k != "options"},
        "options": options,
    }


@app.get("/geometry/{route_id}")
def get_geometry(route_id: str):
    _prune_geometry_cache(app.state.geometry_cache)
    entry = app.state.geometry_cache.get(route_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown or expired route_id")
    _expiry, waypoints = entry

    try:
        geometry = osrm_client_mod.route_geometry(app.state.osrm_client, waypoints)
    except osrm_client_mod.OSRMUnavailableError:
        return {"osrm_unavailable": True}

    return geometry
