import httpx
import numpy as np
import pytest

from tollroute.etl.cluster_gates import PhysicalCluster
from tollroute.routing_engine import DEFAULT_FULL_URL, RoutingEngine
from tollroute.validation import toll_tagging_audit as tta


def _osrm_reachable() -> bool:
    try:
        httpx.get(f"{DEFAULT_FULL_URL}/status", timeout=2.0)
        return True
    except Exception:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live Valhalla instance not reachable on DEFAULT_FULL_URL"
)


def _cluster(pid: int, lat: float, lon: float) -> PhysicalCluster:
    return PhysicalCluster(physical_gate_id=pid, lat=lat, lon=lon, gare_ids=(pid,))


def _route(coords: list[tuple[float, float]]) -> dict:
    """coords is [(lat, lon), ...]; OSRM geometry wire format is [lon, lat]."""
    return {"geometry": {"coordinates": [[lon, lat] for lat, lon in coords]}}


def test_check_route_proximity_passes_when_far_from_other_gates():
    clusters = [_cluster(1, 48.0, 2.0), _cluster(2, 48.5, 2.5), _cluster(3, 60.0, 20.0)]
    route = _route([(48.0, 2.0), (48.25, 2.25), (48.5, 2.5)])
    passed, gate_id, dist_m = tta.check_route_proximity(route, clusters, origin_id=1, dest_id=2)
    assert passed is True
    assert gate_id is None
    assert dist_m is None


def test_check_route_proximity_fails_when_route_passes_near_a_third_gate():
    # Gate 3 sits almost exactly on the route's midpoint - well within threshold.
    clusters = [_cluster(1, 48.0, 2.0), _cluster(2, 48.5, 2.5), _cluster(3, 48.25, 2.25)]
    route = _route([(48.0, 2.0), (48.25, 2.25), (48.5, 2.5)])
    passed, gate_id, dist_m = tta.check_route_proximity(route, clusters, origin_id=1, dest_id=2)
    assert passed is False
    assert gate_id == 3
    assert dist_m < tta.PROXIMITY_THRESHOLD_M


def test_check_route_proximity_excludes_the_routes_own_endpoints():
    # Only the origin/destination gates are near the route - nothing else to trip on.
    clusters = [_cluster(1, 48.0, 2.0), _cluster(2, 48.5, 2.5)]
    route = _route([(48.0, 2.0), (48.25, 2.25), (48.5, 2.5)])
    passed, gate_id, dist_m = tta.check_route_proximity(route, clusters, origin_id=1, dest_id=2)
    assert passed is True


def test_sample_route_pairs_excludes_nan_and_self_pairs():
    clusters = [_cluster(i, 48.0 + i * 0.1, 2.0 + i * 0.1) for i in range(4)]
    dist = np.array(
        [
            [np.nan, 1.0, 2.0, np.nan],
            [1.0, np.nan, np.nan, 3.0],
            [2.0, np.nan, np.nan, 4.0],
            [np.nan, 3.0, 4.0, np.nan],
        ],
        dtype=np.float32,
    )
    pairs = tta.sample_route_pairs(clusters, dist, sample_size=10, seed=1)
    for i, j in pairs:
        assert i != j
        assert dist[i, j] == dist[i, j]  # not NaN


def test_sample_route_pairs_is_deterministic_for_a_fixed_seed():
    clusters = [_cluster(i, 48.0 + i * 0.1, 2.0 + i * 0.1) for i in range(5)]
    dist = np.ones((5, 5), dtype=np.float32)
    np.fill_diagonal(dist, np.nan)
    first = tta.sample_route_pairs(clusters, dist, sample_size=5, seed=99)
    second = tta.sample_route_pairs(clusters, dist, sample_size=5, seed=99)
    assert first == second


@requires_osrm
def test_run_route_proximity_sample_against_live_osrm():
    from tollroute import matrices as mx

    clusters = sorted(mx.physical_gate_points(), key=lambda c: c.physical_gate_id)
    loaded = mx.load_matrices()
    engine = RoutingEngine()
    try:
        results = tta.run_route_proximity_sample(
            clusters, loaded["tollfree_distance_m"], engine, sample_size=3, seed=1
        )
    finally:
        engine.close()
    assert len(results) == 3
    for r in results:
        assert r.from_physical_gate_id != r.to_physical_gate_id
        assert r.distance_km > 0


@requires_osrm
def test_run_isolated_gate_sample_against_live_osrm():
    from tollroute import matrices as mx

    clusters = sorted(mx.physical_gate_points(), key=lambda c: c.physical_gate_id)
    loaded = mx.load_matrices()
    engine = RoutingEngine()
    try:
        results = tta.run_isolated_gate_sample(
            clusters, loaded["tollfree_distance_m"], engine, sample_size=3, seed=1
        )
    finally:
        engine.close()
    assert len(results) == 1
    for r in results:
        assert r.tollfree_snap_m >= r.default_snap_m - 1e-6  # exclude=toll can only push further
        assert r.delta_m == pytest.approx(r.tollfree_snap_m - r.default_snap_m)
