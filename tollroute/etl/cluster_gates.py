"""Cluster geocoded gates to physical points and type transfer edges (Phase 2c).

Run as: python3 -m tollroute.etl.cluster_gates

Two deliverables from `iterative-tumbling-lecun.md` Phase 2c:

1. **Physical-gate clustering.** `gare_master.csv` carries 953 geocoded gates
   but only ~815 *physical* points: the upstream geocoding pipeline snapped
   co-located gates (opposite carriageways, or two concessions meeting at one
   barrier) to *identical* coordinates. Grouping by exact coordinate therefore
   collapses 953 gates -> exactly **815** physical points, matching the spec's
   own ground-truth figure ("815 distinct physical points"). Each group gets a
   stable `physical_gate_id`, producing the `physical_gate_id <-> gare_id`
   lookup the matrix/graph phases need.

   *Why exact coordinate rather than a 100 m union-find:* a 100 m transitive
   union-find over-merges to ~790 points by chaining 36 near-but-distinct
   carriageway pairs (gates 50-100 m apart that are genuinely separate physical
   barriers) into their neighbours. Exact-coordinate grouping realises the
   spec's 815 and keeps those near pairs as distinct points; the ~100 m
   tolerance is applied instead to *transfer-edge typing* below, where it
   belongs.

2. **Transfer-edge typing.** For every pair of gates within
   ``CO_LOCATION_MAX_M`` (~100 m — spec's co-location radius) a transfer edge is
   typed as exactly one of:

   - ``boundary`` — the two gates carry **disjoint** operator tags (a genuine
     concession boundary, e.g. ABLIS = ASFC gare_id 4 + Cofiroute gare_id 5).
     Free, zero-time. Per the Phase 1c "Core architectural decision", a
     ``boundary`` edge is the *only* permitted connector between two
     different-operator toll edges.
   - ``exit_reentry`` — the two gates **share** an operator tag (same
     concession; exit one barrier and re-enter at the co-located one). Carries
     the 3 min / 0.5 km dwell. Remains **excluded** as a toll-edge connector
     (both sides share an operator, so chaining through it would be the
     same-operator toll-edge chaining Phase 1c forbids).

The 3 gates without coordinates cannot be clustered here; they are reported and
deferred to the Phase 2c free-flow / `suspect_gates` item, not silently dropped.

**Conjecture flagged explicitly:** the exact-coordinate collapse assumes the
geocoder's identical-coordinate assignment is itself the authoritative
co-location signal; the 100 m transfer radius and the "disjoint operators =
boundary" rule are judgement calls fitted to this dataset (ABLIS is the one
manually-verified anchor). Phase 2d's coverage audit and Phase 3c's snap-quality
curation are where a wrong call here would surface and get corrected.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GARE_MASTER_PATH = REPO_ROOT / "gare_master.csv"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase2c_clustering.md"

# Spec's co-location radius for transfer-edge typing. Physical clustering itself
# uses exact-coordinate equality (see module docstring); this radius only types
# transfer edges, so it does not affect the 815 physical-point count.
CO_LOCATION_MAX_M = 100.0

# exit_reentry dwell — same 3 min / 0.5 km as the Phase 1c per-gate dwell edge.
EXIT_REENTRY_DWELL_MIN = 3.0
EXIT_REENTRY_DWELL_KM = 0.5

# ABLIS is the spec's one manually-verified cross-operator boundary anchor.
ABLIS_GARE_IDS = (4, 5)


class TransferType(str, Enum):
    BOUNDARY = "boundary"
    EXIT_REENTRY = "exit_reentry"


@dataclass(frozen=True)
class Gate:
    gare_id: int
    lat: float
    lon: float
    operators: frozenset[str]
    canonical_name: str


@dataclass(frozen=True)
class PhysicalCluster:
    physical_gate_id: int
    lat: float
    lon: float
    gare_ids: tuple[int, ...]


@dataclass(frozen=True)
class TransferEdge:
    a_gare_id: int
    b_gare_id: int
    a_name: str
    b_name: str
    transfer_type: TransferType
    distance_m: float
    dwell_min: float
    dwell_km: float
    reason: str


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def read_gates(gare_master_path: Path) -> tuple[list[Gate], list[int]]:
    """Return (geocoded gates, gare_ids without coordinates).

    Coordinate-less gates cannot be clustered; they are returned separately so
    the caller can report them (Phase 2c's suspect_gates item resolves them).
    """
    gates: list[Gate] = []
    coordinateless: list[int] = []
    with gare_master_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                gare_id = int(row["gare_id"])
            except ValueError:
                continue
            if row["lat"] in (None, "") or row["lon"] in (None, ""):
                coordinateless.append(gare_id)
                continue
            operators = frozenset(o.strip() for o in row["operators"].split("|") if o.strip())
            gates.append(
                Gate(
                    gare_id=gare_id,
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    operators=operators,
                    canonical_name=row["canonical_name"],
                )
            )
    return gates, coordinateless


def cluster_physical_points(gates: list[Gate]) -> list[PhysicalCluster]:
    """Collapse gates sharing exact coordinates into physical points.

    physical_gate_id is assigned deterministically by ascending minimum member
    gare_id, so the lookup is stable across runs.
    """
    by_coord: dict[tuple[float, float], list[Gate]] = defaultdict(list)
    for gate in gates:
        by_coord[(gate.lat, gate.lon)].append(gate)

    groups = sorted(by_coord.values(), key=lambda members: min(g.gare_id for g in members))
    clusters: list[PhysicalCluster] = []
    for physical_gate_id, members in enumerate(groups, start=1):
        gare_ids = tuple(sorted(g.gare_id for g in members))
        clusters.append(
            PhysicalCluster(
                physical_gate_id=physical_gate_id,
                lat=members[0].lat,
                lon=members[0].lon,
                gare_ids=gare_ids,
            )
        )
    return clusters


def build_lookup(clusters: list[PhysicalCluster]) -> dict[int, int]:
    """Return the gare_id -> physical_gate_id lookup."""
    return {
        gare_id: cluster.physical_gate_id
        for cluster in clusters
        for gare_id in cluster.gare_ids
    }


def _type_pair(a: Gate, b: Gate, distance_m: float) -> TransferEdge:
    if a.operators.isdisjoint(b.operators):
        return TransferEdge(
            a_gare_id=a.gare_id,
            b_gare_id=b.gare_id,
            a_name=a.canonical_name,
            b_name=b.canonical_name,
            transfer_type=TransferType.BOUNDARY,
            distance_m=distance_m,
            dwell_min=0.0,
            dwell_km=0.0,
            reason=(
                f"gates {distance_m:.0f} m apart carry disjoint operator tags "
                f"({sorted(a.operators)} vs {sorted(b.operators)}): a genuine "
                "concession boundary — free, zero-time, and the only permitted "
                "connector between two different-operator toll edges."
            ),
        )
    return TransferEdge(
        a_gare_id=a.gare_id,
        b_gare_id=b.gare_id,
        a_name=a.canonical_name,
        b_name=b.canonical_name,
        transfer_type=TransferType.EXIT_REENTRY,
        distance_m=distance_m,
        dwell_min=EXIT_REENTRY_DWELL_MIN,
        dwell_km=EXIT_REENTRY_DWELL_KM,
        reason=(
            f"gates {distance_m:.0f} m apart share operator tag(s) "
            f"({sorted(a.operators & b.operators)}): same concession — a "
            f"{EXIT_REENTRY_DWELL_MIN:.0f} min / {EXIT_REENTRY_DWELL_KM} km "
            "exit/re-entry dwell, excluded as a toll-edge connector."
        ),
    )


def type_transfer_edges(
    gates: list[Gate], max_m: float = CO_LOCATION_MAX_M
) -> list[TransferEdge]:
    """Type every co-located (<= max_m) gate pair as boundary or exit_reentry."""
    edges: list[TransferEdge] = []
    n = len(gates)
    for i in range(n):
        a = gates[i]
        for j in range(i + 1, n):
            b = gates[j]
            # Cheap bounding-box reject before the haversine (0.01 deg ~ 1.1 km).
            if abs(a.lat - b.lat) > 0.01 or abs(a.lon - b.lon) > 0.01:
                continue
            distance_m = haversine_m(a.lat, a.lon, b.lat, b.lon)
            if distance_m <= max_m:
                edges.append(_type_pair(a, b, distance_m))
    return edges


def find_transfer_edge(
    edges: list[TransferEdge], gare_id_a: int, gare_id_b: int
) -> TransferEdge | None:
    wanted = {gare_id_a, gare_id_b}
    for edge in edges:
        if {edge.a_gare_id, edge.b_gare_id} == wanted:
            return edge
    return None


def render_report(
    clusters: list[PhysicalCluster],
    edges: list[TransferEdge],
    coordinateless: list[int],
) -> str:
    by_type = Counter(e.transfer_type.value for e in edges)
    multi = [c for c in clusters if len(c.gare_ids) > 1]
    ablis = find_transfer_edge(edges, *ABLIS_GARE_IDS)

    lines = ["# Phase 2c — Physical gate clustering and transfer edges", ""]
    lines.append(
        f"{sum(len(c.gare_ids) for c in clusters)} geocoded gates collapse to "
        f"**{len(clusters)} physical points** by exact-coordinate grouping "
        f"({len(multi)} points bundle more than one gare_id). Every co-located "
        f"(<= {CO_LOCATION_MAX_M:.0f} m) gate pair is typed as exactly one "
        "transfer edge — none applied silently."
    )
    lines.append("")
    lines.append(
        "**Conjecture flagged:** exact-coordinate collapse trusts the geocoder's "
        "identical-coordinate assignment as the co-location signal; the 100 m "
        "transfer radius and 'disjoint operators = boundary' rule are fitted to "
        "this dataset (ABLIS is the one manually-verified anchor). Phase 2d's "
        "coverage audit and Phase 3c's snap-quality curation are where a wrong "
        "call surfaces."
    )
    lines.append("")

    lines.append("## Clustering")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(f"| geocoded gates | {sum(len(c.gare_ids) for c in clusters)} |")
    lines.append(f"| physical points | {len(clusters)} |")
    lines.append(f"| multi-gate physical points | {len(multi)} |")
    lines.append(f"| gates without coordinates (deferred to suspect_gates) | {len(coordinateless)} |")
    lines.append("")

    lines.append("## Transfer edges")
    lines.append("")
    lines.append("| type | count | dwell |")
    lines.append("|---|---|---|")
    lines.append(f"| boundary | {by_type.get('boundary', 0)} | free, zero-time |")
    lines.append(
        f"| exit_reentry | {by_type.get('exit_reentry', 0)} | "
        f"{EXIT_REENTRY_DWELL_MIN:.0f} min / {EXIT_REENTRY_DWELL_KM} km |"
    )
    lines.append(f"| **total** | **{len(edges)}** | |")
    lines.append("")

    lines.append("## ABLIS cross-operator boundary (manual verification anchor)")
    lines.append("")
    if ablis is None:
        lines.append(
            f"**MISSING** — no transfer edge found between gare_ids "
            f"{ABLIS_GARE_IDS[0]} and {ABLIS_GARE_IDS[1]}."
        )
    else:
        lines.append(
            f"gare_id {ablis.a_gare_id} ({ablis.a_name}) <-> {ablis.b_gare_id} "
            f"({ablis.b_name}): **{ablis.transfer_type.value}**, "
            f"{ablis.distance_m:.0f} m apart. {ablis.reason}"
        )
    lines.append("")

    lines.append("## Sample transfer edges per type")
    lines.append("")
    for transfer_type in TransferType:
        sample = [e for e in edges if e.transfer_type is transfer_type][:5]
        lines.append(f"### {transfer_type.value}")
        lines.append("")
        if not sample:
            lines.append("None.")
        else:
            lines.append("| a | b | distance (m) | reason |")
            lines.append("|---|---|---|---|")
            for e in sample:
                lines.append(
                    f"| {e.a_name} ({e.a_gare_id}) | {e.b_name} ({e.b_gare_id}) | "
                    f"{e.distance_m:.0f} | {e.reason} |"
                )
        lines.append("")

    return "\n".join(lines) + "\n"


def run(
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> tuple[list[PhysicalCluster], list[TransferEdge], dict[int, int]]:
    gates, coordinateless = read_gates(gare_master_path)
    clusters = cluster_physical_points(gates)
    lookup = build_lookup(clusters)
    edges = type_transfer_edges(gates)

    for edge in edges:
        logger.info(
            "transfer edge type=%s: %s (%d) <-> %s (%d) [%.0f m]",
            edge.transfer_type.value,
            edge.a_name,
            edge.a_gare_id,
            edge.b_name,
            edge.b_gare_id,
            edge.distance_m,
        )
    if coordinateless:
        logger.warning(
            "%d gates without coordinates could not be clustered (deferred to "
            "suspect_gates): %s",
            len(coordinateless),
            coordinateless,
        )

    ablis = find_transfer_edge(edges, *ABLIS_GARE_IDS)
    if ablis is None or ablis.transfer_type is not TransferType.BOUNDARY:
        logger.error("ABLIS boundary verification failed: %s", ablis)
    else:
        logger.info("ABLIS boundary verified: %s", ablis.reason)

    report = render_report(clusters, edges, coordinateless)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)

    by_type = Counter(e.transfer_type.value for e in edges)
    logger.info(
        "clustered %d gates -> %d physical points; %d transfer edges %s; "
        "report written to %s",
        len(gates),
        len(clusters),
        len(edges),
        dict(by_type),
        report_path,
    )
    return clusters, edges, lookup


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gare-master", type=Path, default=DEFAULT_GARE_MASTER_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    run(gare_master_path=args.gare_master, report_path=args.report)


if __name__ == "__main__":
    main()
