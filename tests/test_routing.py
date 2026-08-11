import sqlite3
import tempfile
from pathlib import Path

import httpx
import pytest

from tollroute import graph as graph_mod
from tollroute import routing
from tollroute.cli import GAZETTEER
from tollroute.etl import load, snap_report


def _osrm_reachable() -> bool:
    try:
        httpx.get(f"{snap_report.DEFAULT_OSRM_BASE_URL}/nearest/v1/car/5.0,47.0", timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live OSRM instance not reachable on DEFAULT_OSRM_BASE_URL"
)


@pytest.fixture(scope="module")
def base_graph():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "tollroute.sqlite"
        load.run(
            db_path=db_path,
            od_pairs_path=load.DEFAULT_OD_PAIRS_PATH,
            gare_master_path=load.DEFAULT_GARE_MASTER_PATH,
        )
        conn = sqlite3.connect(db_path)
        try:
            with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
                snap_report.snap_all_gates(conn, client)
                g = graph_mod.build_graph(conn)
        finally:
            conn.close()
    return g


def _graph_copy(g: graph_mod.Graph) -> graph_mod.Graph:
    # add_access_edges mutates its graph argument (appends origin/destination
    # nodes and edges keyed on the fixed synthetic ids -1/-2), so each test
    # pair needs its own copy - reusing one graph across pairs would leak the
    # previous pair's access edges into the next Dijkstra run. Edge/Node are
    # frozen dataclasses, so shallow-copying the containers is enough; this
    # avoids repeating build_graph's expensive O(gates^2) OSRM /table calls.
    return graph_mod.Graph(
        nodes=list(g.nodes),
        node_index=dict(g.node_index),
        edges=list(g.edges),
        gate_coords=dict(g.gate_coords),
        static_edge_count=g.static_edge_count,
        static_edge_arrays=g.static_edge_arrays,
    )


@requires_osrm
def test_known_toll_edge_route_matches_od_pairs(base_graph):
    # Dijon Sud -> Villefranche Nord direct toll edge (named test pair 1),
    # queried node-to-node so no access-edge OSRM calls are needed.
    route = routing.find_route(
        base_graph,
        graph_mod.Node(269, graph_mod.NodeRole.OUT),
        graph_mod.Node(930, graph_mod.NodeRole.IN_TOLL),
        vehicle_class=1,
    )
    assert len(route.edges) == 1
    assert route.edges[0].edge_type == graph_mod.EdgeType.TOLL
    assert route.toll_eur == pytest.approx(14.1)
    assert route.duration_s > 0
    assert route.distance_m > 0


@requires_osrm
@pytest.mark.parametrize(
    "origin_city,dest_city",
    [
        ("dijon", "lyon"),
        ("paris", "lyon"),
        ("clermont-ferrand", "montpellier"),
        ("dijon", "macon"),
        ("beaune", "macon"),
    ],
)
def test_cli_route_for_named_pairs(base_graph, origin_city, dest_city):
    g = _graph_copy(base_graph)
    with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
        origin_node, dest_node = graph_mod.add_access_edges(
            g, client, GAZETTEER[origin_city], GAZETTEER[dest_city]
        )
        route = routing.find_route(g, origin_node, dest_node, vehicle_class=1)

    assert route.duration_s > 0
    assert route.distance_m > 0
    assert route.toll_eur >= 0

    # Structural invariant (Phase 1c "Core architectural decision"): no
    # TOLL -> DWELL -> TOLL in the returned edge sequence, i.e. the dwell
    # edge never chains two toll edges together.
    for i in range(len(route.edges) - 2):
        types = (
            route.edges[i].edge_type,
            route.edges[i + 1].edge_type,
            route.edges[i + 2].edge_type,
        )
        assert types != (
            graph_mod.EdgeType.TOLL,
            graph_mod.EdgeType.DWELL,
            graph_mod.EdgeType.TOLL,
        )
