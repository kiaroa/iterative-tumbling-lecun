"""Minimal FastAPI wrapper over the routing core (Phase 1d).

Exposes one `/route` endpoint returning the same option set as `tollroute.cli`.
Response labelling/guard rails are Phase 4b's job; a lazy geometry endpoint is
Phase 4c's - out of scope here.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

from tollroute import graph as graph_mod
from tollroute import routing
from tollroute.cli import GAZETTEER
from tollroute.etl.load import DEFAULT_DB_PATH
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        with httpx.Client(base_url=DEFAULT_OSRM_BASE_URL, timeout=30.0) as build_client:
            app.state.graph = graph_mod.build_graph(conn, build_client)
    finally:
        conn.close()
    app.state.osrm_client = httpx.Client(base_url=DEFAULT_OSRM_BASE_URL, timeout=30.0)
    yield
    app.state.osrm_client.close()


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
def get_route(origin: str, destination: str, vehicle_class: int = 1):
    key_o, key_d = origin.strip().lower(), destination.strip().lower()
    if key_o not in GAZETTEER or key_d not in GAZETTEER:
        raise HTTPException(status_code=400, detail=f"unknown city; known cities: {', '.join(sorted(GAZETTEER))}")
    if vehicle_class not in (1, 2, 3, 4, 5):
        raise HTTPException(status_code=400, detail="vehicle_class must be 1-5")

    g = _graph_copy(app.state.graph)
    origin_node, dest_node = graph_mod.add_access_edges(
        g, app.state.osrm_client, GAZETTEER[key_o], GAZETTEER[key_d]
    )
    try:
        r = routing.find_route(g, origin_node, dest_node, vehicle_class)
    except routing.RouteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    gate_chain: list[int] = []
    for node in r.nodes:
        if node.gare_id < 0:
            continue  # synthetic origin/destination node
        if not gate_chain or gate_chain[-1] != node.gare_id:
            gate_chain.append(node.gare_id)

    return {
        "origin": origin,
        "destination": destination,
        "vehicle_class": vehicle_class,
        "toll_eur": r.toll_eur,
        "duration_s": r.duration_s,
        "distance_m": r.distance_m,
        "gates": gate_chain,
    }
