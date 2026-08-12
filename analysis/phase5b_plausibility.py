"""Phase 5b: run the 10 plausibility routes against a live `tollroute.api`
instance and print toll/duration/distance for each, plus the OSRM baseline
(direct route, tolls allowed, ignoring the toll-minimising graph) for
comparison.

Usage:
    python3 -m uvicorn tollroute.api:app --host 127.0.0.1 --port 8000 &
    python3 analysis/phase5b_plausibility.py

See reports/phase5b_plausibility.md for the findings this script's output
fed into, including the independent-validator cross-check (spec: HERE/TomTom
API; no key available in this build environment, substituted per that
report's documented reasoning).
"""

from __future__ import annotations

import json
import sys

import httpx

# (origin name, destination name, origin (lat, lon), destination (lat, lon),
# note on operator/region covered). The first 3 are the spec-mandated pairs
# (iterative-tumbling-lecun.md Phase 5b); the other 7 span the remaining
# operators/regions.
ROUTES: list[tuple[str, str, tuple[float, float], tuple[float, float], str]] = [
    ("Paris", "Lyon", (48.8566, 2.3522), (45.7640, 4.8357),
     "A6, APRR - core motorway vs free N6/N7"),
    ("Paris", "Bordeaux", (48.8566, 2.3522), (44.8378, -0.5792),
     "A10, Cofiroute - competitive free N10"),
    ("Clermont-Ferrand", "Montpellier", (45.7772, 3.0870), (43.6119, 3.8772),
     "A75, mostly untolled + Millau viaduct (CEVM, not a dataset operator)"),
    ("Paris", "Lille", (48.8566, 2.3522), (50.6292, 3.0573),
     "A1, Sanef - short/flat northern corridor"),
    ("Paris", "Marseille", (48.8566, 2.3522), (43.2965, 5.3698),
     "A6/A7, APRR+ASFC combo - long N-S multi-operator"),
    ("Nice", "Marseille", (43.7102, 7.2620), (43.2965, 5.3698),
     "A8, Escota - coastal, dense interchanges"),
    ("Bordeaux", "Toulouse", (44.8378, -0.5792), (43.6047, 1.4442),
     "A62, ASFC - south-west corridor"),
    ("Lyon", "Chamonix", (45.7640, 4.8357), (45.9237, 6.8694),
     "A40, ATMB - alpine, smallest operator in the set"),
    ("Strasbourg", "Paris", (48.5734, 7.7521), (48.8566, 2.3522),
     "A4, Sanef/APRR - east-west"),
    ("Calais", "Reims", (50.9513, 1.8587), (49.2583, 4.0317),
     "A26, Sanef - far north"),
]


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    results = []
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        for origin_name, dest_name, origin, dest, note in ROUTES:
            r = client.get("/route", params={
                "origin_lat": origin[0], "origin_lon": origin[1],
                "destination_lat": dest[0], "destination_lon": dest[1],
                "vehicle_class": 1,
            })
            r.raise_for_status()
            results.append({
                "origin_name": origin_name, "dest_name": dest_name, "note": note,
                "response": r.json(),
            })

    for item in results:
        resp = item["response"]
        fastest = next(o for o in resp["options"] if "fastest" in o["labels"])
        cheapest = next((o for o in resp["options"] if "cheapest" in o["labels"]), fastest)
        print(
            f"{item['origin_name']:>17} -> {item['dest_name']:<16} | "
            f"fastest EUR{fastest['toll_eur']:>6.2f} {fastest['duration_s'] / 60:>6.1f}min "
            f"{fastest['distance_m'] / 1000:>6.1f}km gates={fastest['gates']}"
        )
        if cheapest is not fastest:
            print(
                f"{'':>17}    {'':<16} | cheapest EUR{cheapest['toll_eur']:>6.2f} "
                f"{cheapest['duration_s'] / 60:>6.1f}min {cheapest['distance_m'] / 1000:>6.1f}km "
                f"(+{cheapest['extra_minutes']:.1f}min, save EUR{cheapest['saving_vs_fastest_eur']:.2f})"
            )
        baseline = resp["baseline"]
        print(f"{'':>17}    baseline {baseline['duration_s'] / 60:>6.1f}min {baseline['distance_m'] / 1000:>6.1f}km")

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
