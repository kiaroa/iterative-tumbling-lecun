"""Phase 1: static gate classification — no API calls.

Reads gare_master.csv, od_pairs.csv, and (optionally) the existing
source_vs_osrm_distances.csv to assign name/structural flags to every gate.

Output: analysis/gate_validation/gate_classification.csv
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

GARE_MASTER = Path("gare_master.csv")
OD_PAIRS = Path("od_pairs.csv")
DISTANCE_COMPARISON = Path("analysis/source_vs_osrm_distances.csv")
OUT = Path("analysis/gate_validation/gate_classification.csv")

# (pattern, flag_name) — checked against lowercased canonical_name
NAME_FLAGS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"syst[eè]me ouvert|syst[eè]me ferm[eé]|syst[eè]me"), "VIRTUAL"),
    (re.compile(r"limite de concession|fronti[eè]re"), "ADMIN_BOUNDARY"),
    (re.compile(r"bretelle"), "BRETELLE"),
    (re.compile(r"barri[eè]re|barriere"), "BARRIERE"),
    (re.compile(r"p[eé]age en syst"), "PEAGE_EN"),
]


def classify(
    gare_master: Path = GARE_MASTER,
    od_pairs: Path = OD_PAIRS,
    distance_comparison: Path = DISTANCE_COMPARISON,
    out: Path = OUT,
) -> list[dict]:
    gates = list(csv.DictReader(open(gare_master)))
    pairs = list(csv.DictReader(open(od_pairs)))

    # coord duplicate detection
    coord_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    for g in gates:
        if g["lat"].strip() and g["lon"].strip():
            coord_map[(g["lat"], g["lon"])].append(g["gare_id"])
    duplicate_ids: set[str] = set()
    for ids in coord_map.values():
        if len(ids) > 1:
            duplicate_ids.update(ids)

    # OD role per gate per operator
    from_ids: dict[str, set[str]] = defaultdict(set)  # operator -> set of from gare_ids
    to_ids: dict[str, set[str]] = defaultdict(set)
    for p in pairs:
        op = p["operator"]
        if p["from_gare_id"].strip():
            from_ids[op].add(p["from_gare_id"])
        if p["to_gare_id"].strip():
            to_ids[op].add(p["to_gare_id"])

    # distance anomaly score: per gare_id, collect ratios from existing comparison CSV
    ratios_by_gate: dict[str, list[float]] = defaultdict(list)
    if distance_comparison.exists():
        for row in csv.DictReader(open(distance_comparison)):
            if row["ratio"]:
                r = float(row["ratio"])
                ratios_by_gate[row["from_gare_id"]].append(r)
                ratios_by_gate[row["to_gare_id"]].append(r)

    rows_out: list[dict] = []
    for g in gates:
        gid = g["gare_id"]
        name = g["canonical_name"]
        name_lower = name.lower()
        ops = [o.strip() for o in g["operators"].split("|") if o.strip()]

        # name flags
        flags: list[str] = []
        for pattern, flag in NAME_FLAGS:
            if pattern.search(name_lower):
                flags.append(flag)

        # duplicate coord
        is_dup = gid in duplicate_ids

        # OD role: check against each operator this gate belongs to
        sink_ops, source_ops = [], []
        for op in ops:
            in_from = gid in from_ids.get(op, set())
            in_to = gid in to_ids.get(op, set())
            if in_to and not in_from:
                sink_ops.append(op)
            elif in_from and not in_to:
                source_ops.append(op)
        if sink_ops:
            flags.append("OD_SINK_ONLY")
        if source_ops:
            flags.append("OD_SOURCE_ONLY")

        # low confidence / manual override
        tier = g["match_tier"]
        agreement = g["match_agreement"]
        if tier in {"D", "E", "F"}:
            flags.append("LOW_CONFIDENCE")
        if tier == "O":
            flags.append("MANUAL_OVERRIDE")
        if agreement == "conflicted":
            flags.append("CONFLICTED")

        # distance anomaly
        gate_ratios = ratios_by_gate.get(gid, [])
        if gate_ratios:
            sorted_r = sorted(gate_ratios)
            median_r = sorted_r[len(sorted_r) // 2]
            anomaly = abs(median_r - 1.0)
        else:
            median_r = None
            anomaly = None

        rows_out.append({
            "gare_id": gid,
            "canonical_name": name,
            "operators": g["operators"],
            "match_tier": tier,
            "match_agreement": agreement,
            "lat": g["lat"],
            "lon": g["lon"],
            "name_flags": "|".join(flags) if flags else "",
            "is_duplicate_coord": "1" if is_dup else "0",
            "distance_anomaly_median_ratio": round(median_r, 4) if median_r is not None else "",
            "distance_anomaly_score": round(anomaly, 4) if anomaly is not None else "",
        })

    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows_out[0].keys())
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    flagged = sum(1 for r in rows_out if r["name_flags"])
    dups = sum(1 for r in rows_out if r["is_duplicate_coord"] == "1")
    anomalous = sum(1 for r in rows_out if r["distance_anomaly_score"] and float(r["distance_anomaly_score"]) > 0.5)
    print(f"Phase 1: {len(rows_out)} gates classified")
    print(f"  flagged by name/role: {flagged}")
    print(f"  duplicate coord:      {dups}")
    print(f"  distance anomaly >0.5:{anomalous}")
    return rows_out


if __name__ == "__main__":
    classify()
