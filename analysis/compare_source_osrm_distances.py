"""Compare od_pairs.csv source distance_km against precomputed OSRM tolled distances
for APRR, AREA, and aliea operators.

Run from project root:
    python3 analysis/compare_source_osrm_distances.py

Writes analysis/source_vs_osrm_distances.csv and prints per-operator summary.
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from tollroute.etl import cluster_gates
from tollroute import matrices as matrices_mod

OPERATORS = {"APRR", "AREA", "aliea"}
OUTLIER_LOW = 0.80
OUTLIER_HIGH = 1.20

OD_PAIRS_PATH = Path("od_pairs.csv")
GARE_MASTER_PATH = Path("gare_master.csv")
MATRIX_DIR = Path("data/matrices")
OUT_CSV = Path("analysis/source_vs_osrm_distances.csv")


def main() -> None:
    clusters = matrices_mod.physical_gate_points(GARE_MASTER_PATH)
    pgid_of = cluster_gates.build_lookup(clusters)
    tolled_dist = matrices_mod.load_matrices(MATRIX_DIR)["tolled_distance_m"]

    # gare_id -> canonical name (for output readability)
    name_of: dict[int, str] = {}
    with open(GARE_MASTER_PATH) as f:
        for row in csv.DictReader(f):
            name_of[int(row["gare_id"])] = row["canonical_name"]

    rows_out: list[dict] = []
    with open(OD_PAIRS_PATH) as f:
        for row in csv.DictReader(f):
            if row["operator"] not in OPERATORS:
                continue
            dist_str = row["distance_km"].strip()
            if not dist_str:
                continue
            if not row["from_gare_id"].strip() or not row["to_gare_id"].strip():
                continue

            from_id = int(row["from_gare_id"])
            to_id = int(row["to_gare_id"])
            source_km = float(dist_str)

            from_pgid = pgid_of.get(from_id)
            to_pgid = pgid_of.get(to_id)

            osrm_km: float | None = None
            if from_pgid and to_pgid:
                pi, pj = from_pgid - 1, to_pgid - 1
                if pi != pj:
                    val = tolled_dist[pi, pj]
                    if not math.isnan(val):
                        osrm_km = float(val) / 1000.0

            delta_km = (osrm_km - source_km) if osrm_km is not None else None
            ratio = (osrm_km / source_km) if osrm_km is not None else None

            rows_out.append({
                "operator": row["operator"],
                "from_gare_id": from_id,
                "from_gare": name_of.get(from_id, ""),
                "to_gare_id": to_id,
                "to_gare": name_of.get(to_id, ""),
                "source_km": round(source_km, 3),
                "osrm_km": round(osrm_km, 3) if osrm_km is not None else "",
                "delta_km": round(delta_km, 3) if delta_km is not None else "",
                "ratio": round(ratio, 4) if ratio is not None else "",
            })

    # write CSV
    fieldnames = ["operator", "from_gare_id", "from_gare", "to_gare_id", "to_gare",
                  "source_km", "osrm_km", "delta_km", "ratio"]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)
    print(f"Wrote {len(rows_out)} rows → {OUT_CSV}\n")

    # per-operator summary
    for op in sorted(OPERATORS):
        op_rows = [r for r in rows_out if r["operator"] == op]
        if not op_rows:
            print(f"{op}: no rows with distance_km")
            continue

        comparable = [r for r in op_rows if r["ratio"] != ""]
        no_osrm = [r for r in op_rows if r["ratio"] == ""]
        ratios = [r["ratio"] for r in comparable]

        if not ratios:
            print(f"{op}: {len(op_rows)} pairs, 0 with OSRM match")
            continue

        ratios_sorted = sorted(ratios)
        median = ratios_sorted[len(ratios_sorted) // 2]
        mean = sum(ratios) / len(ratios)
        within_10pct = sum(1 for r in ratios if OUTLIER_LOW <= r <= OUTLIER_HIGH) / len(ratios) * 100
        outliers = [r for r in comparable if r["ratio"] < OUTLIER_LOW or r["ratio"] > OUTLIER_HIGH]

        print(f"── {op} ──────────────────────────────")
        print(f"  pairs with source distance : {len(op_rows)}")
        print(f"  OSRM match                 : {len(comparable)} ({len(no_osrm)} no route)")
        print(f"  ratio  median={median:.3f}  mean={mean:.3f}  within±20%={within_10pct:.1f}%")
        print(f"  outliers (ratio<{OUTLIER_LOW} or >{OUTLIER_HIGH}): {len(outliers)}")
        if outliers:
            for r in sorted(outliers, key=lambda x: x["ratio"])[:10]:
                print(f"    ratio={r['ratio']:.3f}  {r['from_gare']} → {r['to_gare']}"
                      f"  src={r['source_km']}km  osrm={r['osrm_km']}km")
        print()


if __name__ == "__main__":
    main()
