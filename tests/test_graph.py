import sqlite3

import httpx
import pytest

from tollroute import graph as graph_mod
from tollroute import routing
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
def built_graph():
    import tempfile
    from pathlib import Path

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
                g = graph_mod.build_graph(conn, client)
        finally:
            conn.close()
    return g


@requires_osrm
def test_graph_builds_with_expected_node_and_edge_shape(built_graph):
    g = built_graph

    # 4 node roles per snapped gate.
    assert len(g.nodes) == 4 * len(g.gate_coords)
    assert len(g.nodes) == len(g.node_index)

    toll_edges = [e for e in g.edges if e.edge_type == graph_mod.EdgeType.TOLL]
    dwell_edges = [e for e in g.edges if e.edge_type == graph_mod.EdgeType.DWELL]
    tollfree_edges = [e for e in g.edges if e.edge_type == graph_mod.EdgeType.TOLL_FREE]

    assert len(toll_edges) > 0
    assert len(tollfree_edges) > 0
    assert len(dwell_edges) == 2 * len(g.gate_coords)

    # Every toll edge carries an operator label (APRR-only in Phase 1).
    assert all(e.operator == "APRR" for e in toll_edges)


@requires_osrm
def test_known_toll_edge_price_matches_od_pairs(built_graph):
    g = built_graph

    # Dijon Sud (269) -> Villefranche Nord (930): named test pair 1 from
    # Phase 1b, a genuine APRR od_pairs fare row.
    matches = [
        e
        for e in g.edges
        if e.edge_type == graph_mod.EdgeType.TOLL
        and e.from_node == graph_mod.Node(269, graph_mod.NodeRole.OUT)
        and e.to_node == graph_mod.Node(930, graph_mod.NodeRole.IN_TOLL)
    ]
    assert len(matches) == 1
    edge = matches[0]
    assert edge.operator == "APRR"
    assert edge.toll_eur[1] == pytest.approx(14.1)
    assert edge.distance_m > 0
    assert edge.duration_s > 0


@requires_osrm
def test_dwell_edge_cannot_chain_two_toll_edges(built_graph):
    g = built_graph

    # Structural invariant: a toll edge can only originate at an OUT node.
    # OUT_TOLL nodes (reached via the dwell edge that follows a toll
    # arrival) must never source a toll edge - that is what makes
    # toll -> dwell -> toll unrepresentable.
    toll_edge_sources = {e.from_node for e in g.edges if e.edge_type == graph_mod.EdgeType.TOLL}
    assert all(node.role != graph_mod.NodeRole.OUT_TOLL for node in toll_edge_sources)

    # Concretely walk the named test-pair toll edge: toll -> dwell -> check
    # the dwell's landing node has zero outgoing toll edges.
    toll_edge = next(
        e
        for e in g.edges
        if e.edge_type == graph_mod.EdgeType.TOLL
        and e.from_node == graph_mod.Node(269, graph_mod.NodeRole.OUT)
        and e.to_node == graph_mod.Node(930, graph_mod.NodeRole.IN_TOLL)
    )
    dwell_edge = next(
        e
        for e in g.edges
        if e.edge_type == graph_mod.EdgeType.DWELL and e.from_node == toll_edge.to_node
    )
    next_hop_toll_edges = [
        e for e in g.edges if e.edge_type == graph_mod.EdgeType.TOLL and e.from_node == dwell_edge.to_node
    ]
    assert next_hop_toll_edges == []

    # And the allowed counterpart: a genuine toll-free detour IS reachable
    # from that same post-toll dwell node.
    next_hop_tollfree_edges = [
        e
        for e in g.edges
        if e.edge_type == graph_mod.EdgeType.TOLL_FREE and e.from_node == dwell_edge.to_node
    ]
    assert len(next_hop_tollfree_edges) > 0


def _mock_osrm_table_client() -> httpx.Client:
    """A single-gate table always resolves to the trivial 1x1 zero matrix -
    good enough to exercise build_graph's self-loop path without a live
    OSRM instance (Phase 2c follow-up: A14 self-loop fare rows, e.g. gate
    547 "PEAGE DE MONTESSON", never reach a live regional extract since
    graph.py's own OSRM lookup is bypassed for self-loops - see below).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/table/v1/car/")
        return httpx.Response(200, json={"code": "Ok", "durations": [[0.0]], "distances": [[0.0]]})

    return httpx.Client(base_url="http://osrm.test", transport=httpx.MockTransport(handler))


def test_a14_selfloop_becomes_priced_freeflow_edge_not_dropped():
    """Phase 2c follow-up: a self-loop fare row (from_gare_id == to_gare_id,
    A14's single-gantry flat-fee pattern) must become a priced TOLL edge
    reachable via the normal IN -> dwell -> OUT -> toll -> IN_TOLL -> dwell
    -> OUT_TOLL chain, not a zero-length no-op or a silently dropped row.
    Synthetic single-gate DB + mocked OSRM client, so this runs without a
    live OSRM instance (unlike the rest of this module).
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(load.SCHEMA_PATH.read_text())
    conn.execute(
        "INSERT INTO gates (gare_id, canonical_name, snap_lat, snap_lon) "
        "VALUES (547, 'PEAGE DE MONTESSON', 48.913480, 2.160399)"
    )
    conn.execute(
        "INSERT INTO fares (from_gare_id, to_gare_id, operator, class1, class2, "
        "class3, class4, class5, distance_km) "
        "VALUES (547, 547, 'sapn', 6.6, 13.6, 24.1, 36.3, 3.4, NULL)"
    )
    conn.commit()

    with _mock_osrm_table_client() as client:
        g = graph_mod.build_graph(conn, client)

    selfloop_edges = [
        e
        for e in g.edges
        if e.edge_type == graph_mod.EdgeType.TOLL
        and e.from_node == graph_mod.Node(547, graph_mod.NodeRole.OUT)
        and e.to_node == graph_mod.Node(547, graph_mod.NodeRole.IN_TOLL)
    ]
    assert len(selfloop_edges) == 1
    edge = selfloop_edges[0]
    assert edge.operator == "sapn"
    assert edge.distance_m == 0.0
    assert edge.duration_s == 0.0
    assert edge.toll_eur[1] == pytest.approx(6.6)

    # Reachability: the fee must actually be collectable end-to-end, not
    # just present as a disconnected edge.
    route = routing.find_route(
        g,
        graph_mod.Node(547, graph_mod.NodeRole.IN),
        graph_mod.Node(547, graph_mod.NodeRole.OUT_TOLL),
        vehicle_class=1,
    )
    assert [e.edge_type for e in route.edges] == [
        graph_mod.EdgeType.DWELL,
        graph_mod.EdgeType.TOLL,
        graph_mod.EdgeType.DWELL,
    ]
    assert route.toll_eur == pytest.approx(6.6)
