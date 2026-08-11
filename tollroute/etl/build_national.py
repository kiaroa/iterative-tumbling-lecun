"""Build the national (all-operator), graph-ready SQLite DB (Phase 4b-follow-up).

Run as: python3 -m tollroute.etl.build_national

Phase 2d's `coverage_audit.build_full_db` already proved a clean national
CSV->SQLite build is possible (13 operators, 956 gates, 57,378 fares, zero
unresolved gate references) but deliberately left the result unremediated and
unsnapped — that DB (`tollroute_full.sqlite`) exists purely for the Phase 2d
coverage/asymmetry audit and Phase 3c's validation checks, not for serving
routes. This module is the missing link the Phase 4b-follow-up plan item
names: it takes that same national load and applies every remediation phase
already implemented (Phase 2b's two dispositions, Phase 2c/3c's quarantines,
Phase 3c's national snapping) so the result is directly usable by
`tollroute/graph.py`'s `build_graph`, replacing the APRR-only dev DB
`tollroute/etl/load.py` produces.

Pipeline, each step reusing an already-implemented, already-tested module
rather than re-deriving its logic:

1. `coverage_audit.build_full_db` — national CSV->SQLite load, zero unresolved
   gate references (`PRAGMA foreign_key_check`).
2. `operators.build_alias_map` / `write_operator_alias` — populate
   `operator_alias`.
3. Phase 2b zero-price disposition (`remediate_zero_price`) — every
   `class1 == 0` row is classified `free_section` / `free_transfer` (kept,
   already priced at the correct €0) or `drop` (deleted from `fares`, never
   left as a routable free edge with no supporting evidence).
4. Phase 2b blank-endpoint re-match (`rematch_blank_ids`) — every blank
   `from_gare_id`/`to_gare_id` is resolved (row updated in place) or left
   unresolved (already NULL from the load; `graph.py`'s fare query already
   excludes NULL endpoints, so no further action is needed for a drop).
5. Phase 2c coordinate-less gate quarantine (`freeflow.write_suspect_gates`).
6. Phase 3c national snap-quality (`validation.snap_quality.run`) — snaps
   every geocoded gate against the live national OSRM instance, quarantining
   > 200 m snaps to `suspect_gates`.
7. Phase 3c distance-error quarantine (`validation.distance_error.run`) —
   gate-level hard-reject using Phase 3b's precomputed matrices.
8. `cost.seed_class_config` — idempotent, so `tollroute.cli`/`tollroute.api`
   can serve generalised-cost routing straight from this DB without a second
   loader pass.

**Row-id alignment (why the DB file is deleted first, not just its rows):**
steps 3 and 4 locate a specific `fares` row by re-deriving its 0-based index
from a fresh read of `od_pairs.csv` (the same read order
`coverage_audit._read_all_fares` used to build the table) and mapping
`row_index -> fares.id` as `row_index + 1`. This only holds if `fares.id`
(`INTEGER PRIMARY KEY AUTOINCREMENT`) starts counting at 1 on this build.
SQLite's `AUTOINCREMENT` remembers the highest id ever used for a table in
`sqlite_sequence`, surviving a `DELETE FROM fares` — so re-running this
module against an *existing* national DB file would silently continue
numbering from the previous build's last id instead of 1, breaking the
alignment. The DB file is therefore unlinked before every build rather than
relying on `coverage_audit.build_full_db`'s `DELETE FROM ...`, making a
re-run idempotent and the alignment assumption always safe.
"""

from __future__ import annotations

import argparse
import csv
import logging
from collections import Counter
from pathlib import Path

from tollroute import cost
from tollroute.etl import coverage_audit, freeflow, operators, rematch_blank_ids, remediate_zero_price
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL
from tollroute.validation import distance_error, snap_quality

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NATIONAL_DB_PATH = REPO_ROOT / "tollroute" / "db" / "tollroute_national.sqlite"
DEFAULT_OD_PAIRS_PATH = REPO_ROOT / "od_pairs.csv"
DEFAULT_GARE_MASTER_PATH = REPO_ROOT / "gare_master.csv"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase4b_followup_national_build.md"


