"""FastAPI wrapper over the routing core (Phase 1d) with Pareto response
shaping, guard rails and a cache (Phase 4b).

Exposes one `/route` endpoint returning the `tollroute.response.shape_response`
option set (fastest/cheapest/best_value plus surviving Pareto points). A lazy
geometry endpoint is Phase 4c's - out of scope here.

**Cache key deviation, flagged (see `tollroute/response.py`'s docstring for
the full reasoning):** the spec's Phase 4b cache key is
`(snapped_entry_gate_id, snapped_exit_gate_id, class, VoT_bucket)`, which
presumes a per-request nearest-gate resolution step that decouples
entry/exit-gate choice from the graph search - that is Phase 4c's job.
Today, `add_access_edges` connects the origin/destination to *every*
candidate gate and lets Dijkstra pick the best one, so no single entry/exit
gate id is known before the search runs. The cache below therefore keys on
`(origin_key, destination_key, vehicle_class, vot_bucket)` - the resolved
gazetteer city pair - which is the correctly-scoped stand-in for "the same
query" in the current architecture and dedupes exact repeat requests exactly
as the cache is meant to. Once Phase 4c adds real lat/lon input with a
separate nearest-gate resolution step, this key can be tightened to literal
gate ids.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from functools import lru_cache

import httpx
from fastapi import FastAPI, HTTPException

from tollroute import cost
from tollroute import graph as graph_mod
from tollroute import response as response_mod
from tollroute import routing
from tollroute.cli import GAZETTEER
from tollroute.etl.load import DEFAULT_DB_PATH
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL

ROUTE_CACHE_MAXSIZE = 512


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        with httpx.Client(base_url=DEFAULT_OSRM_BASE_URL, timeout=30.0) as build_client:
            app.state.graph = graph_mod.build_graph(conn, build_client)
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

    @lru_cache(maxsize=ROUTE_CACHE_MAXSIZE)
    def cached_shape(origin_key: str, destination_key: str, vehicle_class: int, vot_bucket: float) -> dict:
        g = _graph_copy(app.state.graph)
        origin_node, dest_node = graph_mod.add_access_edges(
            g, app.state.osrm_client, GAZETTEER[origin_key], GAZETTEER[destination_key]
        )
        gate_conn = sqlite3.connect(DEFAULT_DB_PATH)
        try:
            return response_mod.shape_response(
                g, origin_node, dest_node, vehicle_class, app.state.class_config,
                gate_conn, vot_threshold=vot_bucket,
            )
        finally:
            gate_conn.close()

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
    return graph_mod.Graph(
        nodes=list(g.nodes),
        node_index=dict(g.node_index),
        edges=list(g.edges),
        gate_coords=dict(g.gate_coords),
    )


@app.get("/route")
def get_route(
    origin: str,
    destination: str,
    vehicle_class: int = 1,
    vot_eur_per_hour: float | None = None,
):
    key_o, key_d = origin.strip().lower(), destination.strip().lower()
    if key_o not in GAZETTEER or key_d not in GAZETTEER:
        raise HTTPException(status_code=400, detail=f"unknown city; known cities: {', '.join(sorted(GAZETTEER))}")
    if vehicle_class not in app.state.class_config:
        raise HTTPException(status_code=400, detail="vehicle_class must be 1-5")

    # VoT bucket: round to the nearest whole EUR/h so near-identical
    # per-request overrides still hit the cache (judgement call - see
    # module docstring for the cache key's full reasoning).
    default_vot = app.state.class_config[vehicle_class].value_of_time_eur_per_hour
    vot_bucket = round(vot_eur_per_hour if vot_eur_per_hour is not None else default_vot)

    try:
        result = app.state.cached_shape(key_o, key_d, vehicle_class, float(vot_bucket))
    except routing.RouteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"origin": origin, "destination": destination, **result}
