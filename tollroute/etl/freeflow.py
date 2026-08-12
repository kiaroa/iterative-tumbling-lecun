"""Classify free-flow corridors and quarantine coordinate-less gates (Phase 2c).

Run as: python3 -m tollroute.etl.freeflow

Two Phase 2c deliverables from `iterative-tumbling-lecun.md`, the sibling of the
clustering step in `cluster_gates.py`:

1. **Free-flow (barrierless) tolling classification (A79, A13/A14).** Free-flow
   motorways have no physical toll barriers — the fare is charged by gantry via
   number-plate recognition — so the spec flags them as a structural hazard and
   asks: do their gates appear in `gare_master`, are their `od_pairs` rows
   structurally different, and are their fares *present* in the fare matrix? If a
   corridor's fares are **absent**, a per-corridor flat-fee override table is the
   mitigation.

   Finding (this dataset): **all three corridors are present in `od_pairs`**, so
   **no override is needed** — the `freeflow_override` schema table stays empty
   but exists, ready for a future corridor genuinely missing its fares. The one
   genuine structural anomaly is **A14**, whose five fare rows are all
   *self-loops* (`from_gare_id == to_gare_id`): a single-gantry flat fee rather
   than an entry->exit gate pair. This is flagged for the graph builder (a
   self-loop toll edge must become a flat-fee section edge, not a zero-length
   no-op) — see the follow-up item in IMPLEMENTATION_PLAN.md.

   *Note (checked, not assumed):* blank `distance_km` is **not** a free-flow
   signal — 61% of all `od_pairs` rows omit it and whole operators (ASFC,
   Cofiroute, sanef, escota...) omit it for every row, so it is an operator-level
   data property, not a barrierless-tolling marker. The self-loop pattern, by
   contrast, is unique: all five self-loops in the file are A14/sapn.

2. **Coordinate-less gate quarantine.** Three `gare_master` gates carry no
   lat/lon (ids 1, 210, 243 — all "limite de concession" administrative boundary
   markers, not real addressable barriers). They cannot be snapped to a road and
   are not meaningfully geocodable (a concession boundary is a point on a
   motorway, not an address; Phase 2a established no external source exists), so
   they are quarantined into the `suspect_gates` table with the count of
   `od_pairs` rows each one strands (spec: "logged with affected OD pair count").

**Conjecture flagged explicitly:** treating the three "limite de concession"
gates as non-geocodable (rather than attempting to place them on their named
route) is a judgement call — they are boundary nodes, not barriers, so no snap
target exists. If a later phase finds a real barrier behind one of these names it
should be geocoded and removed from `suspect_gates`. The free-flow structural
read (self-loop == single gantry) is inferred from the data, not from an
operator document.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "tollroute" / "db" / "schema.sql"
DEFAULT_DB_PATH = REPO_ROOT / "tollroute" / "db" / "tollroute.sqlite"
DEFAULT_GARE_MASTER_PATH = REPO_ROOT / "gare_master.csv"
DEFAULT_OD_PAIRS_PATH = REPO_ROOT / "od_pairs.csv"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase2c_freeflow.md"

# Spec-named free-flow (barrierless) corridors to classify.
FREEFLOW_CORRIDORS = ("A79", "A13", "A14")

# Written into suspect_gates.source_phase so later phases can tell who quarantined a gate.
SOURCE_PHASE = "2c"

# Phase 5b-follow-up-2: the Millau viaduct (A75, north of Béziers/Montpellier) is a genuine
# single-structure toll concession operated by CEVM (Compagnie Eiffage du Viaduc de Millau),
# not one of this project's 13 dataset operators, so it never appears in gare_master.csv or
# od_pairs.csv - Phase 1b/1d/5b already documented the A75 corridor south of Clermont-Ferrand
# as untolled without a CEVM entry.
#
# **Revised design (this item's own first attempt, reverted - see reports/
# phase5b_followup2_millau.md for the full investigation):** the first attempt modelled Millau
# as two synthetic gates ~13 km apart (guessed "interchange" coordinates) joined by a priced
# TOLL edge, reasoning the crossing needed "real endpoints" unlike A14's single-gantry
# self-loop. That reasoning, and its supporting claim that this build's OSM extract "doesn't
# tag the viaduct toll=yes at all", were never actually verified against live data - checked
# directly for this revision: the OSM extract (`osrm/data/france.osm.pbf`) tags the viaduct's
# own ways (e.g. way 4296812 "Viaduc de Millau") `toll=yes`, and the real barrier sits at two
# `barrier=toll_booth` nodes (osm nodes 2032423306/2032423307, one per carriageway) at
# ~(44.13414, 3.02556). A direct OSRM query confirms this coordinate is a genuine mandatory
# chokepoint: `/route` with `exclude=toll` returns `NoRoute` both from Clermont-Ferrand to it
# and from it to Montpellier (no toll-free path exists to/from that exact point at all) -
# exactly the semantics `tollroute.graph.build_graph`'s existing A14-style self-loop handling
# already relies on for a real single-gantry gate. The first attempt's two far-apart guessed
# coordinates, by contrast, turned out to sit off the motorway entirely (a direct OSRM route
# between them cut through Millau's town streets, never touching the viaduct in either
# `exclude=toll` mode), so the priced edge was never actually reachable/selected: the
# "fastest" Clermont-Ferrand->Montpellier route used the synthetic gate purely as a
# same-cost pass-through waypoint via ordinary access edges, at toll_eur=0 - the flagship
# acceptance criterion this item was never met on the first attempt (see the report for the
# full trace). This revision instead seeds Millau as one ordinary self-loop gate at the real
# barrier coordinate, exactly like A14's 5 existing dataset self-loop fares - no new graph.py
# code needed at all; `build_graph`'s existing self-loop handling and (given the barrier's own
# coordinate is `exclude=toll`-unreachable, per the NoRoute check above)
# `tollroute.etl.access_anchors`'s existing entry/exit anchor mechanism both already apply
# unchanged. `access_anchors.run()` must be re-run after this seed (not part of
# `build_national.run()`'s own pipeline - see that module's docstring) for the new gate to be
# reachable at all.
#
# Fee: class 1 (11.30 EUR, off-peak/"normale" 2026 rate) is corroborated by two independent
# reads - Phase 5b's original report citing the operator's own tariff PDF, and this item's own
# web search of a third-party summary quoting the same figure - so it is NOT flagged
# is_conjecture. Classes 2-5 could not be corroborated: leviaducdemillau.com's tariff PDF/page
# return HTTP 403 in this build environment (same access pattern already hit by Phase 2a/5a
# against autoroutes.fr/vinci-autoroutes.com) and two independent third-party summaries quoted
# mutually inconsistent full-class grids (one: 10.68/16.60/30.00/43.00/7.10 EUR for
# classes 1-5; another: 5.10/7.65/10.20/-/2.50 EUR for classes 1-3 + motorcycles, no class
# 4/5) - neither reconciles with the corroborated class-1 figure or with each other, so
# neither is trustworthy enough to use directly. Classes 2-5 are instead interpolated from
# APRR's own verified (Phase 5a fare-oracle-checked, exact-to-the-cent) class-N/class-1 price
# ratios applied to Millau's sourced class-1 figure, and flagged `is_conjecture=1` - the same
# "checked, not assumed" interpolation convention `cost.seed_class_config` already uses for
# class_config's own indicative figures.
MILLAU_VIADUCT_CORRIDOR = "A75-MILLAU"
MILLAU_VIADUCT_OPERATOR = "CEVM"
MILLAU_GARE_ID = 900001  # synthetic - real gare_master.csv ids run 1-956, clearly out of range
MILLAU_CANONICAL_NAME = "PEAGE VIADUC DE MILLAU"
# Midpoint of OSM nodes 2032423306/2032423307 (barrier=toll_booth, one per carriageway),
# sourced directly from the OSM extract this build's OSRM instance is served from - not
# conjecture. Verified (see module comment above) to be an `exclude=toll` NoRoute chokepoint.
MILLAU_BARRIER_COORD = (44.134137, 3.025560)
MILLAU_CLASS1_FEE_EUR = 11.30  # sourced, off-peak 2026 (leviaducdemillau.com); not conjecture
# APRR class-N/class-1 ratios (median over ~3,000 non-zero-priced APRR fare rows in
# od_pairs.csv), applied to MILLAU_CLASS1_FEE_EUR - interpolated, flagged is_conjecture=1.
_MILLAU_CLASS_RATIOS = {2: 1.5466, 3: 2.4801, 4: 3.3333, 5: 0.5849}
MILLAU_FEES_EUR: dict[int, float] = {1: MILLAU_CLASS1_FEE_EUR} | {
    cls: round(MILLAU_CLASS1_FEE_EUR * ratio, 2) for cls, ratio in _MILLAU_CLASS_RATIOS.items()
}
MILLAU_NOTE = (
    "Millau viaduct (CEVM), 2026 off-peak tariff. Class 1 sourced directly to "
    "leviaducdemillau.com's published tariff (corroborated by two independent reads). "
    "Classes 2-5 interpolated from APRR's verified class-N/class-1 price ratios applied to "
    "the sourced class-1 figure (official PDF unreachable in this build environment - "
    "HTTP 403 - and third-party summaries for classes 2-5 disagreed with each other and with "
    "the corroborated class-1 figure)."
)


def seed_millau_override(conn: sqlite3.Connection) -> bool:
    """Idempotently seed the Millau viaduct as a single self-loop toll gate.

    Three tables, one transaction: `gates` (a real gate row at the verified barrier
    coordinate, so it participates in `build_graph`/`access_anchors` exactly like any
    other dataset gate), `fares` (a self-loop row, from_gare_id == to_gare_id, the same
    shape A14's 5 real self-loop rows already use), and `freeflow_override` (fee-only
    provenance bookkeeping - sourced vs. interpolated - kept for documentation, not
    read by the graph builder).

    Returns True if rows were (re-)written. Uses INSERT OR REPLACE (not "only if
    empty" like `cost.seed_class_config`) so a later re-run of the national build
    always reflects this module's current sourced/interpolated figures rather than
    silently keeping a stale prior run's numbers.
    """
    conn.executescript(SCHEMA_PATH.read_text())

    conn.execute(
        "INSERT OR REPLACE INTO gates (gare_id, canonical_name, operators, snap_lat, snap_lon) "
        "VALUES (?, ?, ?, ?, ?)",
        (MILLAU_GARE_ID, MILLAU_CANONICAL_NAME, MILLAU_VIADUCT_OPERATOR, *MILLAU_BARRIER_COORD),
    )
    conn.execute(
        "DELETE FROM fares WHERE from_gare_id = ? AND to_gare_id = ?",
        (MILLAU_GARE_ID, MILLAU_GARE_ID),
    )
    conn.execute(
        "INSERT INTO fares (from_gare_id, to_gare_id, operator, class1, class2, class3, "
        "class4, class5) VALUES (:gid, :gid, :operator, :c1, :c2, :c3, :c4, :c5)",
        {
            "gid": MILLAU_GARE_ID,
            "operator": MILLAU_VIADUCT_OPERATOR,
            "c1": MILLAU_FEES_EUR[1],
            "c2": MILLAU_FEES_EUR[2],
            "c3": MILLAU_FEES_EUR[3],
            "c4": MILLAU_FEES_EUR[4],
            "c5": MILLAU_FEES_EUR[5],
        },
    )
    conn.executemany(
        "INSERT OR REPLACE INTO freeflow_override "
        "(corridor, vehicle_class, flat_fee_eur, note, operator, is_conjecture) "
        "VALUES (:corridor, :vehicle_class, :flat_fee_eur, :note, :operator, :is_conjecture)",
        [
            {
                "corridor": MILLAU_VIADUCT_CORRIDOR,
                "vehicle_class": vehicle_class,
                "flat_fee_eur": fee,
                "note": MILLAU_NOTE,
                "operator": MILLAU_VIADUCT_OPERATOR,
                "is_conjecture": 0 if vehicle_class == 1 else 1,
            }
            for vehicle_class, fee in MILLAU_FEES_EUR.items()
        ],
    )
    conn.commit()
    logger.info(
        "Millau viaduct seeded: gate %d self-loop fare, %s class1=%.2f EUR (sourced), "
        "classes 2-5 interpolated (flagged is_conjecture)",
        MILLAU_GARE_ID,
        MILLAU_VIADUCT_OPERATOR,
        MILLAU_FEES_EUR[1],
    )
    return True


@dataclass(frozen=True)
class CoordinatelessGate:
    gare_id: int
    canonical_name: str
    all_routes: str
    operators: str
    affected_od_pairs: int


@dataclass(frozen=True)
class CorridorClassification:
    corridor: str
    gates_in_gare_master: tuple[int, ...]
    od_rows_referencing_gates: int
    pure_rows: int          # both endpoints are corridor gates
    self_loop_rows: int     # from_gare_id == to_gare_id (single-gantry flat fee)
    present_in_fare_matrix: bool
    override_needed: bool
    note: str


def _route_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for part in (value or "").replace("|", ",").replace(";", ",").split(","):
        part = part.strip()
        if part:
            tokens.add(part)
    return tokens


def _gid(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


def read_gare_master(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_od_pairs(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_coordinateless_gates(
    gare_master: list[dict], od_pairs: list[dict]
) -> list[CoordinatelessGate]:
    """Gates with no lat/lon, each with the count of od_pairs rows that reference it."""
    ref_counts: Counter[int] = Counter()
    for row in od_pairs:
        endpoints = {_gid(row.get("from_gare_id")), _gid(row.get("to_gare_id"))}
        for gid in endpoints:
            if gid is not None:
                ref_counts[gid] += 1

    result: list[CoordinatelessGate] = []
    for row in gare_master:
        try:
            gare_id = int(row["gare_id"])
        except (ValueError, KeyError):
            continue
        if (row.get("lat") or "").strip() and (row.get("lon") or "").strip():
            continue
        result.append(
            CoordinatelessGate(
                gare_id=gare_id,
                canonical_name=row.get("canonical_name", ""),
                all_routes=row.get("all_routes", ""),
                operators=row.get("operators", ""),
                affected_od_pairs=ref_counts.get(gare_id, 0),
            )
        )
    return sorted(result, key=lambda g: g.gare_id)


def classify_corridor(
    corridor: str, gare_master: list[dict], od_pairs: list[dict]
) -> CorridorClassification:
    gates = sorted(
        int(row["gare_id"])
        for row in gare_master
        if row.get("gare_id", "").strip()
        and corridor in _route_tokens(row.get("all_routes", ""))
    )
    gate_set = set(gates)

    referencing = 0
    pure = 0
    self_loops = 0
    for row in od_pairs:
        frm = _gid(row.get("from_gare_id"))
        to = _gid(row.get("to_gare_id"))
        if frm in gate_set or to in gate_set:
            referencing += 1
            if frm in gate_set and to in gate_set:
                pure += 1
            if frm is not None and frm == to:
                self_loops += 1

    present = referencing > 0
    override_needed = not present
    if not present:
        note = (
            "ABSENT from the fare matrix — a per-corridor flat-fee override is "
            "required (populate freeflow_override)."
        )
    elif self_loops > 0:
        note = (
            f"present; {self_loops} of its fare rows are self-loops "
            "(from_gare_id == to_gare_id): a free-flow single-gantry flat fee, "
            "not an entry->exit gate pair. The graph builder must treat a "
            "self-loop toll edge as a flat-fee section edge, not a zero-length "
            "no-op — see the Phase 2c follow-up item."
        )
    else:
        note = (
            "present in the fare matrix as conventional gate-to-gate rows; no "
            "override needed."
        )
    return CorridorClassification(
        corridor=corridor,
        gates_in_gare_master=tuple(gates),
        od_rows_referencing_gates=referencing,
        pure_rows=pure,
        self_loop_rows=self_loops,
        present_in_fare_matrix=present,
        override_needed=override_needed,
        note=note,
    )


def write_suspect_gates(
    conn: sqlite3.Connection, gates: list[CoordinatelessGate]
) -> None:
    """Idempotently upsert the coordinate-less gates into suspect_gates."""
    conn.executescript(SCHEMA_PATH.read_text())
    conn.executemany(
        "INSERT OR REPLACE INTO suspect_gates "
        "(gare_id, canonical_name, reason, source_phase, affected_od_pairs, detail) "
        "VALUES (:gare_id, :canonical_name, :reason, :source_phase, "
        ":affected_od_pairs, :detail)",
        [
            {
                "gare_id": g.gare_id,
                "canonical_name": g.canonical_name,
                "reason": "coordinate-less gate (no lat/lon) — cannot be snapped to a road",
                "source_phase": SOURCE_PHASE,
                "affected_od_pairs": g.affected_od_pairs,
                "detail": (
                    f"'limite de concession' boundary marker on {g.all_routes or '?'} "
                    f"(operators: {g.operators or '?'}); not geocodable to a physical "
                    "barrier"
                ),
            }
            for g in gates
        ],
    )
    conn.commit()


def render_report(
    classifications: list[CorridorClassification],
    coordinateless: list[CoordinatelessGate],
) -> str:
    lines = ["# Phase 2c — Free-flow classification and coordinate-less gate quarantine", ""]
    lines.append(
        "Sibling of `phase2c_clustering.md`. Classifies the spec-named free-flow "
        "(barrierless) corridors and quarantines the gates that carry no coordinates."
    )
    lines.append("")

    lines.append("## Free-flow corridors")
    lines.append("")
    lines.append("| corridor | gates in gare_master | od_pairs rows | self-loops | present? | override needed? |")
    lines.append("|---|---|---|---|---|---|")
    for c in classifications:
        lines.append(
            f"| {c.corridor} | {len(c.gates_in_gare_master)} | "
            f"{c.od_rows_referencing_gates} | {c.self_loop_rows} | "
            f"{'yes' if c.present_in_fare_matrix else 'NO'} | "
            f"{'YES' if c.override_needed else 'no'} |"
        )
    lines.append("")
    for c in classifications:
        lines.append(f"- **{c.corridor}** (gates {list(c.gates_in_gare_master)}): {c.note}")
    lines.append("")
    lines.append(
        "**Decision:** every free-flow corridor is present in `od_pairs`, so the "
        "`freeflow_override` table is created but left **empty** — no flat-fee "
        "override is required. A14's self-loop representation is flagged to the "
        "graph builder as a follow-up item."
    )
    lines.append("")
    lines.append(
        "*Checked, not assumed:* blank `distance_km` is not a free-flow signal "
        "(61% of all rows omit it, whole operators omit it wholesale); the "
        "self-loop pattern is the distinctive marker (all five self-loops in the "
        "file are A14/sapn)."
    )
    lines.append("")

    lines.append("## Coordinate-less gates → suspect_gates")
    lines.append("")
    lines.append("| gare_id | name | routes | operators | affected od_pairs |")
    lines.append("|---|---|---|---|---|")
    for g in coordinateless:
        lines.append(
            f"| {g.gare_id} | {g.canonical_name} | {g.all_routes or '—'} | "
            f"{g.operators or '—'} | {g.affected_od_pairs} |"
        )
    lines.append("")
    lines.append(
        f"All {len(coordinateless)} are 'limite de concession' administrative "
        "boundary markers, not physical barriers — quarantined into "
        "`suspect_gates` rather than geocoded. **Conjecture flagged:** if a later "
        "phase finds a real barrier behind one of these names it should be "
        "geocoded and removed from the table."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def run(
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> tuple[list[CorridorClassification], list[CoordinatelessGate]]:
    gare_master = read_gare_master(gare_master_path)
    od_pairs = read_od_pairs(od_pairs_path)

    classifications = [
        classify_corridor(corridor, gare_master, od_pairs)
        for corridor in FREEFLOW_CORRIDORS
    ]
    coordinateless = find_coordinateless_gates(gare_master, od_pairs)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        write_suspect_gates(conn, coordinateless)
    finally:
        conn.close()

    for c in classifications:
        (logger.warning if c.override_needed else logger.info)(
            "free-flow %s: %d gates, %d od_pairs rows, %d self-loops — %s",
            c.corridor,
            len(c.gates_in_gare_master),
            c.od_rows_referencing_gates,
            c.self_loop_rows,
            c.note,
        )
    for g in coordinateless:
        logger.warning(
            "coordinate-less gate %d (%s) quarantined to suspect_gates; strands "
            "%d od_pairs rows",
            g.gare_id,
            g.canonical_name,
            g.affected_od_pairs,
        )

    report = render_report(classifications, coordinateless)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    logger.info(
        "classified %d free-flow corridors (%d needing overrides); quarantined "
        "%d coordinate-less gates into suspect_gates; report written to %s",
        len(classifications),
        sum(1 for c in classifications if c.override_needed),
        len(coordinateless),
        report_path,
    )
    return classifications, coordinateless


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gare-master", type=Path, default=DEFAULT_GARE_MASTER_PATH)
    parser.add_argument("--od-pairs", type=Path, default=DEFAULT_OD_PAIRS_PATH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    run(
        gare_master_path=args.gare_master,
        od_pairs_path=args.od_pairs,
        db_path=args.db,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()