def apply_zero_price_remediation(
    conn, od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH, gare_master_path: Path = DEFAULT_GARE_MASTER_PATH
) -> Counter:
    """Delete every zero-price `fares` row classified `drop` by Phase 2b's
    named rules (`remediate_zero_price.classify_zero_price_row`); `free_section`
    / `free_transfer` rows are left as-is (already correctly priced at €0).

    Row identity is `csv row_index + 1` — see module docstring.
    """
    with od_pairs_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    gate_lookup = remediate_zero_price.read_gate_lookup(gare_master_path)

    tally: Counter = Counter()
    drop_ids: list[int] = []
    for idx, row in enumerate(rows):
        if row["class1"] not in ("0", "0.0"):
            continue
        classified = remediate_zero_price.classify_zero_price_row(row, gate_lookup)
        tally[classified.disposition.value] += 1
        if classified.disposition is remediate_zero_price.Disposition.DROP:
            drop_ids.append(idx + 1)

    if drop_ids:
        conn.executemany("DELETE FROM fares WHERE id = ?", [(i,) for i in drop_ids])
    conn.commit()
    logger.info(
        "zero-price remediation: %s (%d rows deleted from fares)", dict(tally), len(drop_ids)
    )
    return tally


def apply_blank_endpoint_rematch(
    conn, od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH, gare_master_path: Path = DEFAULT_GARE_MASTER_PATH
) -> tuple[int, int]:
    """Update every resolvable blank-endpoint `fares` row in place with its
    matched `gare_id` (Phase 2b's `rematch_blank_ids`); unresolved rows are
    left NULL, which `graph.py`'s fare query already excludes.

    Row identity is `row_index + 1` — see module docstring. Returns
    (matched_count, dropped_count).
    """
    endpoints = rematch_blank_ids.rematch(od_pairs_path, gare_master_path)
    matched = 0
    dropped = 0
    for ep in endpoints:
        row_id = ep.row_index + 1
        column = f"{ep.endpoint}_gare_id"
        if ep.resolution is rematch_blank_ids.Resolution.MATCHED:
            conn.execute(f"UPDATE fares SET {column} = ? WHERE id = ?", (ep.matched_gare_id, row_id))
            matched += 1
        else:
            dropped += 1
    conn.commit()
    logger.info(
        "blank-endpoint rematch: %d resolved and updated, %d left unresolved (NULL, excluded "
        "from graph edges)",
        matched,
        dropped,
    )
    return matched, dropped


def apply_coordinateless_quarantine(
    conn, od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH, gare_master_path: Path = DEFAULT_GARE_MASTER_PATH
) -> int:
    with gare_master_path.open(newline="", encoding="utf-8") as f:
        gare_master = list(csv.DictReader(f))
    with od_pairs_path.open(newline="", encoding="utf-8") as f:
        od_pairs = list(csv.DictReader(f))
    coordinateless = freeflow.find_coordinateless_gates(gare_master, od_pairs)
    freeflow.write_suspect_gates(conn, coordinateless)
    logger.info("quarantined %d coordinate-less gates to suspect_gates", len(coordinateless))
    return len(coordinateless)


