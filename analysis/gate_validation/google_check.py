"""Phase 4: Google Places nearbySearch per gate.

Requires GOOGLE_MAPS_KEY environment variable.
Searches for toll infrastructure within 300m of each gate coordinate.
Uses difflib to fuzzy-match gate name against Google result names.
"""

from __future__ import annotations

import csv
import difflib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

PLACES_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
RADIUS_M = 300
MAX_WORKERS = 5
NAME_MATCH_THRESHOLD = 0.45
OUT = Path("analysis/gate_validation/google_check.csv")

KEYWORDS = ["péage", "toll"]


def _normalise(name: str) -> str:
    import unicodedata
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    return name.lower().strip()


def _search_gate(
    client: httpx.Client,
    key: str,
    gare_id: str,
    canonical_name: str,
    lat: str,
    lon: str,
) -> dict:
    best_name, best_score, best_dist = "", 0.0, None
    found = False

    for keyword in KEYWORDS:
        try:
            resp = client.get(
                PLACES_URL,
                params={
                    "location": f"{lat},{lon}",
                    "radius": RADIUS_M,
                    "keyword": keyword,
                    "key": key,
                },
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except Exception as exc:
            return {
                "gare_id": gare_id,
                "google_place_found": "",
                "google_place_name": "",
                "google_place_dist_m": "",
                "google_error": str(exc)[:80],
            }

        gate_norm = _normalise(canonical_name)
        for place in results:
            place_name = place.get("name", "")
            score = difflib.SequenceMatcher(None, gate_norm, _normalise(place_name)).ratio()
            if score > best_score:
                best_score = score
                best_name = place_name
                loc = place.get("geometry", {}).get("location", {})
                if loc:
                    import math
                    dlat = math.radians(float(loc["lat"]) - float(lat))
                    dlon = math.radians(float(loc["lng"]) - float(lon))
                    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(float(lat))) * math.cos(math.radians(float(loc["lat"]))) * math.sin(dlon / 2) ** 2
                    best_dist = round(6371000 * 2 * math.asin(math.sqrt(a)))
                found = True

    matched = found and best_score >= NAME_MATCH_THRESHOLD
    return {
        "gare_id": gare_id,
        "google_place_found": "1" if matched else "0",
        "google_place_name": best_name,
        "google_place_dist_m": best_dist if best_dist is not None else "",
        "google_error": "",
    }


def check_google(
    classification_csv: Path = Path("analysis/gate_validation/gate_classification.csv"),
    limit: int = 0,
    out: Path = OUT,
) -> list[dict]:
    key = os.environ.get("GOOGLE_MAPS_KEY", "")
    if not key:
        print("Phase 4: GOOGLE_MAPS_KEY not set — skipping")
        return []

    all_gates = list(csv.DictReader(open(classification_csv)))
    gates_with_coords = [g for g in all_gates if g["lat"].strip() and g["lon"].strip()]
    if limit:
        gates_with_coords = gates_with_coords[:limit]

    print(f"Phase 4: Google Places check for {len(gates_with_coords)} gates")

    with httpx.Client(timeout=15.0) as client:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            results = list(pool.map(
                lambda g: _search_gate(client, key, g["gare_id"], g["canonical_name"], g["lat"], g["lon"]),
                gates_with_coords,
            ))

    result_map = {r["gare_id"]: r for r in results}

    rows_out = []
    for g in all_gates:
        info = result_map.get(g["gare_id"], {
            "google_place_found": "",
            "google_place_name": "",
            "google_place_dist_m": "",
            "google_error": "skipped",
        })
        rows_out.append({**g, **{k: v for k, v in info.items() if k != "gare_id"}})

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    checked = [r for r in results if not r["google_error"]]
    matched = sum(1 for r in checked if r["google_place_found"] == "1")
    errors = sum(1 for r in results if r["google_error"])
    print(f"  checked: {len(checked)}, matched: {matched}, no match: {len(checked)-matched}, errors: {errors}")
    return rows_out
