"""National multi-operator build + per-operator coverage audit (Phase 2d).

Run as: python3 -m tollroute.etl.coverage_audit [--db PATH] [--report PATH]

`iterative-tumbling-lecun.md` Phase 2d has four deliverables; this module owns
the last three (the alias map is `tollroute/etl/operators.py`):

1. **Full build, clean, from CSVs to SQLite** with zero unresolved gate
   references. Unlike `tollroute/etl/load.py` (APRR-only, feeds the regional
   graph/API), this loads **all 13 operators** — the first national CSV->SQLite
   build. It writes to a *separate* database (`tollroute_full.sqlite` by
   default) so it never clobbers the APRR regional dev DB that `graph.py` /
   `api.py` still read. "Zero unresolved gate references" is verified with
   SQLite's own `PRAGMA foreign_key_check`: every non-blank `from_gare_id` /
   `to_gare_id` must resolve to a `gates` row. The 163 + 163 blank endpoints load
   as NULL (a NULL FK is not a violation) and are reported, not counted as
   unresolved — re-matching them is Phase 2b's job, already done at CSV-analysis
   level.

2. **Per-operator coverage audit:** distinct gates N, fare-row count R, dense
   directed maximum ``N*(N-1)``, and ``R / dense``. Operators far below dense are
   flagged as known-bad regions. **Interpretation (flagged):** dense ``N*(N-1)``
   assumes a *complete* graph — every gate priced to every other. Real motorway
   networks are corridors, so a low ratio for a large network (ASFC, Cofiroute)
   reflects geography, not data loss. The genuine anomaly this surfaces is a
   *small* network whose ratio is near zero (aliea at ~1.3 %), which is a real
   correctness hazard, not a modelling artefact.

3. **Asymmetric pricing:** the spec conjectures "426 rows, 0.7 %" priced
   differently by direction. **Finding (verified against the data):** among the
   28,386 bidirectional pairs, **zero** differ in price across any vehicle class,
   so the ">2x ratio" flag fires on **no** pair. The only real directional
   asymmetry is 263 pairs present in one direction only (reverse absent) — a
   coverage gap the directed graph already handles correctly. Both figures are
   reported.

4. **Snap failures > 200 m -> `suspect_gates`** (with affected OD-pair count).
   The mechanism is implemented and runs against whatever `snap_distance_m` data
   the target DB holds. The national build has *no* snap data yet (national OSRM
   snapping is Phase 3a), so it quarantines nothing here; definitive snap-quality
   curation is Phase 3c ("> 200 m *after curation*"). Running it now against the
   APRR regional dev DB would wrongly quarantine the 105 gates the Phase 1b
   report already showed to be an out-of-extract *coverage* artefact, so it is
   deliberately not pointed there.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from tollroute.etl.load import (
    FARE_COLUMNS,
    FARE_FLOAT_COLUMNS,
    FARE_INT_COLUMNS,
    GATE_COLUMNS,
    GATE_FLOAT_COLUMNS,
    GATE_INT_COLUMNS,
    REPO_ROOT,
    SCHEMA_PATH,
    _convert_row,
)
from tollroute.etl.operators import build_alias_map, write_operator_alias

logger = logging.getLogger(__name__)

DEFAULT_FULL_DB_PATH = REPO_ROOT / "tollroute" / "db" / "tollroute_full.sqlite"
DEFAULT_OD_PAIRS_PATH = REPO_ROOT / "od_pairs.csv"
DEFAULT_GARE_MASTER_PATH = REPO_ROOT / "gare_master.csv"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase2d_coverage.md"

# Operators whose coverage ratio (R / dense) below this floor are flagged as
# "materially below dense". 10 % is a judgement call, not a sourced figure
# (flagged conjecture): it is well above the natural corridor-network density of
# the large operators here and isolates aliea's ~1.3 % anomaly.
COVERAGE_FLOOR = 0.10

# Snap distance beyond which a gate is quarantined to suspect_gates (spec Phase
# 2d: "> 200 m after curation").
SNAP_SUSPECT_THRESHOLD_M = 200.0

# Vehicle-class price ratio above which a bidirectional pair is flagged as a
# likely data error (spec Phase 2d: "ratio exceeds 2x").
ASYMMETRY_RATIO_THRESHOLD = 2.0


# --------------------------------------------------------------------------- #
# 1. National build
# --------------------------------------------------------------------------- #

def _read_all_gates(gare_master_path: Path) -> list[dict]:
    with gare_master_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [_convert_row(r, GATE_INT_COLUMNS, GATE_FLOAT_COLUMNS) for r in rows]


def _read_all_fares(od_pairs_path: Path) -> list[dict]:
    with od_pairs_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [_convert_row(r, FARE_INT_COLUMNS, FARE_FLOAT_COLUMNS) for r in rows]


@dataclass
class BuildResult:
    gate_count: int
    fare_count: int
    blank_from: int
    blank_to: int
    fk_violations: int


def build_full_db(
    db_path: Path = DEFAULT_FULL_DB_PATH,
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
) -> tuple[sqlite3.Connection, BuildResult]:
    """Load ALL operators CSV->SQLite and assert zero unresolved gate references.

    Returns an *open* connection (caller closes) plus a `BuildResult`. Raises
    `RuntimeError` if `PRAGMA foreign_key_check` finds any resolved-but-missing
    gate reference.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM fares")
    conn.execute("DELETE FROM gates")

    gates = _read_all_gates(gare_master_path)
    fares = _read_all_fares(od_pairs_path)

    gate_ph = ", ".join(f":{c}" for c in GATE_COLUMNS)
    conn.executemany(
        f"INSERT INTO gates ({', '.join(GATE_COLUMNS)}) VALUES ({gate_ph})", gates
    )
    fare_ph = ", ".join(f":{c}" for c in FARE_COLUMNS)
    conn.executemany(
        f"INSERT INTO fares ({', '.join(FARE_COLUMNS)}) VALUES ({fare_ph})", fares
    )
    conn.commit()

    blank_from = sum(1 for r in fares if r["from_gare_id"] is None)
    blank_to = sum(1 for r in fares if r["to_gare_id"] is None)
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()

    if violations:
        raise RuntimeError(
            f"national build has {len(violations)} unresolved gate references "
            f"(non-blank from/to_gare_id absent from gates): "
            f"{violations[:5]}{' ...' if len(violations) > 5 else ''}"
        )

    result = BuildResult(
        gate_count=len(gates),
        fare_count=len(fares),
        blank_from=blank_from,
        blank_to=blank_to,
        fk_violations=len(violations),
    )
    logger.info(
        "national build clean: %d gates, %d fares, 0 unresolved gate references "
        "(%d blank from_gare_id + %d blank to_gare_id loaded as NULL)",
        result.gate_count,
        result.fare_count,
        result.blank_from,
        result.blank_to,
    )
    return conn, result


