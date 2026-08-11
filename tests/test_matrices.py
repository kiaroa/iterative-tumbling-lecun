import numpy as np
import httpx
import pytest

from tollroute import matrices
from tollroute.etl import cluster_gates


def _osrm_reachable() -> bool:
    try:
        httpx.get(f"{matrices.DEFAULT_OSRM_BASE_URL}/nearest/v1/car/5.0,47.0", timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live OSRM instance not reachable on DEFAULT_OSRM_BASE_URL"
)


def _cluster(physical_gate_id: int, lat: float, lon: float) -> cluster_gates.PhysicalCluster:
    return cluster_gates.PhysicalCluster(
        physical_gate_id=physical_gate_id, lat=lat, lon=lon, gare_ids=(physical_gate_id,)
    )


def _mock_table_client(n: int, missing: set[tuple[int, int]] | None = None) -> httpx.Client:
    """Deterministic n x n table: duration = 100*(i+j+1), distance = 1000*(i+j+1),
    except cells in `missing` which OSRM reports as null (no route).
    """
    missing = missing or set()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/table/v1/car/")
        params = dict(p.split("=") for p in request.url.query.decode().split("&"))
        sources = [int(x) for x in params["sources"].split(";")]
        destinations = [int(x) for x in params["destinations"].split(";")]
        durations = []
        distances = []
        for i in sources:
            drow, distrow = [], []
            for j in destinations:
                if (i, j) in missing:
                    drow.append(None)
                    distrow.append(None)
                else:
                    drow.append(100.0 * (i + j + 1))
                    distrow.append(1000.0 * (i + j + 1))
            durations.append(drow)
            distances.append(distrow)
        return httpx.Response(200, json={"code": "Ok", "durations": durations, "distances": distances})

    return httpx.Client(base_url="http://osrm.test", transport=httpx.MockTransport(handler))


def test_compute_matrices_shapes_and_values():
    clusters = [_cluster(1, 48.0, 2.0), _cluster(2, 48.1, 2.1), _cluster(3, 48.2, 2.2)]
    with _mock_table_client(3, missing={(0, 2)}) as client:
        result = matrices.compute_matrices(clusters, client)

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
    with _mock_table_client(2) as client:
        built = matrices.compute_matrices(clusters, client)
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
    with _mock_table_client(2) as client:
        two_by_two = matrices.compute_matrices(clusters2, client)
    with _mock_table_client(3) as client:
        three_by_three = matrices.compute_matrices(clusters3, client)

    tmp_path.mkdir(exist_ok=True)
    for name in matrices.MATRIX_NAMES[:1]:
        np.save(tmp_path / f"{name}.npy", two_by_two[name])
    for name in matrices.MATRIX_NAMES[1:]:
        np.save(tmp_path / f"{name}.npy", three_by_three[name])

    with pytest.raises(ValueError):
        matrices.load_matrices(tmp_path)


def test_spot_check_sample_size_and_no_diagonal():
    clusters = [_cluster(i, 48.0 + i * 0.01, 2.0 + i * 0.01) for i in range(5)]
    with _mock_table_client(5) as client:
        built = matrices.compute_matrices(clusters, client)

    checks = matrices.spot_check(built, clusters, sample_size=10, seed=1)
    assert len(checks) == 10
    for row in checks:
        assert row["from_physical_gate_id"] != row["to_physical_gate_id"]


def test_physical_gate_points_matches_cluster_gates_count():
    clusters = matrices.physical_gate_points()
    assert len(clusters) == 815
    assert [c.physical_gate_id for c in clusters] == sorted(c.physical_gate_id for c in clusters)


@requires_osrm
def test_run_against_live_osrm_produces_loadable_matrices(tmp_path):
    """Small end-to-end smoke test against a handful of real gates (not the
    full 815 - that's the module's __main__ / phase report run), confirming
    the live OSRM /table wiring and the save->load round trip both work.
    """
    clusters = matrices.physical_gate_points()[:5]
    with httpx.Client(base_url=matrices.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
        built = matrices.compute_matrices(clusters, client)
    matrices.save_matrices(built, tmp_path)
    loaded = matrices.load_matrices(tmp_path)
    for name in matrices.MATRIX_NAMES:
        assert loaded[name].shape == (5, 5)
