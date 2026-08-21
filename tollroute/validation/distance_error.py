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
(`tollroute/matrices.py`), not a fresh per-row OSRM `/route` call.

*This module previously asserted that "a lookup is equivalent to a live call
for this purpose". That assertion was never checked, and it is false for the
matrices currently on disk:* measured against 21,656 live-OSRM distances for
the very pairs checked here, the matrix agrees within 10% on **8%** of pairs,
median matrix/live ratio **1.71**, p95 **8.3**. It is wrong everywhere, worst
inside the bfc-ara region (3.4% agreement), so a stale regional build does not
explain it. Every quarantine this module writes is derived from that matrix,
so `validate_distance_source` below now samples live OSRM and refuses to
quarantine anything when the source fails — see that function. **Rebuilding
the Phase 3b matrices against the national extract is a prerequisite for the
distance check doing anything useful, and is not fixed here.**

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
from dataclasses import dataclass, field
from pathlib import Path

from tollroute import matrices as mx
from tollroute.etl import cluster_gates, coverage_audit, rematch_blank_ids, snap_report
from tollroute.routing_engine import DEFAULT_FULL_URL, DEFAULT_TOLLFREE_URL, RoutingEngine
from tollroute.validation import gate_verdict

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
    # Deviation after the two corrections below, and the reject decision taken from it.
    # Both are filled in by `_apply_row_rejects` once every row has been seen.
    adjusted_deviation: float = 0.0
    rejected: bool = False


@dataclass
class DistanceErrorResult:
    checks: list[RowCheck]
    no_coord_count: int  # endpoint has no lat/lon (already suspect_gates territory)
    self_physical_count: int  # from/to collapse to the same physical point
    no_route_count: int  # OSRM has no route between the physical points at all
    quarantined: dict[int, tuple[int, int]]  # gare_id -> (bad_count, total_count)
    operator_medians: dict[str, float] = field(default_factory=dict)

    @property
    def rejected_rows(self) -> list[RowCheck]:
        return [c for c in self.checks if c.rejected]


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

    medians = _apply_row_rejects(checks)
    return DistanceErrorResult(
        checks, no_coord, self_physical, no_route, quarantined, medians
    )


def _apply_row_rejects(checks: list[RowCheck]) -> dict[str, float]:
    """Decide, per row, whether its distance disagreement is real. Returns the per-operator
    median ratio used, for reporting.

    Two corrections to the raw `error`, both measured on this dataset while planning:

    1. **Symmetric.** Reject on `min(deviation_forward, deviation_reverse)`. The module
       docstring above already documents why a single direction cannot be trusted (gare_id
       96 -> 95 measures +2029% forward, -4.8% reversed - a carriageway-snap artefact, not a
       bad gate). Taking the better of the two directions removes that whole failure class:
       one-direction rejects 6,889 of 21,470 checked pairs, symmetric rejects 4,400. 18 pairs
       have no reverse counterpart and fall back to one direction.

    2. **Per-operator normalisation.** `distance_km` does not mean the same thing to every
       operator: aliea's median OSRM/source ratio is 0.752 across its entire network, a
       systematic source-semantics offset rather than 300-odd displaced gates. Dividing by
       the operator's own median before thresholding removes the offset and leaves the
       spread. Aggregate effect is small (4,400 -> 4,356) because aliea is only 319 rows;
       it is kept because without it aliea loses most of its network to a units difference.
    """
    ratios_by_operator: dict[str, list[float]] = defaultdict(list)
    for c in checks:
        ratios_by_operator[c.operator].append(1.0 + c.error)
    medians = {op: statistics.median(v) for op, v in ratios_by_operator.items()}

    def normalised_deviation(c: RowCheck) -> float:
        median = medians.get(c.operator) or 1.0
        return abs((1.0 + c.error) / median - 1.0)

    deviation_by_pair = {
        (c.from_gare_id, c.to_gare_id): normalised_deviation(c) for c in checks
    }
    for c in checks:
        forward = deviation_by_pair[(c.from_gare_id, c.to_gare_id)]
        reverse = deviation_by_pair.get((c.to_gare_id, c.from_gare_id))
        c.adjusted_deviation = forward if reverse is None else min(forward, reverse)
        c.rejected = c.adjusted_deviation > HARD_REJECT_DEVIATION
    return medians