def run(
    db_path: Path = DEFAULT_NATIONAL_DB_PATH,
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
    osrm_base_url: str = DEFAULT_OSRM_BASE_URL,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict:
    if db_path.exists():
        db_path.unlink()  # AUTOINCREMENT row-id alignment - see module docstring

    conn, build = coverage_audit.build_full_db(
        db_path=db_path, od_pairs_path=od_pairs_path, gare_master_path=gare_master_path
    )
    try:
        alias_map = operators.build_alias_map(od_pairs_path, gare_master_path)
        operators.write_operator_alias(conn, alias_map)
        conn.commit()

        zero_price_tally = apply_zero_price_remediation(conn, od_pairs_path, gare_master_path)
        rematch_matched, rematch_dropped = apply_blank_endpoint_rematch(
            conn, od_pairs_path, gare_master_path
        )
        coordinateless_count = apply_coordinateless_quarantine(conn, od_pairs_path, gare_master_path)

        snap_results, snap_suspects = snap_quality.run(conn, osrm_base_url=osrm_base_url)
        distance_result, distance_suspects = distance_error.run(
            conn, od_pairs_path=od_pairs_path, gare_master_path=gare_master_path
        )

        cost.seed_class_config(conn)
        conn.commit()

        (final_fare_count,) = conn.execute("SELECT COUNT(*) FROM fares").fetchone()
        (suspect_count,) = conn.execute("SELECT COUNT(*) FROM suspect_gates").fetchone()
        (active_gate_count,) = conn.execute(
            "SELECT COUNT(*) FROM gates WHERE snap_lat IS NOT NULL AND snap_lon IS NOT NULL "
            "AND gare_id NOT IN (SELECT gare_id FROM suspect_gates)"
        ).fetchone()

        summary = {
            "raw_gate_count": build.gate_count,
            "raw_fare_count": build.fare_count,
            "final_fare_count": final_fare_count,
            "active_gate_count": active_gate_count,
            "suspect_gate_count": suspect_count,
            "zero_price_tally": dict(zero_price_tally),
            "rematch_matched": rematch_matched,
            "rematch_dropped": rematch_dropped,
            "coordinateless_count": coordinateless_count,
            "snap_suspect_count": len(snap_suspects),
            "distance_suspect_count": len(distance_suspects),
        }
        logger.info("national build complete: %s", summary)

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_report(summary))
        return summary
    finally:
        conn.close()


def render_report(summary: dict) -> str:
    lines = [
        "# Phase 4b-follow-up — National graph-ready DB build",
        "",
        "Generated by `tollroute/etl/build_national.py`, which chains every already-"
        "implemented remediation phase (2b zero-price disposition, 2b blank-endpoint "
        "rematch, 2c coordinate-less quarantine, 3c national snap + distance-error "
        "quarantine) on top of Phase 2d's national CSV->SQLite load, producing "
        "`tollroute_national.sqlite` — the DB `tollroute/cli.py`/`tollroute/api.py` now "
        "serve routes from, replacing the APRR-only dev DB.",
        "",
        "| metric | value |",
        "|---|---|",
        f"| raw gates loaded | {summary['raw_gate_count']} |",
        f"| raw fares loaded | {summary['raw_fare_count']} |",
        f"| fares after zero-price `drop` deletion | {summary['final_fare_count']} |",
        f"| zero-price disposition tally | {summary['zero_price_tally']} |",
        f"| blank endpoints resolved | {summary['rematch_matched']} |",
        f"| blank endpoints left unresolved (NULL) | {summary['rematch_dropped']} |",
        f"| coordinate-less gates quarantined | {summary['coordinateless_count']} |",
        f"| gates quarantined (snap > 200 m) | {summary['snap_suspect_count']} |",
        f"| gates quarantined (distance error > 20%, gate-level policy) | "
        f"{summary['distance_suspect_count']} |",
        f"| **total gates quarantined to suspect_gates** | **{summary['suspect_gate_count']}** |",
        f"| **active gates available to the graph builder** | **{summary['active_gate_count']}** |",
        "",
        "Active gates = snapped (`snap_lat`/`snap_lon` populated) AND not in "
        "`suspect_gates`. `tollroute/graph.py`'s `_gate_rows` query excludes "
        "`suspect_gates` directly, so every quarantine step above is enforced "
        "structurally, not just reported.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_NATIONAL_DB_PATH)
    parser.add_argument("--od-pairs", type=Path, default=DEFAULT_OD_PAIRS_PATH)
    parser.add_argument("--gare-master", type=Path, default=DEFAULT_GARE_MASTER_PATH)
    parser.add_argument("--osrm-base-url", default=DEFAULT_OSRM_BASE_URL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    run(
        db_path=args.db,
        od_pairs_path=args.od_pairs,
        gare_master_path=args.gare_master,
        osrm_base_url=args.osrm_base_url,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()
