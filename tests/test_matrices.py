import numpy as np
import httpx
import pytest

from tollroute import matrices
from tollroute.etl import cluster_gates
from tollroute.routing_engine import DEFAULT_FULL_URL, RoutingEngine


def _valhalla_reachable() -> bool:
    try:
        httpx.get(f"{DEFAULT_FULL_URL}/status", timeout=2.0)
        return True
    except Exception:
        return False


requires_osrm = pytest.mark.skipif(
    not _valhalla_reachable(), reason="live Valhalla instance not reachable on DEFAULT_FULL_URL"
)


def _cluster(physical_gate_id: int, lat: float, lon: float) -> cluster_gates.PhysicalCluster:
    return cluster_gates.PhysicalCluster(
        physical_gate_id=physical_gate_id, lat=lat, lon=lon, gare_ids=(physical_gate_id,)
    )


class _MockEngine:
    """Deterministic mock RoutingEngine: duration = 100*(i+j+1), distance = 1000*(i+j+1),
    except cells in `missing` (row_index, col_index) which return None (no route).
    """

    def __init__(self, missing: set[tuple[int, int]] | None = None):
        self._missing = missing or set()

    def close(self) -> None:
        pass

    def table(
        self, coords: list, toll_free: bool = False
    ) -> tuple[list[list], list[list]]:
        n = len(coords)
        durations: list[list] = []
        distances: list[list] = []
        for i in range(n):
            drow: list = []
            distrow: list = []
            for j in range(n):
                if (i, j) in self._missing:
                    drow.append(None)
                    distrow.append(None)
                else:
                    drow.append(100.0 * (i + j + 1))
                    distrow.append(1000.0 * (i + j + 1))
            durations.append(drow)
            distances.append(distrow)
        return durations, distances

    def asymmetric_table(
        self, source_coords: list, dest_coords: list, toll_free: bool = False
    ) -> tuple[list[list], list[list]]:
        m = len(source_coords)
        n = len(dest_coords)
        durations: list[list] = []
        distances: list[list] = []
        for i in range(m):
            drow: list = []
            distrow: list = []
            for j in range(n):
                drow.append(100.0 * (i + j + 1))
                distrow.append(1000.0 * (i + j + 1))
            durations.append(drow)
            distances.append(distrow)
        return durations, distances


def test_compute_matrices_shapes_and_values():
    clusters = [_cluster(1, 48.0, 2.0), _cluster(2, 48.1, 2.1), _cluster(3, 48.2, 2.2)]
    engine = _MockEngine(missing={(0, 2)})
    result = matrices.compute_matrices(clusters, engine)

    assert set(result) == set(matrices.MATRIX_NAMES)
    for name in matrices.MATRIX_NAMES:
        assert result[name].shape == (3, 3)
        assert result[name].dtype == np.float32

    assert result["tolled_duration_s"][1, 2] == pytest.approx(400.0)
    assert result["tolled_distance_m"][1, 2] == pytest.approx(4000.0)
    assert np.isnan(result["tolled_duration_s"][0, 2])
    assert np.isnan(result["tolled_distance_m"][0, 2])


def test_save_and_load_matrices_round_trip(tmp_path):
    clusters = [_cluster(1, 48.0, 2.0), _cluster(2, 48.1, 2.1)]
    engine = _MockEngine()
    built = matrices.compute_matrices(clusters, engine)
    matrices.save_matrices(built, tmp_path)

    loaded = matrices.load_matrices(tmp_path)
    assert set(loaded) == set(matrices.MATRIX_NAMES)
    for name in matrices.MATRIX_NAMES:
        assert np.array_equal(loaded[name], built[name], equal_nan=True)


def test_load_matrices_missing_file_fails_fast(tmp_path):
    with pytest.raises(FileNotFoundError):
        matrices.load_matrices(tmp_path)


def test_load_matrices_corrupt_file_fails_fast(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    for name in matrices.MATRIX_NAMES:
        (tmp_path / f"{name}.npy").write_bytes(b"not a real npy file")

    with pytest.raises(ValueError):
        matrices.load_matrices(tmp_path)


def test_load_matrices_shape_mismatch_fails_fast(tmp_path):
    clusters2 = [_cluster(1, 48.0, 2.0), _cluster(2, 48.1, 2.1)]
    clusters3 = [_cluster(1, 48.0, 2.0), _cluster(2, 48.1, 2.1), _cluster(3, 48.2, 2.2)]
    two_by_two = matrices.compute_matrices(clusters2, _MockEngine())
    three_by_three = matrices.compute_matrices(clusters3, _MockEngine())

    tmp_path.mkdir(exist_ok=True)
    for name in matrices.MATRIX_NAMES[:1]:
        np.save(tmp_path / f"{name}.npy", two_by_two[name])
    for name in matrices.MATRIX_NAMES[1:]:
        np.save(tmp_path / f"{name}.npy", three_by_three[name])

    with pytest.raises(ValueError):
        matrices.load_matrices(tmp_path)


def test_spot_check_sample_size_and_no_diagonal():
    clusters = [_cluster(i, 48.0 + i * 0.01, 2.0 + i * 0.01) for i in range(5)]
    built = matrices.compute_matrices(clusters, _MockEngine())

    checks = matrices.spot_check(built, clusters, sample_size=10, seed=1)
    assert len(checks) == 10
    for row in checks:
        assert row["from_physical_gate_id"] != row["to_physical_gate_id"]


def test_physical_gate_points_matches_cluster_gates_count():
    clusters = matrices.physical_gate_points()
    assert len(clusters) == 835
    assert [c.physical_gate_id for c in clusters] == sorted(c.physical_gate_id for c in clusters)


@requires_osrm
def test_run_against_live_valhalla_produces_loadable_matrices(tmp_path):
    """Small end-to-end smoke test against a handful of real gates (not the
    full 815 - that's the module's __main__ / phase report run), confirming
    the live Valhalla /sources_to_targets wiring and save->load round trip both work.
    """
    clusters = matrices.physical_gate_points()[:5]
    engine = RoutingEngine()
    try:
        built = matrices.compute_matrices(clusters, engine)
    finally:
        engine.close()
    matrices.save_matrices(built, tmp_path)
    loaded = matrices.load_matrices(tmp_path)
    for name in matrices.MATRIX_NAMES:
        assert loaded[name].shape == (5, 5)