DISTANCE_SOURCE_SAMPLE = 40
DISTANCE_SOURCE_TOLERANCE = 0.10
DISTANCE_SOURCE_MIN_AGREEMENT = 0.80


def validate_distance_source(
    checks: list[RowCheck],
    lookup: dict[int, int],
    by_physical_id: dict[int, int],
    tolled_distance_m,
    engine: RoutingEngine,
    sample_size: int = DISTANCE_SOURCE_SAMPLE,
) -> float:
    """Fraction of a random sample where the precomputed matrix agrees with a live
    Valhalla route to within `DISTANCE_SOURCE_TOLERANCE`.

    Returns the agreement fraction. Callers must refuse to quarantine below
    `DISTANCE_SOURCE_MIN_AGREEMENT`. Returns 0.0 when Valhalla is unreachable.
    """
    import random

    sample = random.Random(0).sample(checks, min(sample_size, len(checks)))
    gate_coords = {
        gare_id: (lat, lon)
        for gare_id, lat, lon in _sample_gate_coords(lookup)
    }
    agreed = 0
    compared = 0
    try:
        for check in sample:
            a = gate_coords.get(check.from_gare_id)
            b = gate_coords.get(check.to_gare_id)
            if a is None or b is None:
                continue
            try:
                data = engine.route(a, b)
            except Exception:
                return 0.0
            if data is None:
                continue
            live_km = data["routes"][0]["distance"] / 1000.0
            if live_km <= 0:
                continue
            compared += 1
            if abs(check.osrm_distance_km / live_km - 1.0) <= DISTANCE_SOURCE_TOLERANCE:
                agreed += 1
    except Exception:
        return 0.0
    return agreed / compared if compared else 0.0


def _sample_gate_coords(lookup: dict[int, int]) -> list[tuple[int, float, float]]:
    gates, _ = cluster_gates.read_gates(DEFAULT_GARE_MASTER_PATH)
    return [(g.gare_id, g.lat, g.lon) for g in gates if g.gare_id in lookup]


