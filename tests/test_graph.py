import httpx
import pytest

from tollroute import graph as graph_mod
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
    import sqlite3
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
