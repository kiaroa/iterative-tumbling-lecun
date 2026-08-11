"""National OSRM-distance vs `distance_km` error distribution (Phase 3c, deliverable 2).

Run as: python3 -m tollroute.validation.distance_error

Resolves the Phase 1d-follow-up finding (`reports/phase1d_pair_validation.md`):
gate-to-gate OSRM distance systematically overshoots `distance_km` on the small
regional extract due to carriageway-direction snap artefacts, and that report
explicitly deferred a trustworthy verdict to "a full 22,175-row OSRM-vs-
`distance_km` error distribution ... on the Phase 3a national extract" — this
module is that check.

**Row set (verified to reproduce the spec's 22,175 figure exactly):** every
`od_pairs.csv` row with a non-blank `distance_km`, after Phase 2b's blank-
endpoint resolution (`tollroute/etl/rematch_blank_ids.rematch`, reused here
rather than re-implemented) is applied. Both figures were independently
recomputed from the CSVs while planning this module: 22,175 rows have
`distance_km`, of which 21,349 are APRR, 503 AREA, 323 aliea — **the other 10
operators never populate `distance_km` at all**, so this check's coverage is
inherently limited to those 3 operators; that is a source-data property, not a
gap in this module.

**Distance source:** Phase 3b's precomputed 815x815 `tolled_distance_m` matrix
(`tollroute/matrices.py`), not a fresh per-row OSRM `/route` call — the matrix
was built the same way (OSRM auto-snaps each raw `gare_master.csv` coordinate
internally; no separate snap step feeds it), so a lookup is equivalent to a
live call for this purpose, at a fraction of the cost (some od_pairs rows map
to the same physical-gate pair, so a live call per row would be duplicate work
the matrix already amortises).

**Hard-reject policy (judgement call, flagged as conjecture):** the spec's
"hard-reject gates with >20% deviation" is read at *gate* granularity, but a
single row's deviation is frequently a *directional*, route-specific artefact
rather than evidence the gate's own location is wrong — verified directly for
this dataset: gare_id 96 -> 95 (BEAUNE SUD -> Beaune nord, 5.75 km apart)
measures +2029% forward but only -4.8% reversed on the live national OSRM
instance, the same carriageway-snap asymmetry Phase 1d diagnosed at regional
scale, just far more extreme here. Quarantining every gate touched by even one
>20% row would strand roughly a third of the 21,981 checkable rows' worth of
gates — not a credible reading of "hard-reject". Instead a gate is quarantined
only when a *majority* of its own checked pairs deviate, with enough pairs to
be meaningful: `>= GATE_REJECT_MIN_SAMPLE` checked pairs AND
`>= GATE_REJECT_FRACTION` of them over the 20% threshold. This isolates
genuine location/data problems (e.g. gare_id 844 "Système Ouvert", an
`overrides.csv`-geocoded administrative label for a free-flow toll *system*,
not a single physical point, referenced from 18 unrelated corridors — 18/18
bad) from the directional-routing noise, which is left as a documented,
unfixed finding rather than silently forced to pass.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from tollroute import matrices as mx
from tollroute.etl import cluster_gates, coverage_audit, rematch_blank_ids

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OD_PAIRS_PATH = REPO_ROOT / "od_pairs.csv"
DEFAULT_GARE_MASTER_PATH = REPO_ROOT / "gare_master.csv"

# Spec: "hard-reject gates with >20% deviation".
HARD_REJECT_DEVIATION = 0.20
# Spec: "flag top 5% absolute deviation for manual snap review".
TOP_PERCENT_FLAG = 0.05
# Judgement call (flagged in the module docstring): minimum checked pairs and
# bad-fraction before a gate itself (not just one of its pairs) is quarantined.
GATE_REJECT_MIN_SAMPLE = 3
GATE_REJECT_FRACTION = 0.5

SUSPECT_REASON = "distance_error_over_20pct"
SUSPECT_SOURCE_PHASE = "phase3c"


@dataclass
class RowCheck:
    operator: str
    from_gare_id: int
    to_gare_id: int
    distance_km: float
    osrm_distance_km: float
    error: float  # signed relative error: (osrm - distance_km) / distance_km


@dataclass
class DistanceErrorResult:
    checks: list[RowCheck]
    no_coord_count: int  # endpoint has no lat/lon (already suspect_gates territory)
    self_physical_count: int  # from/to collapse to the same physical point
    no_route_count: int  # OSRM has no route between the physical points at all
    quarantined: dict[int, tuple[int, int]]  # gare_id -> (bad_count, total_count)


@dataclass
class QuarantinedGate:
    gare_id: int
    canonical_name: str | None
    bad_count: int
    total_count: int


def resolved_fare_rows(
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
) -> list[dict]:
    """`od_pairs.csv` rows with blank endpoints resolved per Phase 2b, reusing
    `rematch_blank_ids.rematch` rather than re-deriving the resolution.
    """
    rows = rematch_blank_ids.read_od_pairs(od_pairs_path)
    endpoints = rematch_blank_ids.rematch(od_pairs_path, gare_master_path)
    for e in endpoints:
        col = f"{e.endpoint}_gare_id"
        if e.resolution is rematch_blank_ids.Resolution.DROP:
            rows[e.row_index][col] = ""
        else:
            rows[e.row_index][col] = str(e.matched_gare_id)
    return rows


def compute_checks(
    rows: list[dict],
    lookup: dict[int, int],
    by_physical_id: dict[int, int],
    tolled_distance_m,
) -> DistanceErrorResult:
    """`lookup` is gare_id -> physical_gate_id (`cluster_gates.build_lookup`);
    `by_physical_id` is physical_gate_id -> matrix row/column index.
    """
    checks: list[RowCheck] = []
    no_coord = 0
    self_physical = 0
    no_route = 0
    per_gate_total: dict[int, int] = defaultdict(int)
    per_gate_bad: dict[int, int] = defaultdict(int)

    for row in rows:
        if row["distance_km"] in (None, ""):
            continue
        if row["from_gare_id"] in (None, "") or row["to_gare_id"] in (None, ""):
            continue
        from_gare_id = int(row["from_gare_id"])
        to_gare_id = int(row["to_gare_id"])
        pf = lookup.get(from_gare_id)
        pt = lookup.get(to_gare_id)
        if pf is None or pt is None:
            no_coord += 1
            continue
        if pf == pt:
            self_physical += 1
            continue

        i, j = by_physical_id[pf], by_physical_id[pt]
        d_m = tolled_distance_m[i, j]
        if d_m != d_m:  # NaN: no OSRM route at all
            no_route += 1
            continue

        distance_km = float(row["distance_km"])
        osrm_km = d_m / 1000.0
        error = (osrm_km - distance_km) / distance_km
        checks.append(
            RowCheck(row["operator"], from_gare_id, to_gare_id, distance_km, osrm_km, error)
        )

        bad = abs(error) > HARD_REJECT_DEVIATION
        for gare_id in (from_gare_id, to_gare_id):
            per_gate_total[gare_id] += 1
            if bad:
                per_gate_bad[gare_id] += 1

    quarantined = {
        gare_id: (per_gate_bad[gare_id], total)
        for gare_id, total in per_gate_total.items()
        if total >= GATE_REJECT_MIN_SAMPLE
        and per_gate_bad[gare_id] / total >= GATE_REJECT_FRACTION
    }

    return DistanceErrorResult(checks, no_coord, self_physical, no_route, quarantined)


def quarantine_gates(
    conn: sqlite3.Connection, result: DistanceErrorResult
) -> list[QuarantinedGate]:
    """Write the hard-rejected gates into `suspect_gates`, mirroring
    `coverage_audit.curate_snap_suspects`'s upsert shape and affected-OD-pair
    convention.
    """
    suspects: list[QuarantinedGate] = []
    for gare_id, (bad, total) in sorted(result.quarantined.items()):
        row = conn.execute(
            "SELECT canonical_name FROM gates WHERE gare_id = ?", (gare_id,)
        ).fetchone()
        name = row[0] if row else None
        # affected_od_pairs counts fares in the RESOLVED dataset (Phase 2b
        # blank-endpoint rematch), not a raw `fares` table lookup — the latter
        # would undercount gates that only appear via a resolved blank endpoint
        # (e.g. gare_id 551, resolved from 326 originally-blank rows).
        conn.execute(
            "INSERT OR REPLACE INTO suspect_gates "
            "(gare_id, canonical_name, reason, source_phase, affected_od_pairs, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                gare_id,
                name,
                SUSPECT_REASON,
                SUSPECT_SOURCE_PHASE,
                total,
                f"{bad}/{total} checked OD pairs (>= {GATE_REJECT_MIN_SAMPLE} sample, "
                f">= {GATE_REJECT_FRACTION:.0%} bad) deviate > "
                f"{HARD_REJECT_DEVIATION:.0%} from distance_km",
            ),
        )
        suspects.append(QuarantinedGate(gare_id, name, bad, total))
    conn.commit()
    return suspects


def error_percentiles(checks: list[RowCheck]) -> dict[str, float]:
    abs_errors = sorted(abs(c.error) for c in checks)
    if not abs_errors:
        return {}
    n = len(abs_errors)

    def pct(p: float) -> float:
        idx = min(n - 1, int(n * p / 100))
        return abs_errors[idx]

    return {
        "mean": statistics.mean(abs_errors),
        "median": pct(50),
        "p75": pct(75),
        "p90": pct(90),
        "p95": pct(95),
        "p99": pct(99),
        "max": abs_errors[-1],
    }


def run(
    conn: sqlite3.Connection,
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
) -> tuple[DistanceErrorResult, list[QuarantinedGate]]:
    """`conn` must already point at a national (all-operator) build."""
    gates, _coordinateless = cluster_gates.read_gates(gare_master_path)
    clusters = cluster_gates.cluster_physical_points(gates)
    lookup = cluster_gates.build_lookup(clusters)
    by_physical_id = {c.physical_gate_id: i for i, c in enumerate(sorted(clusters, key=lambda c: c.physical_gate_id))}

    loaded = mx.load_matrices()
    rows = resolved_fare_rows(od_pairs_path, gare_master_path)
    result = compute_checks(rows, lookup, by_physical_id, loaded["tolled_distance_m"])
    suspects = quarantine_gates(conn, result)

    pct = error_percentiles(result.checks)
    bad_rows = sum(1 for c in result.checks if abs(c.error) > HARD_REJECT_DEVIATION)
    logger.info(
        "distance check: %d rows checked, %d > %.0f%% deviation, %d gates quarantined "
        "(median abs error %.1f%%)",
        len(result.checks),
        bad_rows,
        HARD_REJECT_DEVIATION * 100,
        len(suspects),
        pct.get("median", 0.0) * 100,
    )
    return result, suspects


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=coverage_audit.DEFAULT_FULL_DB_PATH)
    parser.add_argument("--od-pairs", type=Path, default=DEFAULT_OD_PAIRS_PATH)
    parser.add_argument("--gare-master", type=Path, default=DEFAULT_GARE_MASTER_PATH)
    args = parser.parse_args()

    conn, _ = coverage_audit.build_full_db(db_path=args.db)
    try:
        run(conn, od_pairs_path=args.od_pairs, gare_master_path=args.gare_master)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
