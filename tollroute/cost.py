"""Generalised cost function and per-vehicle-class config (Phase 4a).

`G = toll + (km x running_cost_per_km) + (hours x value_of_time)`
(iterative-tumbling-lecun.md Phase 4a). Config is stored in the `class_config`
SQLite table (`tollroute/db/schema.sql`) rather than hard-coded, so real
DGITM/EU figures can replace the indicative defaults below without a code
change - `seed_class_config` only inserts when the table is empty, so a
later, non-conjecture load is never clobbered by a re-run of the ETL loader.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Indicative defaults - CONJECTURE, not sourced figures (spec: "replace with
# DGITM/EU figures before public launch"). Class 1 (light vehicles) and
# class 4 (HGV, 3+ axle) are the two anchors the spec gives directly; classes
# 2 (intermediate: camping-cars, van+trailer), 3 (2-axle trucks) and 5
# (motorcycles) are interpolated/extrapolated between those anchors, not
# independently sourced, and are equally conjecture.
DEFAULT_CLASS_CONFIG: dict[int, tuple[float, float]] = {
    # vehicle_class -> (running_cost_per_km, value_of_time_eur_per_hour)
    1: (0.15, 12.0),
    2: (0.20, 15.0),
    3: (0.25, 30.0),
    4: (0.30, 50.0),
    5: (0.10, 10.0),
}


@dataclass(frozen=True)
class ClassConfig:
    vehicle_class: int
    running_cost_per_km: float
    value_of_time_eur_per_hour: float
    is_conjecture: bool


def seed_class_config(
    conn: sqlite3.Connection, defaults: dict[int, tuple[float, float]] = DEFAULT_CLASS_CONFIG
) -> int:
    """Insert the indicative defaults if `class_config` is empty.

    Idempotent by design: does nothing if any row already exists, so a real
    (non-conjecture) config loaded later is never overwritten by a re-run of
    this function or of `tollroute.etl.load`.
    """
    (count,) = conn.execute("SELECT COUNT(*) FROM class_config").fetchone()
    if count:
        return 0
    rows = [(cls, cost_km, vot, 1) for cls, (cost_km, vot) in defaults.items()]
    conn.executemany(
        "INSERT INTO class_config (vehicle_class, running_cost_per_km, "
        "value_of_time_eur_per_hour, is_conjecture) VALUES (?, ?, ?, ?)",
        rows,
    )
    logger.info(
        "seeded class_config with %d indicative (conjecture) rows - replace with "
        "DGITM/EU figures before public launch",
        len(rows),
    )
    return len(rows)


def load_class_config(conn: sqlite3.Connection) -> dict[int, ClassConfig]:
    """Reads `class_config` into memory (spec: "one data array per vehicle
    class loaded into memory at boot, class swapped at query time").
    """
    rows = conn.execute(
        "SELECT vehicle_class, running_cost_per_km, value_of_time_eur_per_hour, "
        "is_conjecture FROM class_config ORDER BY vehicle_class"
    ).fetchall()
    if not rows:
        raise RuntimeError(
            "class_config table is empty - run tollroute.cost.seed_class_config first"
        )
    return {
        vehicle_class: ClassConfig(vehicle_class, cost_km, vot, bool(conjecture))
        for vehicle_class, cost_km, vot, conjecture in rows
    }


def generalised_cost(
    toll_eur: float,
    distance_m: float,
    duration_s: float,
    running_cost_per_km: float,
    value_of_time_eur_per_hour: float,
) -> float:
    """G = toll + km*running_cost_per_km + hours*VoT."""
    return (
        toll_eur
        + (distance_m / 1000.0) * running_cost_per_km
        + (duration_s / 3600.0) * value_of_time_eur_per_hour
    )
