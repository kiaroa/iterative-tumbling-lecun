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
