"""Assign a typed disposition to every zero-price od_pairs.csv row (Phase 2b).

Run as: python3 -m tollroute.etl.remediate_zero_price

Scope: all 551 `class1 == 0` rows across every operator in `od_pairs.csv`, not
just the APRR subset the rest of `tollroute` currently loads (`etl/load.py`
already logs its 8 APRR zero-price rows rather than dropping them, deferring
the actual disposition to this module, per its own docstring). Reads the CSVs
directly rather than SQLite, since the live database is APRR-only.

A zero fare has no natural interpretation as a Dijkstra edge weight: treating
it as a real "free" toll edge can silently open a wormhole, but discarding the
row loses genuine free/open-section connectivity if it is one. Each row is
classified into exactly one of three named dispositions, in priority order:

1. ``free_transfer`` - the two gates carry different operator tags in
   `gare_master.csv` (a genuine network-boundary signal) AND are physically
   close. This is a same-network zero-price row that plausibly represents a
   short cross-operator hand-off.
2. ``free_section`` - either endpoint's name marks it as a non-toll structural
   node (a "Bifurcation" interchange, never a priced barrier), OR the two
   gates are physically close regardless of naming (adjacent-junction /
   dense urban ring-road style hops, e.g. observed on ASFC's Toulouse
   rocade cluster).
3. ``drop`` - none of the above signals fire. There is no positive evidence
   the zero price is real rather than missing/unrecorded data, and keeping it
   as a routable free edge over tens of km is the dangerous failure mode, so
   the row is excluded from the graph and logged.

**Conjecture flagged explicitly:** the 8 km proximity threshold and the
"bifurcation" keyword are both judgement calls fitted to the patterns visible
in this dataset (see `reports/phase2b_zero_price.md` for the worked
examples/histograms that motivated them: APRR's 8 known-legitimate short
free-bypass rows top out at 6.57 km; Landes/Alicorne's zero-price rows run up
to 78 km with no structural signal and are exactly the case the `drop` rule
exists for). Neither threshold is sourced from an authoritative document —
Phase 2d's per-operator coverage audit and Phase 3c's national distance-error
validation are the places a wrong call here would surface and get corrected.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OD_PAIRS_PATH = REPO_ROOT / "od_pairs.csv"
DEFAULT_GARE_MASTER_PATH = REPO_ROOT / "gare_master.csv"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase2b_zero_price.md"

# Conjecture (see module docstring): both thresholds are pattern-fitted, not
# sourced from an authoritative document.
PROXIMITY_MAX_KM = 8.0
STRUCTURAL_NAME_KEYWORDS = ("bifurcation",)


class Disposition(str, Enum):
    FREE_TRANSFER = "free_transfer"
    FREE_SECTION = "free_section"
    DROP = "drop"


@dataclass(frozen=True)
class GateInfo:
    operators: frozenset[str]
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class ClassifiedRow:
    operator: str
    from_gare_id: int
    to_gare_id: int
    from_gare: str
    to_gare: str
    distance_km: float | None
    disposition: Disposition
    rule: str
    reason: str


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def read_zero_price_rows(od_pairs_path: Path) -> list[dict]:
    with od_pairs_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row for row in reader if row["class1"] in ("0", "0.0")]


def read_gate_lookup(gare_master_path: Path) -> dict[int, GateInfo]:
    lookup: dict[int, GateInfo] = {}
    with gare_master_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                gare_id = int(row["gare_id"])
            except ValueError:
                continue
            operators = frozenset(o.strip() for o in row["operators"].split("|") if o.strip())
            lat = float(row["lat"]) if row["lat"] not in (None, "") else None
            lon = float(row["lon"]) if row["lon"] not in (None, "") else None
            lookup[gare_id] = GateInfo(operators=operators, lat=lat, lon=lon)
    return lookup


def _distance_km(row: dict, from_gate: GateInfo | None, to_gate: GateInfo | None) -> float | None:
    if from_gate and to_gate and from_gate.lat is not None and to_gate.lat is not None:
        return haversine_km(from_gate.lat, from_gate.lon, to_gate.lat, to_gate.lon)
    # Fall back to od_pairs.csv's own distance_km when coordinates are missing;
    # only 8 of 551 rows carry it, but it is a stronger signal than nothing.
    raw = row["distance_km"]
    return float(raw) if raw not in (None, "") else None


def _rule_operator_boundary_short_hop(
    row: dict, from_gate: GateInfo | None, to_gate: GateInfo | None, distance_km: float | None
) -> tuple[Disposition, str, str] | None:
    if from_gate is None or to_gate is None:
        return None
    if from_gate.operators == to_gate.operators:
        return None
    if distance_km is None or distance_km > PROXIMITY_MAX_KM:
        return None
    return (
        Disposition.FREE_TRANSFER,
        "operator_boundary_short_hop",
        f"endpoints carry different gare_master operator tags "
        f"({sorted(from_gate.operators)} vs {sorted(to_gate.operators)}) and are "
        f"{distance_km:.2f} km apart (<= {PROXIMITY_MAX_KM:.0f} km): treated as a "
        "genuine cross-network free hand-off.",
    )


def _rule_structural_node_name(row: dict) -> tuple[Disposition, str, str] | None:
    from_name, to_name = row["from_gare"].lower(), row["to_gare"].lower()
    for keyword in STRUCTURAL_NAME_KEYWORDS:
        if keyword in from_name or keyword in to_name:
            return (
                Disposition.FREE_SECTION,
                "structural_node_name",
                f"an endpoint name contains '{keyword}': a motorway fork/merge node, "
                "not a priced barrier.",
            )
    return None


def _rule_short_physical_hop(distance_km: float | None) -> tuple[Disposition, str, str] | None:
    if distance_km is None or distance_km > PROXIMITY_MAX_KM:
        return None
    return (
        Disposition.FREE_SECTION,
        "short_physical_hop",
        f"gates are {distance_km:.2f} km apart (<= {PROXIMITY_MAX_KM:.0f} km): consistent "
        "with an adjacent-junction or dense local-interchange free connector rather than "
        "a discounted long-distance journey.",
    )


def classify_zero_price_row(row: dict, gate_lookup: dict[int, GateInfo]) -> ClassifiedRow:
    from_gare_id, to_gare_id = int(row["from_gare_id"]), int(row["to_gare_id"])
    from_gate = gate_lookup.get(from_gare_id)
    to_gate = gate_lookup.get(to_gare_id)
    distance_km = _distance_km(row, from_gate, to_gate)

    for rule in (
        lambda: _rule_operator_boundary_short_hop(row, from_gate, to_gate, distance_km),
        lambda: _rule_structural_node_name(row),
        lambda: _rule_short_physical_hop(distance_km),
    ):
        hit = rule()
        if hit is not None:
            disposition, rule_name, reason = hit
            break
    else:
        disposition, rule_name, reason = (
            Disposition.DROP,
            "default_no_signal",
            "no structural-node name, operator-boundary, or short-physical-hop signal fired; "
            "no positive evidence the zero price is real rather than missing/unrecorded data, "
            "so the row is excluded from the graph rather than trusted as a free edge.",
        )

    return ClassifiedRow(
        operator=row["operator"],
        from_gare_id=from_gare_id,
        to_gare_id=to_gare_id,
        from_gare=row["from_gare"],
        to_gare=row["to_gare"],
        distance_km=distance_km,
        disposition=disposition,
        rule=rule_name,
        reason=reason,
    )


def remediate(od_pairs_path: Path, gare_master_path: Path) -> list[ClassifiedRow]:
    rows = read_zero_price_rows(od_pairs_path)
    gate_lookup = read_gate_lookup(gare_master_path)

    classified = [classify_zero_price_row(row, gate_lookup) for row in rows]

    for row in classified:
        log = logger.warning if row.disposition is Disposition.DROP else logger.info
        log(
            "zero-price row disposition=%s rule=%s: %s (%s) -> %s (%s) [%s]",
            row.disposition.value,
            row.rule,
            row.from_gare,
            row.from_gare_id,
            row.to_gare,
            row.to_gare_id,
            row.operator,
        )

    return classified


def tally(classified: list[ClassifiedRow]) -> dict[str, Counter[str]]:
    by_operator: dict[str, Counter[str]] = {}
    for row in classified:
        by_operator.setdefault(row.operator, Counter())[row.disposition.value] += 1
    return by_operator


def render_report(classified: list[ClassifiedRow]) -> str:
    overall = Counter(row.disposition.value for row in classified)
    by_operator = tally(classified)

    lines = ["# Phase 2b — Zero-price row disposition", ""]
    lines.append(
        f"{len(classified)} zero-price (`class1 == 0`) rows found across "
        f"`od_pairs.csv`, spanning {len(by_operator)} operators. Every row below carries "
        "exactly one of three named dispositions, assigned by "
        "`tollroute.etl.remediate_zero_price.classify_zero_price_row` — none applied silently."
    )
    lines.append("")
    lines.append(
        "**Conjecture flagged:** the 8 km proximity threshold and the 'bifurcation' "
        "structural-name keyword are pattern-fitted to this dataset, not sourced from an "
        "authoritative document (see module docstring). Phase 2d's coverage audit and "
        "Phase 3c's national distance-error validation are where a wrong call here would "
        "surface and get corrected."
    )
    lines.append("")

    lines.append("## Overall tally")
    lines.append("")
    lines.append("| disposition | count |")
    lines.append("|---|---|")
    for disposition in Disposition:
        lines.append(f"| {disposition.value} | {overall.get(disposition.value, 0)} |")
    lines.append(f"| **total** | **{len(classified)}** |")
    lines.append("")

    lines.append("## Per-operator tally")
    lines.append("")
    lines.append("| operator | free_section | free_transfer | drop | total |")
    lines.append("|---|---|---|---|---|")
    for operator in sorted(by_operator):
        counts = by_operator[operator]
        total = sum(counts.values())
        lines.append(
            f"| {operator} | {counts.get('free_section', 0)} | "
            f"{counts.get('free_transfer', 0)} | {counts.get('drop', 0)} | {total} |"
        )
    lines.append("")

    lines.append("## Named rules (priority order)")
    lines.append("")
    lines.append(
        "1. `operator_boundary_short_hop` -> `free_transfer` — endpoints carry different "
        "`gare_master.operators` tags AND are <= 8 km apart (haversine)."
    )
    lines.append(
        "2. `structural_node_name` -> `free_section` — either endpoint name contains "
        "'bifurcation' (a motorway fork/merge node, never a priced barrier), any distance."
    )
    lines.append(
        "3. `short_physical_hop` -> `free_section` — gates <= 8 km apart (haversine, or "
        "od_pairs.csv `distance_km` where coordinates are unavailable)."
    )
    lines.append("4. `default_no_signal` -> `drop` — none of the above fired.")
    lines.append("")

    lines.append("## Sample rows per disposition")
    lines.append("")
    for disposition in Disposition:
        sample = [r for r in classified if r.disposition is disposition][:5]
        lines.append(f"### {disposition.value}")
        lines.append("")
        if not sample:
            lines.append("None.")
        else:
            lines.append("| operator | from | to | distance (km) | rule | reason |")
            lines.append("|---|---|---|---|---|---|")
            for r in sample:
                dist = f"{r.distance_km:.2f}" if r.distance_km is not None else "n/a"
                lines.append(
                    f"| {r.operator} | {r.from_gare} ({r.from_gare_id}) | "
                    f"{r.to_gare} ({r.to_gare_id}) | {dist} | {r.rule} | {r.reason} |"
                )
        lines.append("")

    return "\n".join(lines) + "\n"


def run(
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> list[ClassifiedRow]:
    classified = remediate(od_pairs_path, gare_master_path)

    report = render_report(classified)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)

    overall = Counter(row.disposition.value for row in classified)
    logger.info(
        "classified %d zero-price rows: %s; report written to %s",
        len(classified),
        dict(overall),
        report_path,
    )
    return classified


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--od-pairs", type=Path, default=DEFAULT_OD_PAIRS_PATH)
    parser.add_argument("--gare-master", type=Path, default=DEFAULT_GARE_MASTER_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    run(od_pairs_path=args.od_pairs, gare_master_path=args.gare_master, report_path=args.report)


if __name__ == "__main__":
    main()
