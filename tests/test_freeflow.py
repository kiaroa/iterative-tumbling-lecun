"""Tests for the Phase 2c free-flow classification and coordinate-less quarantine.

These run against the real CSVs (no OSRM needed) plus small synthetic fixtures,
matching the CSV-level style of test_cluster_gates.py.
"""

import sqlite3

import pytest

from tollroute.etl import freeflow as ff


@pytest.fixture(scope="module")
def gare_master():
    return ff.read_gare_master(ff.DEFAULT_GARE_MASTER_PATH)


@pytest.fixture(scope="module")
def od_pairs():
    return ff.read_od_pairs(ff.DEFAULT_OD_PAIRS_PATH)


def test_all_three_free_flow_corridors_present_no_override(gare_master, od_pairs):
    # Ground truth: A79, A13, A14 all have fares in od_pairs, so none needs an override.
    for corridor in ff.FREEFLOW_CORRIDORS:
        c = ff.classify_corridor(corridor, gare_master, od_pairs)
        assert c.present_in_fare_matrix, f"{corridor} unexpectedly absent"
        assert not c.override_needed, f"{corridor} unexpectedly needs an override"
        assert c.od_rows_referencing_gates > 0


def test_a14_is_flagged_as_self_loop_single_gantry(gare_master, od_pairs):
    # A14's five fare rows are all self-loops (from == to) — the free-flow
    # single-gantry flat-fee anomaly the graph builder must handle.
    a14 = ff.classify_corridor("A14", gare_master, od_pairs)
    assert a14.self_loop_rows == 5
    assert "self-loop" in a14.note

    # The self-loop pattern is distinctive: A13, by contrast, is conventional.
    a13 = ff.classify_corridor("A13", gare_master, od_pairs)
    assert a13.self_loop_rows == 0


def test_coordinateless_gates_are_exactly_the_three_boundary_markers(gare_master, od_pairs):
    gates = ff.find_coordinateless_gates(gare_master, od_pairs)
    by_id = {g.gare_id: g for g in gates}
    assert set(by_id) == {1, 210, 243}
    # affected od_pairs counts are the real strand cost (spec: log affected count).
    assert by_id[1].affected_od_pairs == 24
    assert by_id[210].affected_od_pairs == 194
    assert by_id[243].affected_od_pairs == 36
    # every quarantined gate carries a non-zero strand count, so none is a silent no-op.
    assert all(g.affected_od_pairs > 0 for g in gates)


def test_run_populates_suspect_gates_and_creates_empty_override(tmp_path):
    db_path = tmp_path / "phase2c.sqlite"
    report_path = tmp_path / "phase2c_freeflow.md"
    classifications, coordinateless = ff.run(
        db_path=db_path, report_path=report_path
    )

    assert report_path.exists()
    assert len(coordinateless) == 3

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT gare_id, source_phase, affected_od_pairs FROM suspect_gates "
            "ORDER BY gare_id"
        ).fetchall()
        assert [r[0] for r in rows] == [1, 210, 243]
        assert all(r[1] == "2c" for r in rows)
        assert {r[0]: r[2] for r in rows} == {1: 24, 210: 194, 243: 36}

        # The override table exists (schema applied) but is intentionally empty,
        # because every corridor is present in the fare matrix.
        (override_count,) = conn.execute(
            "SELECT COUNT(*) FROM freeflow_override"
        ).fetchone()
        assert override_count == 0
        assert not any(c.override_needed for c in classifications)
    finally:
        conn.close()


