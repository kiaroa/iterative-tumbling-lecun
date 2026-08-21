"""Phase 3: Overpass API toll booth check per gate.

One GET request per gate (avoids 406 from large batched POSTs).
Rate-limited by SLEEP_BETWEEN_REQUESTS to be polite to the public instance.

No API key required.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

import httpx

OVERPASS_INSTANCES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
RADIUS_M = 300
SLEEP_BETWEEN_REQUESTS = 1.5
OUT = Path("analysis/gate_validation/overpass_check.csv")

_HEADERS = {
    "User-Agent": "TollRouteGateValidation/1.0 (research project)",
    "Accept": "application/json",
}


def _query_one(lat: str, lon: str) -> int:
    ql = (
        f"[out:json][timeout:20];\n(\n"
        f"  node(around:{RADIUS_M},{lat},{lon})[barrier=toll_booth];\n"
        f"  node(around:{RADIUS_M},{lat},{lon})[highway=toll_gantry];\n"
        f"  node(around:{RADIUS_M},{lat},{lon})[toll=yes][highway];\n"
        f"  way(around:{RADIUS_M},{lat},{lon})[barrier=toll_booth];\n"
        f");\nout count;"
    )
    last_exc: Exception | None = None
    for url in OVERPASS_INSTANCES:
        try:
            resp = httpx.post(url, data={"data": ql}, headers=_HEADERS, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            return int(data.get("elements", [{}])[0].get("tags", {}).get("total", 0))
        except Exception as exc:
            last_exc = exc
            time.sleep(2.0)
    raise last_exc  # type: ignore


def check_overpass(
    classification_csv: Path = Path("analysis/gate_validation/gate_classification.csv"),
    limit: int = 0,
    out: Path = OUT,
) -> list[dict]:
    all_gates = list(csv.DictReader(open(classification_csv)))
    gates_with_coords = [g for g in all_gates if g["lat"].strip() and g["lon"].strip()]
    if limit:
        gates_with_coords = gates_with_coords[:limit]

    print(f"Phase 3: Overpass check for {len(gates_with_coords)} gates (1 req/gate, {SLEEP_BETWEEN_REQUESTS}s gap)")

    counts: dict[str, int] = {}
    for i, g in enumerate(gates_with_coords):
            try:
                counts[g["gare_id"]] = _query_one(g["lat"], g["lon"])
                print(".", end="", flush=True)
            except Exception as exc:
                counts[g["gare_id"]] = -1
                print(f"\n  gate {g['gare_id']} ({g['canonical_name']}): {exc}")
        if i < len(gates_with_coords) - 1:
            time.sleep(SLEEP_BETWEEN_REQUESTS)
    print()

    rows_out = []
    for g in all_gates:
        count = counts.get(g["gare_id"])
        rows_out.append({
            **g,
            "osm_toll_count": "" if count is None else count,
            "osm_no_toll_infra": "" if count is None else ("1" if count <= 0 else "0"),
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
