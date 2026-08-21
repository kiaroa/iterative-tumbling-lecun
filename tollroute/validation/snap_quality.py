"""National snap-quality check for all geocoded gates (Phase 3c, deliverable 1).

Run as: python3 -m tollroute.validation.snap_quality

Phase 1b's `tollroute/etl/snap_report.py` already snaps gates via OSRM `/nearest`,
but only APRR gates against the regional `bfc-ara` extract — the Phase 1b report
itself flags that as not meaningful at national scale ("the national OSRM build
is required before this flag list is meaningful as a data-quality signal").
Phase 2d's `coverage_audit.curate_snap_suspects` already implements the >200 m
quarantine-to-`suspect_gates` mechanism but deliberately runs it against no snap
data ("national OSRM snapping is Phase 3a... definitive snap-quality curation is
Phase 3c").

This module is that curation step: it snaps every geocoded gate (953 of 956, per
`gare_master.csv`) against the now-live *national* OSRM instance (Phase 3a), and
reuses — rather than re-implements — `snap_report.osrm_nearest` for the OSRM
call, `cluster_gates.haversine_m` for the distance, and
`coverage_audit.curate_snap_suspects` (same 200 m threshold) for the quarantine.

Operates on an already-open connection to the national multi-operator DB
(`tollroute_full.sqlite`, built by `coverage_audit.build_full_db`) rather than
building its own, so a caller running this alongside `distance_error.py` in the
same phase (see `tollroute/validation/phase3c.py`) does one build, not two —
`coverage_audit.build_full_db` deletes and re-inserts `gates`/`fares` from the
source CSVs on every call, which would silently wipe the snap columns this
module just wrote if each check built its own copy.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path


from tollroute.etl import coverage_audit
from tollroute.etl.cluster_gates import haversine_m
from tollroute.etl.snap_report import osrm_nearest
from tollroute.routing_engine import DEFAULT_FULL_URL, DEFAULT_TOLLFREE_URL, RoutingEngine

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Same 200 m curation threshold Phase 2d already wired up — single source of
# truth is `coverage_audit.SNAP_SUSPECT_THRESHOLD_M`, not a re-declared constant.
SNAP_FLAG_THRESHOLD_M = coverage_audit.SNAP_SUSPECT_THRESHOLD_M


@dataclass
class SnapResult:
    gare_id: int
    canonical_name: str
    lat: float
    lon: float
    snap_lat: float
    snap_lon: float
    snap_distance_m: float


def snap_all_gates(conn: sqlite3.Connection, engine: RoutingEngine) -> list[SnapResult]:
    """Snap every gate with coordinates against the live Valhalla instance."""
    gates = conn.execute(
        "SELECT gare_id, canonical_name, lat, lon FROM gates "
        "WHERE lat IS NOT NULL AND lon IS NOT NULL ORDER BY gare_id"
    ).fetchall()

    results: list[SnapResult] = []
    for gare_id, canonical_name, lat, lon in gates:
        waypoint = osrm_nearest(engine, lat, lon)
        snap_lon, snap_lat = waypoint["location"]
        snap_distance_m = haversine_m(lat, lon, snap_lat, snap_lon)
        conn.execute(
            "UPDATE gates SET snap_lat = ?, snap_lon = ?, snap_distance_m = ? WHERE gare_id = ?",
            (snap_lat, snap_lon, snap_distance_m, gare_id),
        )
        results.append(
            SnapResult(gare_id, canonical_name, lat, lon, snap_lat, snap_lon, snap_distance_m)
        )
    conn.commit()

    no_coords = conn.execute(
        "SELECT COUNT(*) FROM gates WHERE lat IS NULL OR lon IS NULL"
    ).fetchone()[0]
    if no_coords:
        logger.info(
            "%d gates have no lat/lon and were not snapped (already quarantined "
            "to suspect_gates by Phase 2c's freeflow.py)",
            no_coords,
        )
    return results


def run(
    conn: sqlite3.Connection, engine: RoutingEngine | None = None
) -> tuple[list[SnapResult], list[coverage_audit.SnapSuspect]]:
    """Snap every gate, then quarantine >200 m snaps to `suspect_gates`.

    `conn` must already point at a national (all-operator) build, e.g. from
    `coverage_audit.build_full_db`.
    """
    own_engine = engine is None
    if own_engine:
        engine = RoutingEngine()
    try:
        results = snap_all_gates(conn, engine)
    finally:
        if own_engine:
            engine.close()
    suspects = coverage_audit.curate_snap_suspects(conn, SNAP_FLAG_THRESHOLD_M)
    logger.info(
        "snapped %d gates against the national OSRM instance; %d quarantined to "
        "suspect_gates (> %.0f m)",
        len(results),
        len(suspects),
        SNAP_FLAG_THRESHOLD_M,
    )
    return results, suspects


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=coverage_audit.DEFAULT_FULL_DB_PATH)
    parser.add_argument("--full-url", default=DEFAULT_FULL_URL)
    parser.add_argument("--tollfree-url", default=DEFAULT_TOLLFREE_URL)
    args = parser.parse_args()

    engine = RoutingEngine(full_url=args.full_url, tollfree_url=args.tollfree_url)
    conn, _ = coverage_audit.build_full_db(db_path=args.db)
    try:
        run(conn, engine=engine)
    finally:
        conn.close()
        engine.close()


if __name__ == "__main__":
    main()
