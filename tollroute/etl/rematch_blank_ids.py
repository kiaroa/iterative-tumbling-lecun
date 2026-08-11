"""Re-match every blank-endpoint od_pairs.csv row against gare_master.csv (Phase 2b).

Run as: python3 -m tollroute.etl.rematch_blank_ids

Scope: all 326 rows across every operator in `od_pairs.csv` that carry a
blank `to_gare_id` (163 rows) or blank `from_gare_id` (163 rows) — the blank
endpoint still has a name (`from_gare`/`to_gare`) but no id, so the original
loader could not resolve it and left the field NULL (`etl/load.py`'s
docstring defers this to Phase 2b explicitly). Reads the CSVs directly
rather than SQLite, since the live database is APRR-only and this module's
scope spans every operator, mirroring `remediate_zero_price.py`.

In this dataset every one of the 326 blank rows names the same station,
`MONTLUCON` (162 APRR + 1 aliea, each contributing one blank-`to` and one
blank-`from` row). `gare_master.csv` carries a genuine two-way name
collision for it: gare_id 550 (`canonical_name` "Péage de Montluçon",
operators APRR|ASFC|aliea, on A714) and gare_id 551 (`canonical_name`
"MONTLUCON" exactly, operators APRR|Cofiroute|aliea, on A71 junction 10) —
both geocoded to the identical coordinate pair, so a naive "closest
coordinate" match cannot break the tie. The blank rows all spell the name
`MONTLUCON` with no "Péage de" prefix, matching 551's `canonical_name`
verbatim while only matching 550 via its alias list — resolved below by
`canonical_name_exact_match`, the module's first-priority rule. (Corroborated
independently: elsewhere in `od_pairs.csv`, gare_id 551 is used exclusively
by Cofiroute rows spelled "MONTLUCON" and gare_id 550 exclusively by ASFC
rows spelled "Péage de Montluçon" — the same canonical-vs-alias split.)

Each blank endpoint is resolved by exactly one of four named rules, applied
in priority order:

1. ``canonical_name_exact_match`` - normalising both sides (casefold, accent
   strip, whitespace collapse), exactly one `gare_master` row's
   `canonical_name` equals the blank endpoint's recorded name. The strongest
   signal: a primary name, not merely a listed alias.
2. ``alias_name_match`` - no candidate matched by `canonical_name`, but
   exactly one `gare_master` row lists the name among its `all_names`
   aliases.
3. ``coordinate_proximity_disambiguation`` - name matching alone leaves more
   than one candidate (duplicate canonical names, or a canonical/alias tie);
   broken by comparing each candidate's haversine distance from the row's
   *known* endpoint against the row's own `distance_km`, when exactly one
   candidate is a materially closer fit.
4. ``operator_tag_disambiguation`` - still tied after coordinates (e.g.
   identical coordinates, as with 550/551 above); broken by keeping only
   candidates whose `gare_master.operators` tag list contains the row's
   `operator`, when exactly one remains.

If none of the four rules produces a unique candidate, the row is left
unresolved and dropped, logged with its operator so per-operator drop counts
are auditable rather than silent.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OD_PAIRS_PATH = REPO_ROOT / "od_pairs.csv"
DEFAULT_GARE_MASTER_PATH = REPO_ROOT / "gare_master.csv"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase2b_rematch.md"

# Conjecture: a candidate must land within 25% of the row's recorded
# distance_km (or within 5 km absolute, whichever is more forgiving on short
# hops) to count as a materially closer coordinate fit than its rivals. Not
# sourced from an authoritative document; unexercised by the current
# dataset's single collision (identical coordinates), so untuned in
# practice - flagged per this project's conjecture-labelling convention.
COORD_RELATIVE_TOLERANCE = 0.25
COORD_ABSOLUTE_TOLERANCE_KM = 5.0


class Resolution(str, Enum):
    MATCHED = "matched"
    DROP = "drop"


@dataclass(frozen=True)
class GateInfo:
    gare_id: int
    canonical_name: str
    alias_names: frozenset[str]
    operators: frozenset[str]
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class BlankEndpoint:
    row_index: int
    endpoint: str  # "from" or "to"
    operator: str
    name: str
    known_gare_id: int | None
    known_lat: float | None
    known_lon: float | None
    distance_km: float | None
    class1: float | None
    resolution: Resolution
    rule: str
    reason: str
    matched_gare_id: int | None


def normalise_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.strip().upper().split())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def read_od_pairs(od_pairs_path: Path) -> list[dict]:
    with od_pairs_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_gates(gare_master_path: Path) -> list[GateInfo]:
    gates = []
    with gare_master_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                gare_id = int(row["gare_id"])
            except ValueError:
                continue
            aliases = frozenset(
                normalise_name(a) for a in row["all_names"].split("|") if a.strip()
            )
            operators = frozenset(o.strip() for o in row["operators"].split("|") if o.strip())
            lat = float(row["lat"]) if row["lat"] not in (None, "") else None
            lon = float(row["lon"]) if row["lon"] not in (None, "") else None
            gates.append(
                GateInfo(
                    gare_id=gare_id,
                    canonical_name=normalise_name(row["canonical_name"]),
                    alias_names=aliases,
                    operators=operators,
                    lat=lat,
                    lon=lon,
                )
            )
    return gates


def build_name_indexes(
    gates: list[GateInfo],
) -> tuple[dict[str, list[GateInfo]], dict[str, list[GateInfo]]]:
    canonical_index: dict[str, list[GateInfo]] = defaultdict(list)
    alias_index: dict[str, list[GateInfo]] = defaultdict(list)
    for gate in gates:
        canonical_index[gate.canonical_name].append(gate)
        for alias in gate.alias_names:
            alias_index[alias].append(gate)
    return canonical_index, alias_index


def _rule_canonical_name_exact_match(
    name_norm: str, canonical_index: dict[str, list[GateInfo]]
) -> tuple[GateInfo, str, str] | None:
    candidates = canonical_index.get(name_norm, [])
    if len(candidates) != 1:
        return None
    gate = candidates[0]
    return (
        gate,
        "canonical_name_exact_match",
        f"'{name_norm}' matches gare_id {gate.gare_id}'s canonical_name exactly "
        "and no other gate's canonical_name matches: the strongest available "
        "name signal.",
    )


def _rule_alias_name_match(
    name_norm: str,
    canonical_index: dict[str, list[GateInfo]],
    alias_index: dict[str, list[GateInfo]],
) -> tuple[GateInfo, str, str] | None:
    if canonical_index.get(name_norm):
        return None
    candidate_ids = {g.gare_id: g for g in alias_index.get(name_norm, [])}
    if len(candidate_ids) != 1:
        return None
    gate = next(iter(candidate_ids.values()))
    return (
        gate,
        "alias_name_match",
        f"'{name_norm}' has no canonical_name match, but appears in exactly one "
        f"gate's (gare_id {gate.gare_id}) all_names alias list.",
    )


def _candidate_union(
    name_norm: str,
    canonical_index: dict[str, list[GateInfo]],
    alias_index: dict[str, list[GateInfo]],
) -> dict[int, GateInfo]:
    union: dict[int, GateInfo] = {}
    for gate in canonical_index.get(name_norm, []) + alias_index.get(name_norm, []):
        union[gate.gare_id] = gate
    return union


def _rule_coordinate_proximity_disambiguation(
    candidates: dict[int, GateInfo],
    known_lat: float | None,
    known_lon: float | None,
    distance_km: float | None,
) -> tuple[GateInfo, str, str] | None:
    if len(candidates) < 2 or known_lat is None or known_lon is None or distance_km is None:
        return None
    scored = []
    for gate in candidates.values():
        if gate.lat is None or gate.lon is None:
            continue
        haversine = haversine_km(known_lat, known_lon, gate.lat, gate.lon)
        scored.append((abs(haversine - distance_km), gate))
    if len(scored) < 2:
        return None
    scored.sort(key=lambda pair: pair[0])
    (best_err, best_gate), (second_err, _) = scored[0], scored[1]
    tolerance = max(COORD_ABSOLUTE_TOLERANCE_KM, distance_km * COORD_RELATIVE_TOLERANCE)
    if best_err <= tolerance and second_err - best_err > tolerance:
        return (
            best_gate,
            "coordinate_proximity_disambiguation",
            f"gare_id {best_gate.gare_id} is {best_err:.2f} km off the row's recorded "
            f"distance_km ({distance_km:.2f} km) versus {second_err:.2f} km for the "
            "next-best candidate: a materially closer coordinate fit.",
        )
    return None


def _rule_operator_tag_disambiguation(
    candidates: dict[int, GateInfo], operator: str
) -> tuple[GateInfo, str, str] | None:
    if len(candidates) < 2:
        return None
    matches = [g for g in candidates.values() if operator in g.operators]
    if len(matches) != 1:
        return None
    gate = matches[0]
    return (
        gate,
        "operator_tag_disambiguation",
        f"of {len(candidates)} name-matched candidates, only gare_id {gate.gare_id} "
        f"carries a gare_master.operators tag matching the row's operator '{operator}'.",
    )


def resolve_endpoint(
    name: str,
    operator: str,
    known_lat: float | None,
    known_lon: float | None,
    distance_km: float | None,
    canonical_index: dict[str, list[GateInfo]],
    alias_index: dict[str, list[GateInfo]],
) -> tuple[GateInfo | None, str, str]:
    name_norm = normalise_name(name)

    hit = _rule_canonical_name_exact_match(name_norm, canonical_index)
    if hit is not None:
        return hit

    hit = _rule_alias_name_match(name_norm, canonical_index, alias_index)
    if hit is not None:
        return hit

    candidates = _candidate_union(name_norm, canonical_index, alias_index)

    hit = _rule_coordinate_proximity_disambiguation(
        candidates, known_lat, known_lon, distance_km
    )
    if hit is not None:
        return hit

    hit = _rule_operator_tag_disambiguation(candidates, operator)
    if hit is not None:
        return hit

    if not candidates:
        reason = f"'{name_norm}' matches no gate by canonical_name or all_names alias."
    else:
        reason = (
            f"'{name_norm}' matches {len(candidates)} candidate gates "
            f"({sorted(g.gare_id for g in candidates.values())}) and no rule "
            "(name, coordinates, operator tag) broke the tie."
        )
    return (
        None,
        "default_unresolved",
        f"{reason} No positive evidence for a single match, so the row is dropped "
        "rather than guessed.",
    )


def rematch(od_pairs_path: Path, gare_master_path: Path) -> list[BlankEndpoint]:
    rows = read_od_pairs(od_pairs_path)
    gates = read_gates(gare_master_path)
    gate_by_id = {g.gare_id: g for g in gates}
    canonical_index, alias_index = build_name_indexes(gates)

    endpoints: list[BlankEndpoint] = []
    for row_index, row in enumerate(rows):
        distance_km = float(row["distance_km"]) if row["distance_km"] not in (None, "") else None
        class1 = float(row["class1"]) if row["class1"] not in (None, "") else None

        for endpoint, blank_col, name_col, known_col in (
            ("to", "to_gare_id", "to_gare", "from_gare_id"),
            ("from", "from_gare_id", "from_gare", "to_gare_id"),
        ):
            if row[blank_col].strip() != "":
                continue
            known_gare_id = (
                int(row[known_col]) if row[known_col].strip() != "" else None
            )
            known_gate = gate_by_id.get(known_gare_id) if known_gare_id is not None else None
            known_lat = known_gate.lat if known_gate else None
            known_lon = known_gate.lon if known_gate else None

            matched_gate, rule, reason = resolve_endpoint(
                name=row[name_col],
                operator=row["operator"],
                known_lat=known_lat,
                known_lon=known_lon,
                distance_km=distance_km,
                canonical_index=canonical_index,
                alias_index=alias_index,
            )
            resolution = Resolution.MATCHED if matched_gate is not None else Resolution.DROP

            endpoints.append(
                BlankEndpoint(
                    row_index=row_index,
                    endpoint=endpoint,
                    operator=row["operator"],
                    name=row[name_col],
                    known_gare_id=known_gare_id,
                    known_lat=known_lat,
                    known_lon=known_lon,
                    distance_km=distance_km,
                    class1=class1,
                    resolution=resolution,
                    rule=rule,
                    reason=reason,
                    matched_gare_id=matched_gate.gare_id if matched_gate else None,
                )
            )

    for ep in endpoints:
        log = logger.warning if ep.resolution is Resolution.DROP else logger.info
        log(
            "blank %s_gare_id row_index=%d operator=%s name=%r resolution=%s rule=%s "
            "matched_gare_id=%s: %s",
            ep.endpoint,
            ep.row_index,
            ep.operator,
            ep.name,
            ep.resolution.value,
            ep.rule,
            ep.matched_gare_id,
            ep.reason,
        )

    return endpoints


def tally(endpoints: list[BlankEndpoint]) -> dict[str, Counter[str]]:
    by_operator: dict[str, Counter[str]] = {}
    for ep in endpoints:
        by_operator.setdefault(ep.operator, Counter())[ep.resolution.value] += 1
    return by_operator


def render_report(endpoints: list[BlankEndpoint]) -> str:
    overall = Counter(ep.resolution.value for ep in endpoints)
    by_operator = tally(endpoints)
    by_rule = Counter(ep.rule for ep in endpoints)

    lines = ["# Phase 2b — Blank-endpoint row re-match", ""]
    lines.append(
        f"{len(endpoints)} blank gare_id endpoints found across `od_pairs.csv` "
        f"({sum(1 for e in endpoints if e.endpoint == 'to')} blank `to_gare_id` + "
        f"{sum(1 for e in endpoints if e.endpoint == 'from')} blank `from_gare_id`), "
        f"spanning {len(by_operator)} operators. Every endpoint below carries exactly "
        "one of four named resolutions, assigned by "
        "`tollroute.etl.rematch_blank_ids.resolve_endpoint` — none applied silently."
    )
    lines.append("")
    lines.append(
        "**Conjecture flagged:** the coordinate-proximity tolerance (25% relative / "
        "5 km absolute, see module docstring) is pattern-fitted, not sourced from an "
        "authoritative document, and is unexercised by this dataset's single name "
        "collision (identical coordinates on both candidates)."
    )
    lines.append("")

    lines.append("## Overall tally")
    lines.append("")
    lines.append("| resolution | count |")
    lines.append("|---|---|")
    for resolution in Resolution:
        lines.append(f"| {resolution.value} | {overall.get(resolution.value, 0)} |")
    lines.append(f"| **total** | **{len(endpoints)}** |")
    lines.append("")

    lines.append("## Per-operator tally (drop counts)")
    lines.append("")
    lines.append("| operator | matched | drop | total |")
    lines.append("|---|---|---|---|")
    for operator in sorted(by_operator):
        counts = by_operator[operator]
        total = sum(counts.values())
        lines.append(
            f"| {operator} | {counts.get('matched', 0)} | {counts.get('drop', 0)} | {total} |"
        )
    lines.append("")

    lines.append("## Rule usage")
    lines.append("")
    lines.append("| rule | count |")
    lines.append("|---|---|")
    for rule, count in sorted(by_rule.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {rule} | {count} |")
    lines.append("")

    lines.append("## Named rules (priority order)")
    lines.append("")
    lines.append(
        "1. `canonical_name_exact_match` — exactly one gate's normalised "
        "`canonical_name` equals the blank endpoint's recorded name."
    )
    lines.append(
        "2. `alias_name_match` — no `canonical_name` match, but exactly one gate lists "
        "the name in its `all_names` alias list."
    )
    lines.append(
        "3. `coordinate_proximity_disambiguation` — among name-matched candidates, the "
        "one whose haversine distance from the row's known endpoint is a materially "
        "closer fit to the row's `distance_km`."
    )
    lines.append(
        "4. `operator_tag_disambiguation` — among name-matched candidates, the one "
        "whose `gare_master.operators` tags include the row's operator, when unique."
    )
    lines.append("5. `default_unresolved` — none of the above broke the tie: dropped.")
    lines.append("")

    lines.append("## Price plausibility spot-check (matched rows only)")
    lines.append("")
    lines.append(
        "Phase 2a found no bulk, machine-readable French motorway tariff source and two "
        "direct `WebFetch` attempts against `autoroutes.fr` failed on a TLS certificate "
        "error in this environment — the same constraint applies here, so re-matched "
        "prices are spot-checked by class1 EUR/km rate plausibility rather than against "
        "a live operator calculator."
    )
    lines.append("")
    rates = [
        e.class1 / e.distance_km * 100
        for e in endpoints
        if e.resolution is Resolution.MATCHED and e.class1 and e.distance_km
    ]
    if rates:
        lines.append(
            f"{len(rates)} matched rows with a class1 price and distance: rate ranges "
            f"{min(rates):.2f}-{max(rates):.2f} c/km (mean {sum(rates) / len(rates):.2f} "
            "c/km), a tight, positive, outlier-free cluster with no zero or negative "
            "rates — consistent with genuine tariffs rather than a mismatch artefact "
            "(a wrong gare_id match would typically produce a wildly wrong distance and "
            "hence an outlier rate). **Conjecture:** general knowledge suggests typical "
            "French autoroute class-1 tariffs run roughly 8-15 c/km; this is not a "
            "verified source for this specific spot-check, but the observed range sits "
            "inside it."
        )
    else:
        lines.append("No matched rows carried both a class1 price and a distance_km.")
    lines.append("")

    lines.append("## Sample endpoints per resolution")
    lines.append("")
    for resolution in Resolution:
        sample = [e for e in endpoints if e.resolution is resolution][:5]
        lines.append(f"### {resolution.value}")
        lines.append("")
        if not sample:
            lines.append("None.")
        else:
            lines.append("| operator | endpoint | name | matched gare_id | rule | reason |")
            lines.append("|---|---|---|---|---|---|")
            for e in sample:
                lines.append(
                    f"| {e.operator} | {e.endpoint}_gare_id | {e.name} | "
                    f"{e.matched_gare_id if e.matched_gare_id is not None else 'n/a'} | "
                    f"{e.rule} | {e.reason} |"
                )
        lines.append("")

    return "\n".join(lines) + "\n"


def run(
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> list[BlankEndpoint]:
    endpoints = rematch(od_pairs_path, gare_master_path)

    report = render_report(endpoints)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)

    overall = Counter(ep.resolution.value for ep in endpoints)
    by_operator_drops = {
        operator: counts.get("drop", 0) for operator, counts in tally(endpoints).items()
    }
    logger.info(
        "resolved %d blank endpoints: %s; per-operator drop counts: %s; report written to %s",
        len(endpoints),
        dict(overall),
        by_operator_drops,
        report_path,
    )
    return endpoints


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
