import httpx
import pytest

from tollroute.etl import coverage_audit
from tollroute.validation import snap_quality


def _osrm_reachable() -> bool:
    try:
        httpx.get(f"{snap_quality.DEFAULT_OSRM_BASE_URL}/nearest/v1/car/5.0,47.0", timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live OSRM instance not reachable on DEFAULT_OSRM_BASE_URL"
)


def test_threshold_reuses_coverage_audit_single_source_of_truth():
    assert snap_quality.SNAP_FLAG_THRESHOLD_M == coverage_audit.SNAP_SUSPECT_THRESHOLD_M


@pytest.fixture
def full_db(tmp_path):
    db_path = tmp_path / "full.sqlite"
    conn, _ = coverage_audit.build_full_db(db_path=db_path)
    yield conn
    conn.close()


@requires_osrm
def test_run_snaps_all_gates_and_quarantines_over_threshold(full_db):
    conn = full_db
    results, suspects = snap_quality.run(conn)

    # Ground truth (gare_master.csv): 953 of 956 gates carry coordinates.
    assert len(results) == 953
    (snapped_count,) = conn.execute(
        "SELECT COUNT(*) FROM gates WHERE snap_distance_m IS NOT NULL"
    ).fetchone()
    assert snapped_count == 953
    for r in results:
        assert r.snap_distance_m >= 0

    # Verified on the live national extract: every gate snaps within 200 m,
    # resolving the Phase 1b regional-extract flag count (an out-of-extract
    # coverage artefact, not a data-quality signal).
    assert suspects == []


@requires_osrm
def test_run_is_idempotent_on_rerun(full_db):
    conn = full_db
    snap_quality.run(conn)
    results_2, suspects_2 = snap_quality.run(conn)
    assert len(results_2) == 953
    assert suspects_2 == []
