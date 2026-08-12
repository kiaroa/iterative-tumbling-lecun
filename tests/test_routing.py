import sqlite3
import tempfile
from pathlib import Path

import httpx
import pytest

from tollroute import graph as graph_mod
from tollroute import osrm_client as osrm_client_mod
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
        access_anchors_entry=dict(g.access_anchors_entry),
        access_anchors_exit=dict(g.access_anchors_exit),
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


def test_add_access_edges_queries_anchor_coord_and_adds_apron(monkeypatch):
    """Phase 5b-follow-up-1: a gate with a `graph.access_anchors_entry`/
    `access_anchors_exit` entry must be queried (via the batched OSRM /table
    calls) at its anchor coordinate, not its own - the gate's own coordinate
    is the physical barrier on tolled tarmac, which can be an unreachable
    pocket in the `exclude=toll` graph (`tollroute.etl.access_anchors`) -
    with the anchor's apron duration/distance added back onto whatever leg
    OSRM returns for anchor<->gate.

    Phase 5b-follow-up-1-continued: entry and exit anchors are deliberately
    given *different* coordinates here (unlike a single shared anchor) to
    pin that `add_access_edges` looks each one up independently - reachability
    on a divided/oneway motorway is directional, and reusing one direction's
    anchor for the other was found to silently break most of the anchors
    Phase 5b-follow-up-1 originally shipped.

    Self-contained (no live OSRM): the batched-table calls are monkeypatched
    so this only exercises `add_access_edges`'s own coordinate-selection and
    apron-arithmetic logic.
    """
    entry_anchor_lat, entry_anchor_lon = 48.001, 2.001
    entry_apron_distance_m, entry_apron_duration_s = 300.0, 25.0
    exit_anchor_lat, exit_anchor_lon = 48.002, 2.002
    exit_apron_distance_m, exit_apron_duration_s = 450.0, 40.0
    g = graph_mod.Graph(
        gate_coords={1: (48.000, 2.000), 2: (49.0, 3.0)},
        access_anchors_entry={
            1: (entry_anchor_lat, entry_anchor_lon, entry_apron_distance_m, entry_apron_duration_s)
        },
        access_anchors_exit={
            1: (exit_anchor_lat, exit_anchor_lon, exit_apron_distance_m, exit_apron_duration_s)
        },
    )
    for gid in (1, 2):
        g.add_node(graph_mod.Node(gid, graph_mod.NodeRole.IN))
        g.add_node(graph_mod.Node(gid, graph_mod.NodeRole.OUT))
        g.add_node(graph_mod.Node(gid, graph_mod.NodeRole.OUT_TOLL))

    captured_entry_coords: list[tuple[float, float]] = []
    captured_exit_coords: list[tuple[float, float]] = []

    def fake_one_to_many_table(client, origin, destinations, exclude_toll):
        captured_entry_coords.extend(destinations)
        return [(1000.0, 5000.0) for _ in destinations]

    def fake_many_to_one_table(client, origins, destination, exclude_toll):
        captured_exit_coords.extend(origins)
        return [(2000.0, 8000.0) for _ in origins]

    monkeypatch.setattr(osrm_client_mod, "one_to_many_table", fake_one_to_many_table)
    monkeypatch.setattr(osrm_client_mod, "many_to_one_table", fake_many_to_one_table)

    origin_node, destination_node = graph_mod.add_access_edges(
        g, None, origin=(0.0, 0.0), destination=(9.0, 9.0)
    )

    # The anchored gate (1) is queried at its own direction's anchor coordinate
    # (entry != exit here), not its raw `gate_coords` entry; the unanchored
    # gate (2) is queried unchanged.
    assert captured_entry_coords == [(entry_anchor_lat, entry_anchor_lon), (49.0, 3.0)]
    assert captured_exit_coords == [(exit_anchor_lat, exit_anchor_lon), (49.0, 3.0)]

    entry_edge = next(
        e for e in g.edges if e.from_node == origin_node and e.to_node == graph_mod.Node(1, graph_mod.NodeRole.IN)
    )
    assert entry_edge.duration_s == pytest.approx(1000.0 + entry_apron_duration_s)
    assert entry_edge.distance_m == pytest.approx(5000.0 + entry_apron_distance_m)

    unanchored_entry_edge = next(
        e for e in g.edges if e.from_node == origin_node and e.to_node == graph_mod.Node(2, graph_mod.NodeRole.IN)
    )
    assert unanchored_entry_edge.duration_s == pytest.approx(1000.0)
    assert unanchored_entry_edge.distance_m == pytest.approx(5000.0)

    exit_edge = next(
        e for e in g.edges if e.to_node == destination_node and e.from_node == graph_mod.Node(1, graph_mod.NodeRole.OUT)
    )
    assert exit_edge.duration_s == pytest.approx(2000.0 + exit_apron_duration_s)
    assert exit_edge.distance_m == pytest.approx(8000.0 + exit_apron_distance_m)
