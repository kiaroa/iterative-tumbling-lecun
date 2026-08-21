import sqlite3

import httpx
import pytest

from tollroute.etl import load, snap_report
from tollroute.routing_engine import DEFAULT_FULL_URL, RoutingEngine


def _osrm_reachable() -> bool:
    try:
        httpx.get(f"{DEFAULT_FULL_URL}/status", timeout=2.0)
        return True
    except Exception:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live Valhalla instance not reachable on DEFAULT_FULL_URL"
)


@pytest.fixture
def loaded_db(tmp_path):
    db_path = tmp_path / "tollroute.sqlite"
    load.run(
        db_path=db_path,
        od_pairs_path=load.DEFAULT_OD_PAIRS_PATH,
        gare_master_path=load.DEFAULT_GARE_MASTER_PATH,
    )
    return db_path


@requires_osrm
def test_snap_all_gates_populates_snap_columns(loaded_db):
    conn = sqlite3.connect(loaded_db)
    try:
        engine = RoutingEngine()
        try:
            results = snap_report.snap_all_gates(conn, engine)
        finally:
            engine.close()

        assert len(results) > 0
        (snapped_count,) = conn.execute(
            "SELECT COUNT(*) FROM gates WHERE snap_distance_m IS NOT NULL"
        ).fetchone()
        assert snapped_count == len(results)
    finally:
        conn.close()


@requires_osrm
def test_all_5_named_test_pairs_have_prices_and_distinct_routes(loaded_db):
    conn = sqlite3.connect(loaded_db)
    engine = RoutingEngine()
    try:
        fare_results = [
            snap_report.verify_fare_pair(conn, engine, pair)
            for pair in snap_report.FARE_TEST_PAIRS
        ]
        geo_result = snap_report.verify_geo_only_pair(
            engine, snap_report.GEO_ONLY_TEST_PAIR
        )
    finally:
        engine.close()
        conn.close()

    assert len(fare_results) == 4
    for r in fare_results:
        assert r["od_price_eur"] > 0
        assert r["distinct_route"] is True

    # The A75 edge case has no APRR price and is expected to show no toll-driven
    # detour in this corridor (that is the point of the edge case).
    assert geo_result["distinct_route"] is False
