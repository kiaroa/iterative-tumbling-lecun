"""Phase 3: Overpass API toll booth check per gate.

Queries OSM for barrier=toll_booth / highway=toll_gantry within 300m of each gate.
Batches up to 50 gates per Overpass request to minimise round-trips.

No API key required. Rate-limited by 1s sleep between batches.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
RADIUS_M = 300
BATCH_SIZE = 50
SLEEP_BETWEEN_BATCHES = 1.5  # seconds
OUT = Path("analysis/gate_validation/overpass_check.csv")


def _overpass_query(gates: list[dict]) -> dict[str, int]:
    """Returns {gare_id: count_of_toll_features_within_radius}."""
    parts = []
    for g in gates:
        lat, lon = g["lat"], g["lon"]
        parts.append(
            f'node(around:{RADIUS_M},{lat},{lon})[barrier=toll_booth];'
            f'node(around:{RADIUS_M},{lat},{lon})[highway=toll_gantry];'
            f'node(around:{RADIUS_M},{lat},{lon})[toll=yes][highway];'
            f'way(around:{RADIUS_M},{lat},{lon})[barrier=toll_booth];'
        )
    ql = "[out:json][timeout:30];\n(\n" + "\n".join(parts) + "\n);\nout center;"

    resp = httpx.post(OVERPASS_URL, data={"data": ql}, timeout=60.0)
    resp.raise_for_status()
    elements = resp.json().get("elements", [])

    # map each returned element back to the nearest gate
    counts: dict[str, int] = {g["gare_id"]: 0 for g in gates}
    for elem in elements:
        elat = elem.get("lat") or elem.get("center", {}).get("lat")
        elon = elem.get("lon") or elem.get("center", {}).get("lon")
        if elat is None:
            continue
        # find closest gate within radius
        best_gid, best_d = None, float("inf")
        for g in gates:
            dlat = float(g["lat"]) - elat
            dlon = float(g["lon"]) - elon
            d2 = dlat * dlat + dlon * dlon
            if d2 < best_d:
                best_d, best_gid = d2, g["gare_id"]
        if best_gid:
            counts[best_gid] += 1
    return counts


def check_overpass(
    classification_csv: Path = Path("analysis/gate_validation/gate_classification.csv"),
    limit: int = 0,
    out: Path = OUT,
) -> list[dict]:
    all_gates = list(csv.DictReader(open(classification_csv)))
    gates_with_coords = [g for g in all_gates if g["lat"].strip() and g["lon"].strip()]
    if limit:
        gates_with_coords = gates_with_coords[:limit]

    print(f"Phase 3: Overpass check for {len(gates_with_coords)} gates ({BATCH_SIZE}/batch)")

    all_counts: dict[str, int] = {}
    batches = [gates_with_coords[i:i + BATCH_SIZE] for i in range(0, len(gates_with_coords), BATCH_SIZE)]
    for bi, batch in enumerate(batches):
        print(f"  batch {bi + 1}/{len(batches)} ({len(batch)} gates) ...", end=" ", flush=True)
        try:
            counts = _overpass_query(batch)
            all_counts.update(counts)
            print("ok")
        except Exception as exc:
            print(f"ERROR: {exc}")
            for g in batch:
                all_counts[g["gare_id"]] = -1  # -1 = query failed
        if bi < len(batches) - 1:
            time.sleep(SLEEP_BETWEEN_BATCHES)

    # merge back into all gates
    rows_out = []
    for g in all_gates:
        count = all_counts.get(g["gare_id"])
        rows_out.append({
            **g,
            "osm_toll_count": "" if count is None else count,
            "osm_no_toll_infra": "" if count is None else ("1" if count == 0 else "0"),
        })

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    checked = [r for r in rows_out if r["osm_toll_count"] not in ("", "-1")]
    no_infra = sum(1 for r in checked if r["osm_no_toll_infra"] == "1")
    print(f"  checked: {len(checked)}, no OSM toll infra: {no_infra}")
    return rows_out
