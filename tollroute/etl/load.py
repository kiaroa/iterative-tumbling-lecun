"""Load od_pairs.csv and gare_master.csv into SQLite, filtered to APRR.

Run as: python3 -m tollroute.etl.load

Zero-price fare rows (class1 == 0) are logged explicitly, never silently
dropped — remediation into a typed disposition is Phase 2b's job, not this
loader's. Blank from/to gare_id rows are likewise loaded as-is (NULL in
SQLite); re-matching them is also Phase 2b's job.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "tollroute" / "db" / "schema.sql"
DEFAULT_DB_PATH = REPO_ROOT / "tollroute" / "db" / "tollroute.sqlite"
DEFAULT_OD_PAIRS_PATH = REPO_ROOT / "od_pairs.csv"
DEFAULT_GARE_MASTER_PATH = REPO_ROOT / "gare_master.csv"

OPERATOR = "APRR"

GATE_COLUMNS = [
    "gare_id",
    "canonical_name",
    "all_names",
    "primary_route",
    "all_routes",
    "inferred_route",
    "junction_ref",
    "all_junctions",
    "operators",
    "name_collision",
    "lat",
    "lon",
    "pr_km",
    "commune",
    "departement",
    "is_interchange",
    "connecting_road",
    "direction_served",
    "toll_system_type",
    "concession_boundary",
    "gare_type",
    "match_tier",
    "match_agreement",
    "match_source",
]

FARE_COLUMNS = [
    "from_gare_id",
    "to_gare_id",
    "operator",
    "from_route",
    "from_junction",
    "from_gare",
    "to_route",
    "to_junction",
    "to_gare",
    "distance_km",
    "start_time",
    "end_time",
    "class1",
    "class2",
    "class3",
    "class4",
    "class5",
]

GATE_INT_COLUMNS = {"gare_id"}
GATE_FLOAT_COLUMNS = {"lat", "lon", "pr_km"}
FARE_INT_COLUMNS = {"from_gare_id", "to_gare_id"}
FARE_FLOAT_COLUMNS = {"distance_km", "class1", "class2", "class3", "class4", "class5"}


def _to_int_or_none(value: str) -> int | None:
    return int(value) if value not in (None, "") else None


def _to_float_or_none(value: str) -> float | None:
    return float(value) if value not in (None, "") else None


def _convert_row(row: dict, int_columns: set, float_columns: set) -> dict:
    converted = dict(row)
    for col in int_columns:
        converted[col] = _to_int_or_none(row[col])
    for col in float_columns:
        converted[col] = _to_float_or_none(row[col])
    return converted


def _read_aprr_gates(gare_master_path: Path) -> list[dict]:
    with gare_master_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            row
            for row in reader
            if OPERATOR in [op.strip() for op in row["operators"].split("|")]
        ]
    return [_convert_row(row, GATE_INT_COLUMNS, GATE_FLOAT_COLUMNS) for row in rows]


def _read_aprr_fares(od_pairs_path: Path) -> list[dict]:
    with od_pairs_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader if row["operator"] == OPERATOR]
    return [_convert_row(row, FARE_INT_COLUMNS, FARE_FLOAT_COLUMNS) for row in rows]


def load_gates(conn: sqlite3.Connection, gare_master_path: Path) -> int:
    gates = _read_aprr_gates(gare_master_path)
    placeholders = ", ".join(f":{col}" for col in GATE_COLUMNS)
    conn.executemany(
        f"INSERT INTO gates ({', '.join(GATE_COLUMNS)}) VALUES ({placeholders})",
        gates,
    )
    return len(gates)


def load_fares(conn: sqlite3.Connection, od_pairs_path: Path) -> tuple[int, int]:
    fares = _read_aprr_fares(od_pairs_path)

    zero_price_rows = [row for row in fares if row["class1"] == 0.0]
    for row in zero_price_rows:
        logger.warning(
            "zero-price APRR fare: %s (%s) -> %s (%s), distance_km=%s, "
            "class1..5=%s/%s/%s/%s/%s",
            row["from_gare_id"],
            row["from_gare"],
            row["to_gare_id"],
            row["to_gare"],
            row["distance_km"],
            row["class1"],
            row["class2"],
            row["class3"],
            row["class4"],
            row["class5"],
        )

    placeholders = ", ".join(f":{col}" for col in FARE_COLUMNS)
    conn.executemany(
        f"INSERT INTO fares ({', '.join(FARE_COLUMNS)}) VALUES ({placeholders})",
        fares,
    )
    return len(fares), len(zero_price_rows)


def run(
    db_path: Path = DEFAULT_DB_PATH,
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.execute("DELETE FROM fares")
        conn.execute("DELETE FROM gates")

        gate_count = load_gates(conn, gare_master_path)
        fare_count, zero_price_count = load_fares(conn, od_pairs_path)
        conn.commit()

        (db_fare_count,) = conn.execute("SELECT COUNT(*) FROM fares").fetchone()
        (db_gate_count,) = conn.execute("SELECT COUNT(*) FROM gates").fetchone()
        if db_fare_count != fare_count or db_gate_count != gate_count:
            raise RuntimeError(
                f"row count mismatch after load: fares {db_fare_count} != "
                f"{fare_count}, gates {db_gate_count} != {gate_count}"
            )

        logger.info(
            "loaded %d APRR gates and %d APRR fares into %s (%d zero-price "
            "fare rows logged above)",
            gate_count,
            fare_count,
            db_path,
            zero_price_count,
        )
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--od-pairs", type=Path, default=DEFAULT_OD_PAIRS_PATH)
    parser.add_argument("--gare-master", type=Path, default=DEFAULT_GARE_MASTER_PATH)
    args = parser.parse_args()
    run(db_path=args.db, od_pairs_path=args.od_pairs, gare_master_path=args.gare_master)


if __name__ == "__main__":
    main()
