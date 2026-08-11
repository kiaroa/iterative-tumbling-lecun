import sqlite3
import tempfile
from pathlib import Path

import httpx
import pytest

from tollroute import cost
from tollroute import graph as graph_mod
from tollroute import response
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
def base_graph_config_and_db():
    # Deliberately not a `with tempfile.TemporaryDirectory()` block: the
    # sqlite file must outlive fixture setup so individual tests can reopen
    # a connection for response.shape_response's gate_match_detail lookups.
    tmp = Path(tempfile.mkdtemp())
    db_path = tmp / "tollroute.sqlite"
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
        class_config = cost.load_class_config(conn)
    finally:
        conn.close()
    return g, class_config, db_path


def _graph_copy(g: graph_mod.Graph) -> graph_mod.Graph:
    return graph_mod.Graph(
        nodes=list(g.nodes),
        node_index=dict(g.node_index),
        edges=list(g.edges),
        gate_coords=dict(g.gate_coords),
    )


def _make_edge(edge_type, operator=None, duration_s=0.0, distance_m=0.0, toll=None):
    return graph_mod.Edge(
        from_node=graph_mod.Node(0, graph_mod.NodeRole.OUT),
        to_node=graph_mod.Node(1, graph_mod.NodeRole.IN_TOLL),
        edge_type=edge_type,
        duration_s=duration_s,
        distance_m=distance_m,
        operator=operator,
        toll_eur=toll,
    )


def test_gate_chain_skips_synthetic_nodes_and_collapses_repeats():
    nodes = [
        graph_mod.Node(-1, graph_mod.NodeRole.IN),
        graph_mod.Node(5, graph_mod.NodeRole.IN),
        graph_mod.Node(5, graph_mod.NodeRole.OUT),
        graph_mod.Node(6, graph_mod.NodeRole.IN_TOLL),
        graph_mod.Node(-2, graph_mod.NodeRole.OUT),
    ]
    route = routing.Route(nodes=nodes, edges=[], toll_eur=0.0, duration_s=0.0, distance_m=0.0)
    assert response.gate_chain(route) == [5, 6]


def test_toll_gate_hops_counts_only_toll_edges():
    edges = [
        _make_edge(graph_mod.EdgeType.TOLL, operator="APRR", toll={1: 5.0}),
        _make_edge(graph_mod.EdgeType.DWELL),
        _make_edge(graph_mod.EdgeType.TOLL_FREE),
        _make_edge(graph_mod.EdgeType.TOLL, operator="APRR", toll={1: 3.0}),
    ]
    route = routing.Route(nodes=[], edges=edges, toll_eur=8.0, duration_s=0.0, distance_m=0.0)
    assert response.toll_gate_hops(route) == 2


def test_same_operator_split_true_for_repeated_operator_toll_edges():
    edges = [
        _make_edge(graph_mod.EdgeType.TOLL, operator="APRR", toll={1: 5.0}),
        _make_edge(graph_mod.EdgeType.TOLL_FREE),
        _make_edge(graph_mod.EdgeType.TOLL, operator="APRR", toll={1: 3.0}),
    ]
    route = routing.Route(nodes=[], edges=edges, toll_eur=8.0, duration_s=0.0, distance_m=0.0)
    assert response.same_operator_split(route) is True


def test_same_operator_split_false_for_single_toll_edge_or_different_operators():
    single = routing.Route(
        nodes=[], edges=[_make_edge(graph_mod.EdgeType.TOLL, operator="APRR", toll={1: 5.0})],
        toll_eur=5.0, duration_s=0.0, distance_m=0.0,
    )
    assert response.same_operator_split(single) is False

    cross_operator = routing.Route(
        nodes=[],
        edges=[
            _make_edge(graph_mod.EdgeType.TOLL, operator="APRR", toll={1: 5.0}),
            _make_edge(graph_mod.EdgeType.TOLL, operator="ASFC", toll={1: 3.0}),
        ],
        toll_eur=8.0, duration_s=0.0, distance_m=0.0,
    )
    assert response.same_operator_split(cross_operator) is False


def test_detour_floor_is_or_not_and():
    # Phase 1d-follow-up finding: a toll-free alternative that is slower but
    # never longer must still pass (motorway vs. parallel N-road).
    assert response._meets_detour_floor(extra_km=-5.0, extra_minutes=6.0) is True
    assert response._meets_detour_floor(extra_km=15.0, extra_minutes=1.0) is True
    assert response._meets_detour_floor(extra_km=1.0, extra_minutes=1.0) is False


