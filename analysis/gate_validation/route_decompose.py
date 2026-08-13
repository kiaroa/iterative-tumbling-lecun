"""Phase 5: on-route gate detection for anomalous OD pairs.

For pairs where source distance_km vs OSRM ratio is far from 1.0, routes between
the two gates, then finds which other operator gates lie within GATE_SNAP_M of the
route polyline. Gives the ordered list of physical gates the route passes through,
and attempts to decompose the journey into sub-fares.

Requires OSRM running and shapely/pyproj installed.
"""

from __future__ import annotations

import csv
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from pyproj import Transformer
from shapely.geometry import LineString, Point

OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "http://localhost:5000")
GATE_SNAP_M = 300       # metres: gate must be within this distance of route polyline
ANOMALY_THRESHOLD = 0.5  # abs(ratio - 1.0) > this → treat as anomalous
MAX_WORKERS = 4

OUT = Path("analysis/gate_validation/route_decomposition.csv")

# Lambert-93 — standard French projected CRS, metre units
_TRANSFORMER = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)


def _project(lat: float, lon: float) -> tuple[float, float]:
    x, y = _TRANSFORMER.transform(lon, lat)
    return x, y


def _route_geometry(client: httpx.Client, lat1: float, lon1: float, lat2: float, lon2: float) -> list[tuple[float, float]] | None:
    """Return list of (lon, lat) GeoJSON coordinates for the fastest route, or None."""
    resp = client.get(
        f"/route/v1/car/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok":
        return None
    return data["routes"][0]["geometry"]["coordinates"]  # list of [lon, lat]


def _gates_on_route(
    route_coords: list[tuple[float, float]],
    candidate_gates: list[dict],
) -> list[tuple[float, str, str]]:
    """Return [(fraction_along_route, gare_id, canonical_name)] for gates within GATE_SNAP_M."""
    projected = [_project(lat, lon) for lon, lat in route_coords]
    route_line = LineString(projected)

    on_route = []
    for g in candidate_gates:
        try:
            gx, gy = _project(float(g["lat"]), float(g["lon"]))
        except (ValueError, KeyError):
            continue
        pt = Point(gx, gy)
        dist = pt.distance(route_line)
        if dist <= GATE_SNAP_M:
            fraction = route_line.project(pt, normalized=True)
            on_route.append((fraction, g["gare_id"], g["canonical_name"]))

    on_route.sort()
    return on_route


def decompose(
    classification_csv: Path = Path("analysis/gate_validation/gate_classification.csv"),
    distance_csv: Path = Path("analysis/source_vs_osrm_distances.csv"),
    od_pairs_csv: Path = Path("od_pairs.csv"),
    gare_master_csv: Path = Path("gare_master.csv"),
    limit: int = 0,
    out: Path = OUT,
) -> list[dict]:
    # load gate coords
    gates_by_id: dict[str, dict] = {}
    for g in csv.DictReader(open(gare_master_csv)):
        gates_by_id[g["gare_id"]] = g

    # load fares index for decomposition lookup
    fares: dict[tuple[str, str, str], str] = {}  # (op, from_id, to_id) -> class1 fare
    for p in csv.DictReader(open(od_pairs_csv)):
        if p["class1"].strip():
            fares[(p["operator"], p["from_gare_id"], p["to_gare_id"])] = p["class1"]

    # load operator → gate list
    op_gates: dict[str, list[dict]] = {}
    for g in gates_by_id.values():
        for op in [o.strip() for o in g["operators"].split("|") if o.strip()]:
            op_gates.setdefault(op, []).append(g)

    # load anomalous pairs
    anomalous = []
    for row in csv.DictReader(open(distance_csv)):
        if not row["ratio"]:
            continue
        ratio = float(row["ratio"])
        if abs(ratio - 1.0) > ANOMALY_THRESHOLD:
            anomalous.append(row)
    if limit:
        anomalous = anomalous[:limit]

    print(f"Phase 5: route decomposition for {len(anomalous)} anomalous pairs")

    def _process(row: dict) -> dict:
        op = row["operator"]
        from_id, to_id = row["from_gare_id"], row["to_gare_id"]
        fg = gates_by_id.get(from_id)
        tg = gates_by_id.get(to_id)
        if not fg or not tg or not fg["lat"] or not tg["lat"]:
            return {**row, "intermediate_gates": "", "intermediate_fares_class1": "", "route_error": "no_coords"}

        try:
            with httpx.Client(base_url=OSRM_BASE_URL, timeout=15.0) as client:
                coords = _route_geometry(
                    client,
                    float(fg["lat"]), float(fg["lon"]),
                    float(tg["lat"]), float(tg["lon"]),
                )
        except Exception as exc:
            return {**row, "intermediate_gates": "", "intermediate_fares_class1": "", "route_error": str(exc)[:60]}

        if coords is None:
            return {**row, "intermediate_gates": "", "intermediate_fares_class1": "", "route_error": "no_route"}

        # candidates: all gates of the same operator, excluding from and to themselves
        candidates = [g for g in op_gates.get(op, []) if g["gare_id"] not in {from_id, to_id} and g["lat"].strip()]
        on_route = _gates_on_route(coords, candidates)

        # ordered intermediate gate names/ids
        inter_names = [name for _, _, name in on_route]
        inter_ids = [gid for _, gid, _ in on_route]

        # attempt fare decomposition: from_id → g1 → g2 → ... → to_id
        chain = [from_id] + inter_ids + [to_id]
        fares_chain: list[str] = []
        for i in range(len(chain) - 1):
            f = fares.get((op, chain[i], chain[i + 1]), "")
            fares_chain.append(f)

        return {
            **row,
            "intermediate_gates": "|".join(inter_names),
            "decomposed_fares_class1": "|".join(fares_chain),
            "route_error": "",
        }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        rows_out = list(pool.map(_process, anomalous))

    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows_out[0].keys()) if rows_out else []
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    with_inter = sum(1 for r in rows_out if r.get("intermediate_gates"))
    print(f"  processed: {len(rows_out)}, with intermediate gates: {with_inter}")
    return rows_out