def ensure_quarantine_columns(conn: sqlite3.Connection) -> None:
    """Idempotently add `fares.quarantined` / `fares.quarantine_reason` to a database built
    before those columns existed in `tollroute/db/schema.sql`. `CREATE TABLE IF NOT EXISTS`
    cannot add a column to an existing table, and the national DB is a committed artefact."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(fares)")}
    if "quarantined" not in existing:
        conn.execute("ALTER TABLE fares ADD COLUMN quarantined INTEGER NOT NULL DEFAULT 0")
    if "quarantine_reason" not in existing:
        conn.execute("ALTER TABLE fares ADD COLUMN quarantine_reason TEXT")
    conn.commit()


def quarantine_fare_rows(conn: sqlite3.Connection, result: DistanceErrorResult) -> int:
    """Mark the individual fare rows whose distance disagreement survives both corrections
    in `_apply_row_rejects`.

    This replaces gate-level quarantine as the *primary* defence. A gate-level reject takes
    down every fare touching that gate - measured at 7,728 of 57,141 rows for 46 gates, with
    single gates costing 511 (DEUX-CHAISES) and 324 (the A71 Clermont cluster) rows each -
    even though the evidence against those gates was one signal that never ran on two thirds
    of the network. Rejecting the row instead confines the damage to the pair that actually
    disagrees.

    Directionless: a rejected pair marks both directions, since the reject decision is
    already symmetric.
    """
    conn.execute("UPDATE fares SET quarantined = 0, quarantine_reason = NULL")
    reason = (
        f"OSRM tolled distance deviates > {HARD_REJECT_DEVIATION:.0%} from source "
        "distance_km after per-operator normalisation, in both directions"
    )
    pairs = {
        (c.from_gare_id, c.to_gare_id) for c in result.checks if c.rejected
    }
    pairs |= {(b, a) for a, b in pairs}
    conn.executemany(
        "UPDATE fares SET quarantined = 1, quarantine_reason = ? "
        "WHERE from_gare_id = ? AND to_gare_id = ?",
        [(reason, a, b) for a, b in sorted(pairs)],
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM fares WHERE quarantined = 1").fetchone()[0]


def _clear_fare_quarantine(conn: sqlite3.Connection) -> int:
    """Release every row-level quarantine. Used when the distance source fails validation:
    a quarantine that cannot be justified must not survive from a previous build."""
    conn.execute("UPDATE fares SET quarantined = 0, quarantine_reason = NULL")
    conn.commit()
    return 0


def quarantine_gates(
    conn: sqlite3.Connection,
    result: DistanceErrorResult,
    gate_scores_path: Path = gate_verdict.DEFAULT_GATE_SCORES_PATH,
    distance_source_trusted: bool = True,
) -> list[QuarantinedGate]:
    """Write the hard-rejected gates into `suspect_gates`, mirroring
    `coverage_audit.curate_snap_suspects`'s upsert shape and affected-OD-pair
    convention.

    **Two signals now required, not one (Phase 3c revision).** A gate is quarantined only
    when the distance rule rejects it *and* `analysis/gate_validation` independently scored it
    `LIKELY_INVALID`. Measured on this dataset, the distance rule alone quarantined 46 gates
    of which 43 score `LIKELY_VALID`, snapping to road at a median of 8.1 m (all gates:
    5.0 m) - while 8 gates scored `LIKELY_INVALID` were not quarantined at all. Requiring
    agreement leaves exactly one gate: 844 "Système Ouvert", an administrative label for a
    whole free-flow toll system referenced from 18 unrelated corridors, which is the case the
    module docstring above already names as the genuine find.

    Rows this run no longer quarantines are deleted, so releasing a gate takes effect instead
    of lingering from a previous build.
    """
    verdict_invalid = gate_verdict.invalid_gate_ids(gate_scores_path)
    confirmed = (
        {
            gare_id: counts
            for gare_id, counts in result.quarantined.items()
            if gare_id in verdict_invalid
        }
        if distance_source_trusted
        else {}
    )
    # A gate that is not a physical toll point at all is quarantined regardless of whether
    # the distance source can be trusted - that evidence (`gate_verdict.non_physical_gate_ids`)
    # comes from the name, the OD role and the validation suite, none of which touch the
    # matrix. Without this, an untrusted matrix silently readmits gare_id 844.
    for gare_id in gate_verdict.non_physical_gate_ids(gate_scores_path):
        confirmed.setdefault(gare_id, result.quarantined.get(gare_id, (0, 0)))
    released = sorted(set(result.quarantined) - set(confirmed))
    if released:
        conn.executemany(
            "DELETE FROM suspect_gates WHERE gare_id = ? AND reason = ?",
            [(gare_id, SUSPECT_REASON) for gare_id in released],
        )
        logger.info(
            "%d gates released from quarantine: distance rule rejected them but the gate "
            "validation suite scores them valid",
            len(released),
        )

    suspects: list[QuarantinedGate] = []
    for gare_id, (bad, total) in sorted(confirmed.items()):
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
                (
                    f"{bad}/{total} checked OD pairs (>= {GATE_REJECT_MIN_SAMPLE} sample, "
                    f">= {GATE_REJECT_FRACTION:.0%} bad) deviate > "
                    f"{HARD_REJECT_DEVIATION:.0%} from distance_km, and the gate validation "
                    f"suite scores this gate {gate_verdict.LIKELY_INVALID}"
                    if total
                    else "not a physical toll point: scored "
                    f"{gate_verdict.LIKELY_INVALID}, flagged VIRTUAL and OD_SINK_ONLY "
                    "(never an origin), so no driver can enter the network here"
                ),
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
    engine: RoutingEngine | None = None,
) -> tuple[DistanceErrorResult, list[QuarantinedGate]]:
    """`conn` must already point at a national (all-operator) build."""
    own_engine = engine is None
    if own_engine:
        engine = RoutingEngine()
    try:
        return _run(conn, od_pairs_path, gare_master_path, engine)
    finally:
        if own_engine:
            engine.close()


def _run(
    conn: sqlite3.Connection,
    od_pairs_path: Path,
    gare_master_path: Path,
    engine: RoutingEngine,
) -> tuple[DistanceErrorResult, list[QuarantinedGate]]:
    gates, _coordinateless = cluster_gates.read_gates(gare_master_path)
    clusters = cluster_gates.cluster_physical_points(gates)
    lookup = cluster_gates.build_lookup(clusters)
    by_physical_id = {c.physical_gate_id: i for i, c in enumerate(sorted(clusters, key=lambda c: c.physical_gate_id))}

    loaded = mx.load_matrices()
    rows = resolved_fare_rows(od_pairs_path, gare_master_path)
    result = compute_checks(rows, lookup, by_physical_id, loaded["tolled_distance_m"])
    ensure_quarantine_columns(conn)

    agreement = validate_distance_source(
        result.checks, lookup, by_physical_id, loaded["tolled_distance_m"], engine
    )
    source_trusted = agreement >= DISTANCE_SOURCE_MIN_AGREEMENT
    if not source_trusted:
        logger.error(
            "distance source REJECTED: the precomputed tolled_distance_m matrix agrees with "
            "live OSRM on only %.0f%% of a %d-pair sample (need %.0f%%). No fare row will be "
            "quarantined on distance error - rebuild the Phase 3b matrices against the "
            "national extract first.",
            agreement * 100,
            DISTANCE_SOURCE_SAMPLE,
            DISTANCE_SOURCE_MIN_AGREEMENT * 100,
        )

    suspects = quarantine_gates(conn, result, distance_source_trusted=source_trusted)
    quarantined_rows = (
        quarantine_fare_rows(conn, result) if source_trusted else _clear_fare_quarantine(conn)
    )

    pct = error_percentiles(result.checks)
    raw_bad = sum(1 for c in result.checks if abs(c.error) > HARD_REJECT_DEVIATION)
    logger.info(
        "distance check: %d rows checked, %d > %.0f%% raw deviation, %d rejected after "
        "symmetric + per-operator normalisation (%d fare rows quarantined), %d gates "
        "quarantined (median abs error %.1f%%)",
        len(result.checks),
        raw_bad,
        HARD_REJECT_DEVIATION * 100,
        len(result.rejected_rows),
        quarantined_rows,
        len(suspects),
        pct.get("median", 0.0) * 100,
    )
    logger.info(
        "per-operator median OSRM/source ratio: %s",
        ", ".join(f"{op} {m:.3f}" for op, m in sorted(result.operator_medians.items())),
    )
    return result, suspects


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=coverage_audit.DEFAULT_FULL_DB_PATH)
    parser.add_argument("--od-pairs", type=Path, default=DEFAULT_OD_PAIRS_PATH)
    parser.add_argument("--gare-master", type=Path, default=DEFAULT_GARE_MASTER_PATH)
    parser.add_argument("--full-url", default=DEFAULT_FULL_URL)
    parser.add_argument("--tollfree-url", default=DEFAULT_TOLLFREE_URL)
    args = parser.parse_args()

    engine = RoutingEngine(full_url=args.full_url, tollfree_url=args.tollfree_url)
    conn, _ = coverage_audit.build_full_db(db_path=args.db)
    try:
        run(conn, od_pairs_path=args.od_pairs, gare_master_path=args.gare_master, engine=engine)
    finally:
        conn.close()
        engine.close()


if __name__ == "__main__":
    main()
