"""Phase 4b-follow-up national graph-ready DB build (tollroute/etl/build_national.py).

Chains Phase 2b/2c/3c's already-tested remediation modules on top of Phase 2d's
national load; the snap-quality step needs a live OSRM instance, so the whole
suite is gated the same way as tests/test_snap_quality.py.
"""

import httpx
import pytest

from tollroute.etl import build_national
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL


def _osrm_reachable() -> bool:
    try:
        httpx.get(f"{DEFAULT_OSRM_BASE_URL}/nearest/v1/car/5.0,47.0", timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live OSRM instance not reachable on DEFAULT_OSRM_BASE_URL"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("phase4b_followup") / "national.sqlite"
    report_path = tmp_path_factory.mktemp("phase4b_followup_report") / "report.md"
    summary = build_national.run(db_path=db_path, report_path=report_path)
    return db_path, summary, report_path


@requires_osrm
def test_national_build_summary_matches_known_disposition_counts(built):
    _db_path, summary, _report_path = built
    # Ground truth from this module's own already-verified upstream phases
    # (coverage_audit's Phase 2d load, remediate_zero_price's Phase 2b
    # disposition, rematch_blank_ids' Phase 2b rematch): 956 raw gates,
    # 57,378 raw fares, 551 zero-price rows split 307 free_section / 6
    # free_transfer / 238 drop, all 326 blank endpoints resolved.
    assert summary["raw_gate_count"] == 956
    assert summary["raw_fare_count"] == 57378
    assert summary["final_fare_count"] == 57378 - 238
    assert summary["zero_price_tally"] == {"free_section": 307, "free_transfer": 6, "drop": 238}
    assert summary["rematch_matched"] == 326
    assert summary["rematch_dropped"] == 0
    assert summary["coordinateless_count"] == 3
    assert summary["distance_suspect_count"] == 43


@requires_osrm
def test_dropped_zero_price_rows_are_absent_and_others_kept(built):
    import sqlite3

    db_path, _summary, _report_path = built
    conn = sqlite3.connect(db_path)
    try:
        (zero_price_remaining,) = conn.execute(
            "SELECT COUNT(*) FROM fares WHERE class1 = 0"
        ).fetchone()
        # drop rows deleted; free_section/free_transfer rows kept (already
        # correctly priced at EUR 0, per remediate_zero_price's dispositions).
        assert zero_price_remaining == 307 + 6
    finally:
        conn.close()


@requires_osrm
def test_no_blank_endpoints_remain_unresolved(built):
    import sqlite3

    db_path, summary, _report_path = built
    conn = sqlite3.connect(db_path)
    try:
        (blank_remaining,) = conn.execute(
            "SELECT COUNT(*) FROM fares WHERE from_gare_id IS NULL OR to_gare_id IS NULL"
        ).fetchone()
        assert blank_remaining == summary["rematch_dropped"]
    finally:
        conn.close()


@requires_osrm
def test_active_gates_excludes_all_suspects(built):
    import sqlite3

    db_path, summary, _report_path = built
    conn = sqlite3.connect(db_path)
    try:
        (active,) = conn.execute(
            "SELECT COUNT(*) FROM gates WHERE snap_lat IS NOT NULL AND snap_lon IS NOT NULL "
            "AND gare_id NOT IN (SELECT gare_id FROM suspect_gates)"
        ).fetchone()
        assert active == summary["active_gate_count"]
    finally:
        conn.close()


@requires_osrm
def test_report_written(built):
    _db_path, _summary, report_path = built
    text = report_path.read_text()
    assert "National graph-ready DB build" in text
    assert "active gates available to the graph builder" in text


@requires_osrm
def test_rerun_against_existing_file_stays_row_id_aligned(tmp_path):
    """Re-running against an already-existing DB file must reproduce the same
    disposition counts, not silently misalign fares.id on the second pass
    (see module docstring: AUTOINCREMENT survives DELETE FROM, so the file is
    unlinked before every build rather than rows cleared)."""
    db_path = tmp_path / "national.sqlite"
    report_path = tmp_path / "report.md"

    first = build_national.run(db_path=db_path, report_path=report_path)
    assert db_path.exists()
    second = build_national.run(db_path=db_path, report_path=report_path)

    assert second["final_fare_count"] == first["final_fare_count"]
    assert second["zero_price_tally"] == first["zero_price_tally"]
    assert second["rematch_matched"] == first["rematch_matched"]
    assert second["active_gate_count"] == first["active_gate_count"]
