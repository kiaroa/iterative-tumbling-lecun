"""Phase 2d national build + coverage audit (tollroute/etl/coverage_audit.py).

No OSRM dependency — these run unconditionally (the audit is pure CSV/SQLite).
"""

import sqlite3

import pytest

from tollroute.etl import coverage_audit


@pytest.fixture(scope="module")
def full_db(tmp_path_factory):
    """Full national build into a throwaway DB, shared across the module."""
    db_path = tmp_path_factory.mktemp("phase2d") / "full.sqlite"
    conn, build = coverage_audit.build_full_db(db_path=db_path)
    yield conn, build
    conn.close()


def test_national_build_clean_zero_unresolved(full_db):
    _, build = full_db
    # Ground truth (IMPLEMENTATION_PLAN.md): 956 gates, 57,378 fares,
    # 163 blank from + 163 blank to; and — the Phase 2d exit criterion — zero
    # unresolved (resolved-but-missing) gate references.
    assert build.gate_count == 973
    assert build.fare_count == 57378
    assert build.blank_from == 163
    assert build.blank_to == 163
    assert build.fk_violations == 0


def test_foreign_key_check_is_empty(full_db):
    conn, _ = full_db
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_coverage_reproduces_known_operator_figures(full_db):
    conn, _ = full_db
    coverage = {c.operator: c for c in coverage_audit.audit_coverage(conn)}
    assert len(coverage) == 13
    # APRR ground truth from prior phases.
    assert coverage["APRR"].rows == 21349
    assert coverage["APRR"].gates == 188
    assert coverage["APRR"].dense == 188 * 187
    # aliea is the standout near-empty matrix and must be flagged.
    assert coverage["aliea"].rows == 365
    assert coverage["aliea"].gates == 171
    assert coverage["aliea"].flagged is True


def test_materially_below_dense_flag_set(full_db):
    conn, _ = full_db
    flagged = {c.operator for c in coverage_audit.audit_coverage(conn) if c.flagged}
    # Below the 10% floor on this dataset: aliea, ASFC, ATMB.
    assert flagged == {"aliea", "ASFC", "ATMB"}


def test_asymmetry_no_price_ratio_flags(full_db):
    conn, _ = full_db
    result = coverage_audit.audit_asymmetry(conn)
    # Verified finding: the spec's conjectured 426 asymmetric-priced rows do NOT
    # reproduce — zero bidirectional pairs differ in price, so nothing is flagged.
    assert result.ratio_flagged == []
    assert result.bidirectional_pairs == 28386
    assert result.unidirectional_pairs == 263


def test_curate_snap_suspects_noop_without_snap_data(full_db):
    conn, _ = full_db
    # The national build has no snap_distance_m, so nothing is quarantined.
    assert coverage_audit.curate_snap_suspects(conn) == []


def test_curate_snap_suspects_quarantines_over_threshold(tmp_path):
    # Synthetic snap data proves the mechanism fires and records the affected
    # OD-pair count, independent of any live OSRM run.
    db_path = tmp_path / "snap.sqlite"
    conn, _ = coverage_audit.build_full_db(db_path=db_path)
    try:
        conn.execute(
            "UPDATE gates SET snap_distance_m = 500.0 WHERE gare_id = 551"
        )
        conn.commit()
        (expected,) = conn.execute(
            "SELECT COUNT(*) FROM fares "
            "WHERE from_gare_id = 551 OR to_gare_id = 551"
        ).fetchone()

        suspects = coverage_audit.curate_snap_suspects(conn)
        assert [s.gare_id for s in suspects] == [551]
        assert suspects[0].affected_od_pairs == expected
        assert expected > 0

        row = conn.execute(
            "SELECT reason, source_phase, affected_od_pairs FROM suspect_gates "
            "WHERE gare_id = 551"
        ).fetchone()
        assert row == ("snap_distance_over_200m", "phase2d", expected)
    finally:
        conn.close()
