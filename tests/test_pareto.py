import sqlite3
import tempfile
from pathlib import Path

import httpx
import pytest

from tollroute import cost
from tollroute import graph as graph_mod
from tollroute import pareto
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
def base_graph_and_config():
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
            class_config = cost.load_class_config(conn)
        finally:
            conn.close()
    return g, class_config


def _graph_copy(g: graph_mod.Graph) -> graph_mod.Graph:
    return graph_mod.Graph(
        nodes=list(g.nodes),
        node_index=dict(g.node_index),
        edges=list(g.edges),
        gate_coords=dict(g.gate_coords),
        access_anchors_entry=dict(g.access_anchors_entry),
        access_anchors_exit=dict(g.access_anchors_exit),
    )


def test_vot_sweep_values_are_logarithmic_and_bounded():
    values = pareto.vot_sweep_values(vot_min=1.0, vot_max=100.0, steps=10)
    assert len(values) == 10
    assert values[0] == pytest.approx(1.0)
    assert values[-1] == pytest.approx(100.0)
    assert all(b > a for a, b in zip(values, values[1:]))  # strictly increasing


@requires_osrm
def test_pareto_sweep_shifts_from_zero_toll_toward_motorway(base_graph_and_config):
    # Named Phase 1c/4a test pair, Dijon -> Lyon: a real toll-free alternative
    # exists alongside the A6 motorway, so this is a genuine trade-off, not a
    # degenerate single-option graph.
    g, class_config = base_graph_and_config
    g = _graph_copy(g)
    with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
        origin_node, dest_node = graph_mod.add_access_edges(
            g, client, GAZETTEER["dijon"], GAZETTEER["lyon"]
        )
        results = pareto.pareto_sweep(g, origin_node, dest_node, vehicle_class=1, class_config=class_config)

    assert len(results) == 10
    assert [r.vot_eur_per_hour for r in results] == sorted(r.vot_eur_per_hour for r in results)

    # Exit criterion (spec: iterative-tumbling-lecun.md Phase 4a): sweeping
    # VoT from EUR 1 to EUR 100 shifts the chosen route from zero-toll toward
    # motorway - toll rises (or holds) and duration falls (or holds) as VoT
    # rises, with a genuine, non-trivial shift somewhere across the sweep.
    tolls = [r.route.toll_eur for r in results]
    durations = [r.route.duration_s for r in results]
    assert all(b >= a - 1e-6 for a, b in zip(tolls, tolls[1:]))
    assert all(b <= a + 1e-6 for a, b in zip(durations, durations[1:]))
    assert tolls[0] == pytest.approx(0.0)
    assert tolls[-1] > tolls[0]
    assert durations[-1] < durations[0]


@requires_osrm
def test_pareto_sweep_generalised_cost_matches_formula(base_graph_and_config):
    g, class_config = base_graph_and_config
    g = _graph_copy(g)
    with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
        origin_node, dest_node = graph_mod.add_access_edges(
            g, client, GAZETTEER["dijon"], GAZETTEER["macon"]
        )
        results = pareto.pareto_sweep(g, origin_node, dest_node, vehicle_class=1, class_config=class_config)

    cfg = class_config[1]
    for r in results:
        expected = cost.generalised_cost(
            r.route.toll_eur, r.route.distance_m, r.route.duration_s,
            cfg.running_cost_per_km, r.vot_eur_per_hour,
        )
        assert r.generalised_cost_eur == pytest.approx(expected)


def test_pareto_sweep_rejects_unknown_vehicle_class(base_graph_and_config):
    g, class_config = base_graph_and_config
    origin = graph_mod.Node(269, graph_mod.NodeRole.OUT)
    dest = graph_mod.Node(930, graph_mod.NodeRole.IN_TOLL)
    with pytest.raises(ValueError):
        pareto.pareto_sweep(g, origin, dest, vehicle_class=9, class_config=class_config)


@requires_osrm
def test_pareto_sweep_origin_equals_destination_is_zero_cost(base_graph_and_config):
    g, class_config = base_graph_and_config
    node = graph_mod.Node(269, graph_mod.NodeRole.OUT)
    results = pareto.pareto_sweep(g, node, node, vehicle_class=1, class_config=class_config)
    for r in results:
        assert r.route.toll_eur == 0.0
        assert r.route.duration_s == 0.0
        assert r.route.distance_m == 0.0
        assert r.generalised_cost_eur == pytest.approx(0.0)
