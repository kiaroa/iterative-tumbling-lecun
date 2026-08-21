import sqlite3

import httpx
import pytest

from tollroute import graph as graph_mod
from tollroute import routing
from tollroute.etl import coverage_audit, freeflow, load, snap_report
from tollroute.routing_engine import DEFAULT_FULL_URL, RoutingEngine


def _osrm_reachable() -> bool:
    try:
        httpx.get(f"{DEFAULT_FULL_URL}/status", timeout=2.0)
        return True
    except Exception:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live Valhalla instance not reachable on DEFAULT_FULL_URL"
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
            engine = RoutingEngine()
            try:
                snap_report.snap_all_gates(conn, engine)
                g = graph_mod.build_graph(conn)
            finally:
                engine.close()
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


@pytest.fixture(scope="module")
def national_built_graph():
    """Phase 2c transfer-edge wiring is vacuous on an APRR-only graph (no
    other operator's gates are loaded to connect to), so these tests build
    off the national (all-operator) load instead - unremediated
    (`coverage_audit.build_full_db`, not `build_national.run`) is enough
    here since the transfer-edge mechanism only needs gates/operators/fares
    loaded and snapped, not Phase 2b's disposition/rematch remediation.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "tollroute_full.sqlite"
        conn, _ = coverage_audit.build_full_db(db_path=db_path)
        try:
            engine = RoutingEngine()
            try:
                snap_report.snap_all_gates(conn, engine)
            finally:
                engine.close()
            g = graph_mod.build_graph(conn)
        finally:
            conn.close()
    return g


@requires_osrm
def test_ablis_boundary_edge_wired_both_directions(national_built_graph):
    g = national_built_graph

    # ABLIS: gare_id 4 (ASFC) and 5 (Cofiroute), 0 m apart, disjoint
    # operators - the spec's one manually-verified boundary anchor
    # (reports/phase2c_clustering.md). Free, zero-time, and must connect
    # both OUT and OUT_TOLL (a toll arrival can cross straight over) to the
    # other gate's OUT (ready to start a new toll edge with no extra dwell).
    for a, b in ((4, 5), (5, 4)):
        for src_role in (graph_mod.NodeRole.OUT, graph_mod.NodeRole.OUT_TOLL):
            matches = [
                e
                for e in g.edges
                if e.edge_type == graph_mod.EdgeType.BOUNDARY
                and e.from_node == graph_mod.Node(a, src_role)
                and e.to_node == graph_mod.Node(b, graph_mod.NodeRole.OUT)
            ]
            assert len(matches) == 1, f"missing boundary edge {a}({src_role}) -> {b}(OUT)"
            assert matches[0].duration_s == 0.0
            assert matches[0].distance_m == 0.0


@requires_osrm
def test_exit_reentry_edge_carries_dwell_and_lands_on_in(national_built_graph):
    g = national_built_graph

    # ANCENIS (40) <-> ANGERS (43): 0 m apart, both Cofiroute - same
    # concession, so a 3 min / 0.5 km exit/re-entry dwell, landing on IN
    # (not OUT) so a further per-gate dwell is required before any new toll
    # edge - excluded as a toll-edge connector, per the Core architectural
    # decision.
    for a, b in ((40, 43), (43, 40)):
        for src_role in (graph_mod.NodeRole.OUT, graph_mod.NodeRole.OUT_TOLL):
            matches = [
                e
                for e in g.edges
                if e.edge_type == graph_mod.EdgeType.EXIT_REENTRY
                and e.from_node == graph_mod.Node(a, src_role)
                and e.to_node == graph_mod.Node(b, graph_mod.NodeRole.IN)
            ]
            assert len(matches) == 1, f"missing exit_reentry edge {a}({src_role}) -> {b}(IN)"
            assert matches[0].duration_s == pytest.approx(180.0)
            assert matches[0].distance_m == pytest.approx(500.0)


@requires_osrm
def test_transfer_edges_never_invert_the_out_in_landing_rule(national_built_graph):
    g = national_built_graph

    # Structural invariant mirroring test_dwell_edge_cannot_chain_two_toll_
    # edges above: a BOUNDARY edge is the only permitted connector between
    # two different-operator toll edges, which only holds if it always
    # lands on OUT (never IN); EXIT_REENTRY must never take the OUT-landing
    # shortcut either, or the same-operator no-chaining rule would leak.
    boundary_edges = [e for e in g.edges if e.edge_type == graph_mod.EdgeType.BOUNDARY]
    exit_reentry_edges = [e for e in g.edges if e.edge_type == graph_mod.EdgeType.EXIT_REENTRY]
    assert boundary_edges and exit_reentry_edges
    assert all(e.to_node.role == graph_mod.NodeRole.OUT for e in boundary_edges)
    assert all(e.to_node.role == graph_mod.NodeRole.IN for e in exit_reentry_edges)


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


def test_a14_selfloop_becomes_priced_freeflow_edge_not_dropped():
    """Phase 2c follow-up: a self-loop fare row (from_gare_id == to_gare_id,
    A14's single-gantry flat-fee pattern) must become a priced TOLL edge
    reachable via the normal IN -> dwell -> OUT -> toll -> IN_TOLL -> dwell
    -> OUT_TOLL chain, not a zero-length no-op or a silently dropped row.
    Synthetic single-gate DB, so this runs without a live OSRM instance
    (unlike the rest of this module) - build_graph itself no longer calls
    OSRM at all (Phase 4b-follow-up: gate-to-gate legs come from the
    precomputed matrix), so no mocking is needed here either.
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

    g = graph_mod.build_graph(conn)

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


def test_millau_seed_becomes_priced_selfloop_edge_via_existing_a14_mechanism():
    """Phase 5b-follow-up-2 (revised): `freeflow.seed_millau_override` inserts one
    real self-loop gate/fares row (same shape A14's 5 dataset self-loop rows already
    use - see `test_a14_selfloop_becomes_priced_freeflow_edge_not_dropped` above),
    so `build_graph`'s existing self-loop handling wires it up correctly with no
    new graph.py code at all. This is the design this item settled on after an
    initial two-synthetic-gate "fork" attempt was found, on direct empirical
    verification, to never actually charge the fee (see reports/
    phase5b_followup2_millau.md and `tollroute/etl/freeflow.py`'s module comment
    for the full investigation).
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(load.SCHEMA_PATH.read_text())
    conn.commit()
    freeflow.seed_millau_override(conn)

    g = graph_mod.build_graph(conn)
    conn.close()

    selfloop_edges = [
        e
        for e in g.edges
        if e.edge_type == graph_mod.EdgeType.TOLL
        and e.from_node == graph_mod.Node(freeflow.MILLAU_GARE_ID, graph_mod.NodeRole.OUT)
        and e.to_node == graph_mod.Node(freeflow.MILLAU_GARE_ID, graph_mod.NodeRole.IN_TOLL)
    ]
    assert len(selfloop_edges) == 1
    edge = selfloop_edges[0]
    assert edge.operator == "CEVM"
    assert edge.distance_m == 0.0
    assert edge.duration_s == 0.0
    assert edge.toll_eur[1] == pytest.approx(11.30)
    assert edge.toll_eur[2] > 0  # interpolated class present too

    route = routing.find_route(
        g,
        graph_mod.Node(freeflow.MILLAU_GARE_ID, graph_mod.NodeRole.IN),
        graph_mod.Node(freeflow.MILLAU_GARE_ID, graph_mod.NodeRole.OUT_TOLL),
        vehicle_class=1,
    )
    assert [e.edge_type for e in route.edges] == [
        graph_mod.EdgeType.DWELL,
        graph_mod.EdgeType.TOLL,
        graph_mod.EdgeType.DWELL,
    ]
    assert route.toll_eur == pytest.approx(11.30)
