"""CLI for the toll-minimising route service (Phase 1c).

Usage: python3 -m tollroute <origin city> <destination city> --class 1

Builds the national multi-operator overlay graph, adds per-query origin/
destination access edges via OSRM, then runs Dijkstra and prints toll/
duration/distance for the result plus the gate chain used.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from tollroute import graph as graph_mod
from tollroute import routing
from tollroute.etl.build_national import DEFAULT_NATIONAL_DB_PATH as DEFAULT_DB_PATH
from tollroute.etl.snap_report import CLERMONT_FERRAND, MONTPELLIER
from tollroute.routing_engine import DEFAULT_FULL_URL, DEFAULT_TOLLFREE_URL, RoutingEngine

logger = logging.getLogger(__name__)

# City-centre coordinates covering the 5 named Phase 1b/1c test pairs plus
# Phase 4b's national multi-operator exit-criterion pair (Lille/Marseille).
# This is a small fixed gazetteer, not a general geocoder - Phase 6b adds
# free-text geocoding on top of the (unchanged) routing core this CLI drives.
GAZETTEER: dict[str, tuple[float, float]] = {
    "dijon": (47.3220, 5.0415),
    "lyon": (45.7640, 4.8357),
    "paris": (48.8566, 2.3522),
    "macon": (46.3069, 4.8281),
    "mâcon": (46.3069, 4.8281),
    "beaune": (47.0206, 4.8404),
    "villefranche": (45.9895, 4.7178),
    "clermont-ferrand": CLERMONT_FERRAND,
    "montpellier": MONTPELLIER,
    "lille": (50.6292, 3.0573),
    "marseille": (43.2965, 5.3698),
}


def _normalise(name: str) -> str:
    return name.strip().lower()


def resolve_city(name: str) -> tuple[float, float]:
    key = _normalise(name)
    if key not in GAZETTEER:
        known = ", ".join(sorted(GAZETTEER))
        raise SystemExit(f"unknown city {name!r}; known cities: {known}")
    return GAZETTEER[key]


def run(
    origin_name: str,
    dest_name: str,
    vehicle_class: int,
    db_path: Path = DEFAULT_DB_PATH,
    engine: RoutingEngine | None = None,
) -> routing.Route:
    origin_coords = resolve_city(origin_name)
    dest_coords = resolve_city(dest_name)

    own_engine = engine is None
    if own_engine:
        engine = RoutingEngine()
    conn = sqlite3.connect(db_path)
    try:
        g = graph_mod.build_graph(conn)
        origin_node, dest_node = graph_mod.add_access_edges(g, engine, origin_coords, dest_coords)
        return routing.find_route(g, origin_node, dest_node, vehicle_class)
    finally:
        conn.close()
        if own_engine:
            engine.close()


def format_route(route: routing.Route, origin_name: str, dest_name: str, vehicle_class: int) -> str:
    gate_chain: list[int] = []
    for node in route.nodes:
        if node.gare_id < 0:
            continue  # synthetic origin/destination node
        if not gate_chain or gate_chain[-1] != node.gare_id:
            gate_chain.append(node.gare_id)

    lines = [
        f"{origin_name.title()} -> {dest_name.title()} (class {vehicle_class})",
        f"  toll:     EUR {route.toll_eur:.2f}",
        f"  duration: {route.duration_s / 60:.1f} min",
        f"  distance: {route.distance_m / 1000:.1f} km",
        f"  gates:    {' -> '.join(str(g) for g in gate_chain) or '(direct, no gates)'}",
    ]
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("destination")
    parser.add_argument(
        "--class", dest="vehicle_class", type=int, default=1, choices=range(1, 6)
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--full-url", default=DEFAULT_FULL_URL)
    parser.add_argument("--tollfree-url", default=DEFAULT_TOLLFREE_URL)
    args = parser.parse_args()

    engine = RoutingEngine(full_url=args.full_url, tollfree_url=args.tollfree_url)
    try:
        route = run(args.origin, args.destination, args.vehicle_class, args.db, engine=engine)
    finally:
        engine.close()
    print(format_route(route, args.origin, args.destination, args.vehicle_class))


if __name__ == "__main__":
    main()