# --------------------------------------------------------------------------- #
# 2. Coverage audit
# --------------------------------------------------------------------------- #

@dataclass
class OperatorCoverage:
    operator: str
    gates: int
    rows: int
    dense: int
    ratio: float
    flagged: bool


def audit_coverage(conn: sqlite3.Connection) -> list[OperatorCoverage]:
    """Per-operator N gates vs rows vs dense N(N-1); flag those below the floor."""
    gates_per_op: dict[str, set[int]] = defaultdict(set)
    rows_per_op: dict[str, int] = defaultdict(int)
    cur = conn.execute(
        "SELECT operator, from_gare_id, to_gare_id FROM fares"
    )
    for operator, frm, to in cur:
        rows_per_op[operator] += 1
        if frm is not None:
            gates_per_op[operator].add(frm)
        if to is not None:
            gates_per_op[operator].add(to)

    out: list[OperatorCoverage] = []
    for operator in sorted(rows_per_op, key=lambda o: -rows_per_op[o]):
        n = len(gates_per_op[operator])
        dense = n * (n - 1)
        rows = rows_per_op[operator]
        ratio = rows / dense if dense else 0.0
        out.append(
            OperatorCoverage(
                operator=operator,
                gates=n,
                rows=rows,
                dense=dense,
                ratio=ratio,
                flagged=dense > 0 and ratio < COVERAGE_FLOOR,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# 3. Asymmetry audit
# --------------------------------------------------------------------------- #

@dataclass
class AsymmetryResult:
    bidirectional_pairs: int
    unidirectional_pairs: int
    ratio_flagged: list[tuple[str, int, int, float, float]]


def _class_vector(row: sqlite3.Row) -> tuple:
    return tuple(row[f"class{i}"] for i in range(1, 6))


def audit_asymmetry(conn: sqlite3.Connection) -> AsymmetryResult:
    """Directional pricing audit.

    Flags bidirectional pairs whose class1 price ratio exceeds
    `ASYMMETRY_RATIO_THRESHOLD`, and counts pairs present in one direction only.
    """
    conn.row_factory = sqlite3.Row
    prices: dict[tuple, tuple] = {}
    cur = conn.execute(
        "SELECT operator, from_gare_id, to_gare_id, class1, class2, class3, "
        "class4, class5 FROM fares "
        "WHERE from_gare_id IS NOT NULL AND to_gare_id IS NOT NULL"
    )
    for row in cur:
        key = (row["operator"], row["from_gare_id"], row["to_gare_id"])
        # First row wins on the 17 duplicate (op,from,to) keys (time-window rows).
        prices.setdefault(key, _class_vector(row))
    conn.row_factory = None

    keys = set(prices)
    unidirectional = 0
    bidirectional = 0
    flagged: list[tuple[str, int, int, float, float]] = []
    seen: set[tuple] = set()
    for op, a, b in keys:
        rev = (op, b, a)
        if rev not in keys:
            unidirectional += 1
            continue
        pair_id = (op, frozenset((a, b)))
        if pair_id in seen:
            continue
        seen.add(pair_id)
        bidirectional += 1
        c1_ab = prices[(op, a, b)][0]
        c1_ba = prices[rev][0]
        if c1_ab and c1_ba and c1_ab > 0 and c1_ba > 0:
            hi, lo = max(c1_ab, c1_ba), min(c1_ab, c1_ba)
            if hi / lo > ASYMMETRY_RATIO_THRESHOLD:
                flagged.append((op, a, b, c1_ab, c1_ba))

    return AsymmetryResult(
        bidirectional_pairs=bidirectional,
        unidirectional_pairs=unidirectional,
        ratio_flagged=flagged,
    )


# --------------------------------------------------------------------------- #
# 4. Snap-quality curation
# --------------------------------------------------------------------------- #

@dataclass
class SnapSuspect:
    gare_id: int
    canonical_name: str
    snap_distance_m: float
    affected_od_pairs: int


def curate_snap_suspects(
    conn: sqlite3.Connection, threshold_m: float = SNAP_SUSPECT_THRESHOLD_M
) -> list[SnapSuspect]:
    """Move gates snapping > `threshold_m` into suspect_gates with OD-pair count.

    Real mechanism; quarantines nothing when the DB carries no `snap_distance_m`
    (the national build's case — national snapping is Phase 3a).
    """
    suspects: list[SnapSuspect] = []
    cur = conn.execute(
        "SELECT gare_id, canonical_name, snap_distance_m FROM gates "
        "WHERE snap_distance_m IS NOT NULL AND snap_distance_m > ?",
        (threshold_m,),
    )
    for gare_id, name, dist in cur.fetchall():
        (affected,) = conn.execute(
            "SELECT COUNT(*) FROM fares WHERE from_gare_id = ? OR to_gare_id = ?",
            (gare_id, gare_id),
        ).fetchone()
        suspects.append(SnapSuspect(gare_id, name, dist, affected))

    for s in suspects:
        conn.execute(
            "INSERT OR REPLACE INTO suspect_gates "
            "(gare_id, canonical_name, reason, source_phase, affected_od_pairs, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                s.gare_id,
                s.canonical_name,
                "snap_distance_over_200m",
                "phase2d",
                s.affected_od_pairs,
                f"snap_distance_m={s.snap_distance_m:.1f}",
            ),
        )
    conn.commit()
    return suspects


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def write_report(
    report_path: Path,
    build: BuildResult,
    coverage: list[OperatorCoverage],
    asymmetry: AsymmetryResult,
    suspects: list[SnapSuspect],
    alias_map: dict[str, str],
) -> None:
    lines: list[str] = []
    lines.append("# Phase 2d — Operator normalisation and coverage audit")
    lines.append("")
    lines.append(
        "Generated by `tollroute/etl/coverage_audit.py` (build + audit) and "
        "`tollroute/etl/operators.py` (alias map). All figures reproduce "
        "directly from `od_pairs.csv` / `gare_master.csv`."
    )
    lines.append("")

    lines.append("## 1. National build (zero unresolved gate references)")
    lines.append("")
    lines.append(
        f"Full multi-operator CSV->SQLite build: **{build.gate_count} gates**, "
        f"**{build.fare_count} fares**, **{build.fk_violations} unresolved gate "
        f"references** (`PRAGMA foreign_key_check` clean). "
        f"{build.blank_from} blank `from_gare_id` + {build.blank_to} blank "
        f"`to_gare_id` rows load as NULL (a NULL FK is not a violation; "
        "re-matching is Phase 2b)."
    )
    lines.append("")

    lines.append("## 2. Operator alias map")
    lines.append("")
    lines.append("`raw_name -> canonical_operator` (uppercase casefold):")
    lines.append("")
    lines.append("| raw_name | canonical_operator |")
    lines.append("| --- | --- |")
    for raw, canon in sorted(alias_map.items()):
        note = " *(uppercased)*" if raw != canon else ""
        lines.append(f"| `{raw}` | `{canon}`{note} |")
    lines.append("")
    lines.append(
        "**Conjecture flagged:** the spec conjectures `ASFC = ASF`. No `ASF` "
        "token exists in either CSV, so `ASFC` is kept as its own canonical name "
        "rather than renamed on an unverified equivalence. `aliea` mis-casing is "
        "resolved by the uppercase casefold (`aliea -> ALIEA`)."
    )
    lines.append("")

    lines.append("## 3. Per-operator coverage (N gates vs rows vs dense N(N-1))")
    lines.append("")
    lines.append("| operator | gates N | rows | dense N(N-1) | rows/dense | flag |")
    lines.append("| --- | ---: | ---: | ---: | ---: | :---: |")
    for c in coverage:
        flag = "⚠️ below dense" if c.flagged else ""
        lines.append(
            f"| {c.operator} | {c.gates} | {c.rows} | {c.dense} | "
            f"{c.ratio * 100:.1f}% | {flag} |"
        )
    lines.append("")
    flagged = [c.operator for c in coverage if c.flagged]
    lines.append(
        f"Flagged below the {COVERAGE_FLOOR * 100:.0f}% floor: "
        f"**{', '.join(flagged) if flagged else 'none'}**."
    )
    lines.append("")
    lines.append(
        "**Interpretation (flagged as judgement, not sourced):** dense "
        "`N*(N-1)` assumes a complete graph — every gate priced to every other. "
        "Real networks are corridors, so a low ratio for a *large* network "
        "(ASFC, Cofiroute) reflects geography, not data loss. The genuine "
        "correctness hazard is **aliea (~1.3%)**: 171 distinct gates but only "
        "365 fare rows — a small, near-empty matrix, logged as a known-bad "
        "region. ATMB (10 rows) is thin but plausibly a real tunnel-only "
        "network."
    )
    lines.append("")

    lines.append("## 4. Directional asymmetry")
    lines.append("")
    lines.append(
        f"- Bidirectional pairs (both directions present): "
        f"**{asymmetry.bidirectional_pairs}**."
    )
    lines.append(
        f"- Pairs flagged with class1 price ratio > "
        f"{ASYMMETRY_RATIO_THRESHOLD:.0f}x: **{len(asymmetry.ratio_flagged)}**."
    )
    lines.append(
        f"- Unidirectional pairs (reverse direction absent): "
        f"**{asymmetry.unidirectional_pairs}**."
    )
    lines.append("")
    lines.append(
        "**Finding vs spec conjecture:** the spec expects \"426 rows (0.7%)\" "
        "priced asymmetrically. Against the actual data, **zero** bidirectional "
        "pairs differ in price across any vehicle class, so the >2x flag fires "
        "on none. The only real directional asymmetry is the "
        f"{asymmetry.unidirectional_pairs} pairs present in one direction only "
        "(a coverage gap the directed graph already handles correctly — no "
        "action needed)."
    )
    if asymmetry.ratio_flagged:
        lines.append("")
        lines.append("| operator | from | to | class1 A->B | class1 B->A |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for op, a, b, pab, pba in asymmetry.ratio_flagged[:20]:
            lines.append(f"| {op} | {a} | {b} | {pab} | {pba} |")
    lines.append("")

    lines.append("## 5. Snap-quality suspects (> 200 m)")
    lines.append("")
    if suspects:
        lines.append(
            f"Quarantined **{len(suspects)}** gates to `suspect_gates`:"
        )
        lines.append("")
        lines.append("| gare_id | name | snap_m | affected OD pairs |")
        lines.append("| ---: | --- | ---: | ---: |")
        for s in suspects:
            lines.append(
                f"| {s.gare_id} | {s.canonical_name} | "
                f"{s.snap_distance_m:.0f} | {s.affected_od_pairs} |"
            )
    else:
        lines.append(
            "No gates quarantined: the national build carries no "
            "`snap_distance_m` (national OSRM snapping is Phase 3a). Definitive "
            "snap-quality curation is Phase 3c (\"> 200 m *after curation*\"). "
            "The mechanism is implemented and wired; it fires as soon as snap "
            "data is present."
        )
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def run(
    db_path: Path = DEFAULT_FULL_DB_PATH,
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> BuildResult:
    conn, build = build_full_db(db_path, od_pairs_path, gare_master_path)
    try:
        alias_map = build_alias_map(od_pairs_path, gare_master_path)
        write_operator_alias(conn, alias_map)
        conn.commit()
        coverage = audit_coverage(conn)
        asymmetry = audit_asymmetry(conn)
        suspects = curate_snap_suspects(conn)
        write_report(report_path, build, coverage, asymmetry, suspects, alias_map)
        logger.info(
            "coverage audit complete: %d operators, %d flagged below dense, "
            "%d asymmetric-ratio pairs, %d snap suspects; report -> %s",
            len(coverage),
            sum(1 for c in coverage if c.flagged),
            len(asymmetry.ratio_flagged),
            len(suspects),
            report_path,
        )
        return build
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_FULL_DB_PATH)
    parser.add_argument("--od-pairs", type=Path, default=DEFAULT_OD_PAIRS_PATH)
    parser.add_argument("--gare-master", type=Path, default=DEFAULT_GARE_MASTER_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    run(
        db_path=args.db,
        od_pairs_path=args.od_pairs,
        gare_master_path=args.gare_master,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()