def test_run_is_idempotent(tmp_path):
    db_path = tmp_path / "phase2c.sqlite"
    report_path = tmp_path / "phase2c_freeflow.md"
    ff.run(db_path=db_path, report_path=report_path)
    ff.run(db_path=db_path, report_path=report_path)  # second run must not duplicate

    conn = sqlite3.connect(db_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM suspect_gates").fetchone()
        assert count == 3
    finally:
        conn.close()


def test_seed_millau_override_writes_gate_selfloop_fare_and_provenance(tmp_path):
    """Phase 5b-follow-up-2: Millau is seeded as one real self-loop gate (same
    shape as A14's 5 dataset self-loop fares), not a two-endpoint fork - class 1
    is sourced directly (is_conjecture=0), classes 2-5 are interpolated from
    APRR's ratios and flagged is_conjecture=1 in `freeflow_override` (fee
    provenance bookkeeping only; the graph builder never reads that table).
    """
    db_path = tmp_path / "millau.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        assert ff.seed_millau_override(conn) is True

        gate = conn.execute(
            "SELECT canonical_name, operators, snap_lat, snap_lon FROM gates WHERE gare_id = ?",
            (ff.MILLAU_GARE_ID,),
        ).fetchone()
        assert gate is not None
        assert gate[1] == "CEVM"
        assert (gate[2], gate[3]) == pytest.approx(ff.MILLAU_BARRIER_COORD)

        fare = conn.execute(
            "SELECT operator, class1, class2, class3, class4, class5 "
            "FROM fares WHERE from_gare_id = ? AND to_gare_id = ?",
            (ff.MILLAU_GARE_ID, ff.MILLAU_GARE_ID),
        ).fetchone()
        assert fare is not None
        assert fare[0] == "CEVM"
        assert fare[1] == pytest.approx(11.30)
        assert all(c > 0 for c in fare[2:])

        rows = conn.execute(
            "SELECT vehicle_class, flat_fee_eur, operator, is_conjecture "
            "FROM freeflow_override WHERE corridor = ? ORDER BY vehicle_class",
            (ff.MILLAU_VIADUCT_CORRIDOR,),
        ).fetchall()
        assert [r[0] for r in rows] == [1, 2, 3, 4, 5]
        assert all(r[2] == "CEVM" for r in rows)
        assert rows[0][1] == pytest.approx(11.30)
        assert rows[0][3] == 0  # sourced, not conjecture
        for _vehicle_class, fee, _operator, is_conjecture in rows[1:]:
            assert is_conjecture == 1
            assert fee > 0
    finally:
        conn.close()


def test_seed_millau_override_is_idempotent_and_reflects_reruns(tmp_path):
    db_path = tmp_path / "millau.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        ff.seed_millau_override(conn)
        ff.seed_millau_override(conn)  # INSERT OR REPLACE: must not duplicate rows

        (gate_count,) = conn.execute(
            "SELECT COUNT(*) FROM gates WHERE gare_id = ?", (ff.MILLAU_GARE_ID,)
        ).fetchone()
        assert gate_count == 1
        (fare_count,) = conn.execute(
            "SELECT COUNT(*) FROM fares WHERE from_gare_id = ? AND to_gare_id = ?",
            (ff.MILLAU_GARE_ID, ff.MILLAU_GARE_ID),
        ).fetchone()
        assert fare_count == 1
        (override_count,) = conn.execute(
            "SELECT COUNT(*) FROM freeflow_override WHERE corridor = ?",
            (ff.MILLAU_VIADUCT_CORRIDOR,),
        ).fetchone()
        assert override_count == 5  # one row per vehicle class, not 10
    finally:
        conn.close()


def test_absent_corridor_would_flag_override_needed():
    # Synthetic: a corridor whose gate is in gare_master but has no od_pairs rows
    # must be flagged as needing an override (guards the branch the real data never hits).
    gare_master = [
        {"gare_id": "9001", "canonical_name": "Ghost Gantry", "all_routes": "A99",
         "lat": "46.0", "lon": "3.0", "operators": "aliea"},
    ]
    od_pairs: list[dict] = []
    c = ff.classify_corridor("A99", gare_master, od_pairs)
    assert not c.present_in_fare_matrix
    assert c.override_needed
    assert "ABSENT" in c.note
