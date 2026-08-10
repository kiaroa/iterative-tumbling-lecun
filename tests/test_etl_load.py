import sqlite3

from tollroute.etl import load

REPO_ROOT = load.REPO_ROOT


def test_load_populates_sqlite_filtered_to_aprr(tmp_path):
    db_path = tmp_path / "tollroute.sqlite"

    load.run(
        db_path=db_path,
        od_pairs_path=load.DEFAULT_OD_PAIRS_PATH,
        gare_master_path=load.DEFAULT_GARE_MASTER_PATH,
    )

    conn = sqlite3.connect(db_path)
    try:
        (fare_count,) = conn.execute("SELECT COUNT(*) FROM fares").fetchone()
        (gate_count,) = conn.execute("SELECT COUNT(*) FROM gates").fetchone()
        (operator_count,) = conn.execute(
            "SELECT COUNT(DISTINCT operator) FROM fares"
        ).fetchone()
        (zero_price_count,) = conn.execute(
            "SELECT COUNT(*) FROM fares WHERE class1 = 0.0"
        ).fetchone()
    finally:
        conn.close()

    # Reconcile against a source-of-truth count computed independently from the raw CSV.
    expected_fare_count = load._to_int_or_none(
        str(len(load._read_aprr_fares(load.DEFAULT_OD_PAIRS_PATH)))
    )
    assert fare_count == expected_fare_count
    assert fare_count > 0
    assert operator_count == 1  # filtered to APRR only
    assert gate_count > 0
    assert zero_price_count > 0  # zero-price rows loaded, not dropped


def test_zero_price_rows_are_logged_not_dropped(tmp_path, caplog):
    db_path = tmp_path / "tollroute.sqlite"

    with caplog.at_level("WARNING", logger="tollroute.etl.load"):
        load.run(
            db_path=db_path,
            od_pairs_path=load.DEFAULT_OD_PAIRS_PATH,
            gare_master_path=load.DEFAULT_GARE_MASTER_PATH,
        )

    zero_price_warnings = [
        r for r in caplog.records if "zero-price APRR fare" in r.getMessage()
    ]

    conn = sqlite3.connect(db_path)
    try:
        (zero_price_count,) = conn.execute(
            "SELECT COUNT(*) FROM fares WHERE class1 = 0.0"
        ).fetchone()
    finally:
        conn.close()

    assert len(zero_price_warnings) == zero_price_count
    assert zero_price_count > 0


def test_gates_referenced_by_fares_are_all_resolvable(tmp_path):
    db_path = tmp_path / "tollroute.sqlite"

    load.run(
        db_path=db_path,
        od_pairs_path=load.DEFAULT_OD_PAIRS_PATH,
        gare_master_path=load.DEFAULT_GARE_MASTER_PATH,
    )

    conn = sqlite3.connect(db_path)
    try:
        unresolved = conn.execute(
            """
            SELECT COUNT(*) FROM fares
            WHERE (from_gare_id IS NOT NULL
                   AND from_gare_id NOT IN (SELECT gare_id FROM gates))
               OR (to_gare_id IS NOT NULL
                   AND to_gare_id NOT IN (SELECT gare_id FROM gates))
            """
        ).fetchone()[0]
    finally:
        conn.close()

    assert unresolved == 0
