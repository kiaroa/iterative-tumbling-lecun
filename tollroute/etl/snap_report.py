"""Snap every APRR gate to OSRM's road network and verify the 5 named test pairs.

Run as: python3 -m tollroute.etl.snap_report

For every APRR gate with coordinates, calls OSRM `/nearest`, records the snapped
position and distance, and writes the result back into `gates.snap_lat` /
`snap_lon` / `snap_distance_m`. Gates snapping >200 m are flagged in the report,
not dropped — that curation is Phase 2d's job (`suspect_gates`), not this
snapper's.

Also confirms the spec's 5 named APRR test pairs (iterative-tumbling-lecun.md
Phase 1b) exist with non-zero prices and that OSRM returns a distinct toll-free
route for each, ahead of Phase 1c's overlay graph.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "tollroute" / "db" / "tollroute.sqlite"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase1b_snapping.md"
DEFAULT_OSRM_BASE_URL = "http://localhost:5000"

SNAP_FLAG_THRESHOLD_M = 200.0

# The 5 named test pairs from iterative-tumbling-lecun.md Phase 1b, resolved to
# concrete APRR gare_ids. Gates 1, 2 and 4-5 are genuine APRR fare-matrix pairs
# (from_gare_id -> to_gare_id in `fares`), each on the A6 corridor with a
# well-known parallel N-road. Pair 3 (Clermont-Ferrand -> Montpellier) is a
# deliberate edge case: A75 south of Clermont is an untolled state motorway, so
# no APRR gare exists in that direction at all (confirmed: no CLERMONT-BARRIERE
# fare row heads south; every APRR fare from Clermont-Ferrand runs north towards
# Lyon/Bourgogne). That pair is therefore checked via OSRM only, using city-centre
# coordinates, and is expected to have no od_pairs price and a near-identical
# tolled/toll-free route (the point of the edge case, per the spec's own
# parenthetical "A75 is free motorway").
CLERMONT_FERRAND = (45.7772, 3.0870)
MONTPELLIER = (43.6119, 3.8772)


@dataclass
class FareGatePair:
    label: str
    note: str
    from_gare_id: int
    to_gare_id: int


@dataclass
class GeoOnlyPair:
    label: str
    note: str
    origin: tuple[float, float]  # (lat, lon)
    destination: tuple[float, float]


FARE_TEST_PAIRS = [
    FareGatePair(
        "1. Dijon -> Lyon (A6 vs N6/N7)",
        "DIJON SUD -> VILLEFRANCHE NORD: last APRR gate on A6 before the "
        "toll-free approach into Lyon.",
        269,
        930,
    ),
    FareGatePair(
        "2. Paris -> Lyon (A6 vs N6)",
        "LA FOLIE-B/PARIS -> VILLEFRANCHE NORD: the full A6 Paris-Lyon run.",
        393,
        930,
    ),
    FareGatePair(
        "4. Dijon -> Macon (medium-distance, parallel N6)",
        "DIJON SUD -> MACON SUD: mid-length A6/N6 corridor segment.",
        269,
        495,
    ),
    FareGatePair(
        "5. Beaune -> Macon (medium-distance, parallel N6)",
        "BEAUNE SUD -> MACON NORD: shorter A6/N6 corridor segment.",
        96,
        494,
    ),
]

GEO_ONLY_TEST_PAIR = GeoOnlyPair(
    "3. Clermont-Ferrand -> Montpellier (A75 free motorway - edge case)",
    "No APRR gare exists south of Clermont-Ferrand: A75 is an untolled state "
    "motorway, so this pair is checked via OSRM city-centre coordinates only, "
    "not an od_pairs fare lookup. Expected result: no APRR price applies, and "
    "the tolled/toll-free routes should be near-identical (that is the point "
    "of the edge case).",
    CLERMONT_FERRAND,
    MONTPELLIER,
)


def osrm_nearest(client: httpx.Client, lat: float, lon: float) -> dict:
    resp = client.get(f"/nearest/v1/car/{lon},{lat}")
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != "Ok":
        raise RuntimeError(f"OSRM /nearest failed for ({lat},{lon}): {data}")
    return data["waypoints"][0]


def osrm_route(
    client: httpx.Client, origin: tuple[float, float], destination: tuple[float, float], exclude_toll: bool
) -> dict:
    o_lat, o_lon = origin
    d_lat, d_lon = destination
    params = "overview=false"
    if exclude_toll:
        params += "&exclude=toll"
    resp = client.get(f"/route/v1/car/{o_lon},{o_lat};{d_lon},{d_lat}?{params}")
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != "Ok":
        raise RuntimeError(f"OSRM /route failed for {origin}->{destination}: {data}")
    return data["routes"][0]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, a**0.5))


def snap_all_gates(conn: sqlite3.Connection, client: httpx.Client) -> list[dict]:
    gates = conn.execute(
        "SELECT gare_id, canonical_name, lat, lon FROM gates WHERE lat IS NOT NULL AND lon IS NOT NULL"
    ).fetchall()

    results = []
    for gare_id, canonical_name, lat, lon in gates:
        waypoint = osrm_nearest(client, lat, lon)
        snap_lon, snap_lat = waypoint["location"]
        snap_distance_m = haversine_m(lat, lon, snap_lat, snap_lon)
        conn.execute(
            "UPDATE gates SET snap_lat = ?, snap_lon = ?, snap_distance_m = ? WHERE gare_id = ?",
            (snap_lat, snap_lon, snap_distance_m, gare_id),
        )
        results.append(
            {
                "gare_id": gare_id,
                "canonical_name": canonical_name,
                "lat": lat,
                "lon": lon,
                "snap_lat": snap_lat,
                "snap_lon": snap_lon,
                "snap_distance_m": snap_distance_m,
            }
        )
    conn.commit()

    no_coords = conn.execute(
        "SELECT COUNT(*) FROM gates WHERE lat IS NULL OR lon IS NULL"
    ).fetchone()[0]
    if no_coords:
        logger.warning("%d APRR gates have no lat/lon and were not snapped", no_coords)

    return results


def verify_fare_pair(conn: sqlite3.Connection, client: httpx.Client, pair: FareGatePair) -> dict:
    fare_row = conn.execute(
        "SELECT from_gare, to_gare, distance_km, class1 FROM fares "
        "WHERE from_gare_id = ? AND to_gare_id = ?",
        (pair.from_gare_id, pair.to_gare_id),
    ).fetchone()
    if fare_row is None:
        raise RuntimeError(
            f"{pair.label}: no APRR fare row for gate {pair.from_gare_id} -> {pair.to_gare_id}"
        )
    from_gare, to_gare, distance_km, class1 = fare_row
    if class1 is None or class1 == 0.0:
        raise RuntimeError(f"{pair.label}: fare row has non-positive class1 price ({class1})")

    origin = conn.execute(
        "SELECT lat, lon FROM gates WHERE gare_id = ?", (pair.from_gare_id,)
    ).fetchone()
    destination = conn.execute(
        "SELECT lat, lon FROM gates WHERE gare_id = ?", (pair.to_gare_id,)
    ).fetchone()

    tolled = osrm_route(client, origin, destination, exclude_toll=False)
    toll_free = osrm_route(client, origin, destination, exclude_toll=True)
    distinct = (
        tolled["distance"] != toll_free["distance"] or tolled["duration"] != toll_free["duration"]
    )

    return {
        "label": pair.label,
        "note": pair.note,
        "from_gare": from_gare,
        "to_gare": to_gare,
        "od_distance_km": distance_km,
        "od_price_eur": class1,
        "tolled_distance_m": tolled["distance"],
        "tolled_duration_s": tolled["duration"],
        "toll_free_distance_m": toll_free["distance"],
        "toll_free_duration_s": toll_free["duration"],
        "distinct_route": distinct,
    }


def verify_geo_only_pair(client: httpx.Client, pair: GeoOnlyPair) -> dict:
    tolled = osrm_route(client, pair.origin, pair.destination, exclude_toll=False)
    toll_free = osrm_route(client, pair.origin, pair.destination, exclude_toll=True)
    distinct = (
        tolled["distance"] != toll_free["distance"] or tolled["duration"] != toll_free["duration"]
    )

    return {
        "label": pair.label,
        "note": pair.note,
        "od_distance_km": None,
        "od_price_eur": None,
        "tolled_distance_m": tolled["distance"],
        "tolled_duration_s": tolled["duration"],
        "toll_free_distance_m": toll_free["distance"],
        "toll_free_duration_s": toll_free["duration"],
        "distinct_route": distinct,
    }


def render_report(
    snap_results: list[dict], fare_pair_results: list[dict], geo_only_result: dict
) -> str:
    flagged = [r for r in snap_results if r["snap_distance_m"] > SNAP_FLAG_THRESHOLD_M]
    flagged.sort(key=lambda r: r["snap_distance_m"], reverse=True)

    lines = ["# Phase 1b — APRR gate snapping and test-pair verification", ""]
    lines.append(
        f"Snapped {len(snap_results)} APRR gates against OSRM `/nearest` "
        f"(regional bfc-ara extract). {len(flagged)} gates snapped further than "
        f"{SNAP_FLAG_THRESHOLD_M:.0f} m from their `gare_master.csv` coordinates."
    )
    lines.append("")
    lines.append(
        f"**Note on the {len(flagged)}-gate flag count:** the OSRM instance running against "
        "this report only serves the Bourgogne-Franche-Comte + Auvergne-Rhone-Alpes regional "
        "extract (Phase 1a); APRR's network extends well beyond that region (e.g. towards "
        "Paris, Tours, Reims, Verdun). Gates outside the loaded extract snap to the nearest "
        "in-extract road, tens to hundreds of km away — that is an extract-coverage artefact, "
        "not a geocoding error. The national OSRM build (Phase 3a) is required before this "
        "flag list is meaningful as a data-quality signal; until then, treat only the smaller "
        "in-region snap distances as informative."
    )
    lines.append("")
    lines.append("## Gates flagged (>200 m snap distance)")
    lines.append("")
    if flagged:
        lines.append("| gare_id | name | snap distance (m) |")
        lines.append("|---|---|---|")
        for r in flagged:
            lines.append(f"| {r['gare_id']} | {r['canonical_name']} | {r['snap_distance_m']:.1f} |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## 5 named test pairs (iterative-tumbling-lecun.md Phase 1b)")
    lines.append("")
    for r in fare_pair_results:
        lines.append(f"### {r['label']}")
        lines.append("")
        lines.append(r["note"])
        lines.append("")
        lines.append(
            f"- APRR fare: `{r['from_gare']}` -> `{r['to_gare']}`, "
            f"distance_km={r['od_distance_km']}, class1=€{r['od_price_eur']}"
        )
        lines.append(
            f"- OSRM tolled route: distance={r['tolled_distance_m']:.0f} m, "
            f"duration={r['tolled_duration_s']:.0f} s"
        )
        lines.append(
            f"- OSRM toll-free route: distance={r['toll_free_distance_m']:.0f} m, "
            f"duration={r['toll_free_duration_s']:.0f} s"
        )
        lines.append(
            f"- Distinct toll-free alternative: {'YES' if r['distinct_route'] else 'NO'}"
        )
        lines.append("")

    r = geo_only_result
    lines.append(f"### {r['label']}")
    lines.append("")
    lines.append(r["note"])
    lines.append("")
    lines.append("- APRR fare: none (A75 carries no APRR toll gate south of Clermont-Ferrand)")
    lines.append(
        f"- OSRM tolled route: distance={r['tolled_distance_m']:.0f} m, "
        f"duration={r['tolled_duration_s']:.0f} s"
    )
    lines.append(
        f"- OSRM toll-free route: distance={r['toll_free_distance_m']:.0f} m, "
        f"duration={r['toll_free_duration_s']:.0f} s"
    )
    lines.append(
        f"- Route changes under exclude=toll: {'YES' if r['distinct_route'] else 'NO'} "
        "(NO is expected/consistent with A75 being untolled end-to-end on this corridor; "
        "YES would mean a tolled alternative exists elsewhere on the route)"
    )
    lines.append("")

    return "\n".join(lines) + "\n"


def run(
    db_path: Path = DEFAULT_DB_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    osrm_base_url: str = DEFAULT_OSRM_BASE_URL,
) -> str:
    conn = sqlite3.connect(db_path)
    try:
        with httpx.Client(base_url=osrm_base_url, timeout=10.0) as client:
            snap_results = snap_all_gates(conn, client)
            fare_pair_results = [verify_fare_pair(conn, client, p) for p in FARE_TEST_PAIRS]
            geo_only_result = verify_geo_only_pair(client, GEO_ONLY_TEST_PAIR)
    finally:
        conn.close()

    report = render_report(snap_results, fare_pair_results, geo_only_result)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)

    flagged_count = sum(1 for r in snap_results if r["snap_distance_m"] > SNAP_FLAG_THRESHOLD_M)
    logger.info(
        "snapped %d gates (%d flagged >%.0fm); report written to %s",
        len(snap_results),
        flagged_count,
        SNAP_FLAG_THRESHOLD_M,
        report_path,
    )
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--osrm-base-url", default=DEFAULT_OSRM_BASE_URL)
    args = parser.parse_args()
    run(db_path=args.db, report_path=args.report, osrm_base_url=args.osrm_base_url)


if __name__ == "__main__":
    main()
