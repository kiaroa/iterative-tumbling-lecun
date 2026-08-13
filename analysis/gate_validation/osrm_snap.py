"""Phase 2: OSRM /nearest snap check per gate.

For each gate, hits OSRM /nearest to get snap distance and road classes.
Adds snap_distance_m, snap_toll, snap_motorway columns.

Requires OSRM running at OSRM_BASE_URL (default http://localhost:5000).
"""

from __future__ import annotations

import csv
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "http://localhost:5000")
MAX_WORKERS = 8
OUT = Path("analysis/gate_validation/osrm_snap.csv")


def _snap_gate(client: httpx.Client, gare_id: str, lat: str, lon: str) -> dict:
    try:
        resp = client.get(f"/nearest/v1/car/{lon},{lat}?number=1")
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "Ok" or not data.get("waypoints"):
            return {"gare_id": gare_id, "snap_distance_m": "", "snap_toll": "", "snap_motorway": "", "snap_error": "no_waypoint"}
        wp = data["waypoints"][0]
        snap_dist = wp.get("distance", "")

        # get road classes via a zero-distance route from the snapped point
        snap_loc = wp["location"]  # [lon, lat]
        snap_lon, snap_lat = snap_loc
        route_resp = client.get(
            f"/route/v1/car/{snap_lon},{snap_lat};{snap_lon},{snap_lat}"
            "?steps=true&overview=false"
        )
        route_resp.raise_for_status()
        route_data = route_resp.json()
        classes: set[str] = set()
        if route_data.get("code") == "Ok":
            for leg in route_data.get("routes", [{}])[0].get("legs", []):
                for step in leg.get("steps", []):
                    for inter in step.get("intersections", []):
                        classes.update(inter.get("classes", []))

        return {
            "gare_id": gare_id,
            "snap_distance_m": round(float(snap_dist), 1) if snap_dist != "" else "",
            "snap_toll": "1" if "toll" in classes else "0",
            "snap_motorway": "1" if ("motorway" in classes or "trunk" in classes) else "0",
            "snap_error": "",
        }
    except Exception as exc:
        return {"gare_id": gare_id, "snap_distance_m": "", "snap_toll": "", "snap_motorway": "", "snap_error": str(exc)[:80]}


def check_snap(
    classification_csv: Path = Path("analysis/gate_validation/gate_classification.csv"),
    limit: int = 0,
    out: Path = OUT,
) -> list[dict]:
    gates = [r for r in csv.DictReader(open(classification_csv)) if r["lat"].strip() and r["lon"].strip()]
    if limit:
        gates = gates[:limit]

    print(f"Phase 2: snapping {len(gates)} gates via OSRM at {OSRM_BASE_URL}")

    with httpx.Client(base_url=OSRM_BASE_URL, timeout=10.0) as client:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            results = list(pool.map(
                lambda g: _snap_gate(client, g["gare_id"], g["lat"], g["lon"]),
                gates,
            ))

    snap_map = {r["gare_id"]: r for r in results}

    # merge back into all gates (gates outside limit get empty values)
    all_gates = list(csv.DictReader(open(classification_csv)))
    rows_out = []
    for g in all_gates:
        snap = snap_map.get(g["gare_id"], {"snap_distance_m": "", "snap_toll": "", "snap_motorway": "", "snap_error": "skipped"})
        rows_out.append({**g, **snap})

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    not_toll = sum(1 for r in results if r["snap_toll"] == "0" and not r["snap_error"])
    far = sum(1 for r in results if r["snap_distance_m"] and float(r["snap_distance_m"]) > 200)
    errors = sum(1 for r in results if r["snap_error"])
    print(f"  snap >200m:    {far}")
    print(f"  not on toll road: {not_toll}")
    print(f"  errors:        {errors}")
    return rows_out