def test_is_worthwhile_compares_implied_rate_to_threshold():
    assert response._is_worthwhile(eur_per_hour_saved=20.0, vot_threshold=12.0) is True
    assert response._is_worthwhile(eur_per_hour_saved=5.0, vot_threshold=12.0) is False
    assert response._is_worthwhile(eur_per_hour_saved=None, vot_threshold=12.0) is False


def test_dedupe_by_gate_chain_removes_duplicate_paths():
    nodes = [graph_mod.Node(1, graph_mod.NodeRole.IN), graph_mod.Node(1, graph_mod.NodeRole.OUT)]
    r1 = routing.Route(nodes=nodes, edges=[], toll_eur=1.0, duration_s=1.0, distance_m=1.0)
    r2 = routing.Route(nodes=nodes, edges=[], toll_eur=1.0, duration_s=1.0, distance_m=1.0)
    assert len(response.dedupe_by_gate_chain([r1, r2])) == 1


@requires_osrm
def test_gate_match_detail_reads_gates_table(base_graph_config_and_db):
    _g, _class_config, db_path = base_graph_config_and_db
    conn = sqlite3.connect(db_path)
    try:
        detail = response.gate_match_detail(conn, [269])
    finally:
        conn.close()
    assert len(detail) == 1
    assert detail[0]["gare_id"] == 269
    assert detail[0]["match_tier"] is not None
    assert detail[0]["match_agreement"] is not None


@requires_osrm
def test_shape_response_dijon_lyon_has_fastest_matching_plain_dijkstra(base_graph_config_and_db):
    base_g, class_config, db_path = base_graph_config_and_db
    g = _graph_copy(base_g)
    with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
        origin_node, dest_node = graph_mod.add_access_edges(g, client, GAZETTEER["dijon"], GAZETTEER["lyon"])
        expected_fastest = routing.find_route(g, origin_node, dest_node, vehicle_class=1)

    conn = sqlite3.connect(db_path)
    try:
        result = response.shape_response(g, origin_node, dest_node, vehicle_class=1, class_config=class_config, conn=conn)
    finally:
        conn.close()

    assert result["vehicle_class"] == 1
    options = result["options"]
    assert 1 <= len(options) <= 5

    fastest_options = [o for o in options if "fastest" in o["labels"]]
    assert len(fastest_options) == 1
    fastest = fastest_options[0]
    assert fastest["toll_eur"] == pytest.approx(expected_fastest.toll_eur)
    assert fastest["duration_s"] == pytest.approx(expected_fastest.duration_s)
    assert fastest["distance_m"] == pytest.approx(expected_fastest.distance_m)

    assert any("cheapest" in o["labels"] for o in options)
    assert any("best_value" in o["labels"] for o in options)

    for opt in options:
        assert len(opt["gates"]) == len(opt["gate_detail"])
        # Guard rail: max_gate_hops - toll edges traversed, derived from the
        # gate chain length as a loose proxy (chain includes toll-free stops
        # too, so this is a generous upper bound, not an exact count).
        assert len(opt["gates"]) <= 2 * response.MAX_GATE_HOPS


@requires_osrm
def test_shape_response_worthwhile_filter_shrinks_with_high_vot(base_graph_config_and_db):
    base_g, class_config, db_path = base_graph_config_and_db
    g = _graph_copy(base_g)
    with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
        origin_node, dest_node = graph_mod.add_access_edges(g, client, GAZETTEER["dijon"], GAZETTEER["lyon"])

    conn = sqlite3.connect(db_path)
    try:
        low_vot = response.shape_response(
            g, origin_node, dest_node, vehicle_class=1, class_config=class_config, conn=conn, vot_threshold=1.0
        )
        high_vot = response.shape_response(
            g, origin_node, dest_node, vehicle_class=1, class_config=class_config, conn=conn, vot_threshold=1000.0
        )
    finally:
        conn.close()

    # A very high VoT should never surface *more* worthwhile detours than a
    # near-zero one (raising the bar can only shrink or hold the surviving
    # unlabelled Pareto set - the 3 core labels are always present regardless).
    low_extra = [o for o in low_vot["options"] if not o["labels"]]
    high_extra = [o for o in high_vot["options"] if not o["labels"]]
    assert len(high_extra) <= len(low_extra)


def test_shape_response_rejects_unknown_vehicle_class():
    with pytest.raises(ValueError):
        response.shape_response(
            graph_mod.Graph(), graph_mod.Node(1, graph_mod.NodeRole.OUT),
            graph_mod.Node(2, graph_mod.NodeRole.IN_TOLL), vehicle_class=9,
            class_config={}, conn=None,
        )
