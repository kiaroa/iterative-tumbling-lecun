"""Precompute per-gate, per-direction toll-free access anchors (Phase 5b-follow-up-1,
direction split added in Phase 5b-follow-up-1-continued).

Run as: python3 -m tollroute.etl.access_anchors

**Two bugs found in the original (Phase 5b-follow-up-1) implementation, both fixed here.**

1. This module's own docstring claimed the anchor search "walks backward along a real
   route['s] geometry" from a reference city to the gate - deliberately chosen over probing
   outward from `/nearest`, which the docstring says was "tried first and rejected" because
   motorways are oneway/divided and `/nearest`'s raw nearest-edge snap isn't direction-aware,
   so a geometrically-close candidate can sit on the *opposite* carriageway and force a huge
   plain-driving detour to actually reach. The shipped code never implemented that: `find_anchor`
   called `_nearest_tollfree_candidates` (`/nearest?exclude=toll`), exactly the rejected approach.
   Verified directly against the live national OSRM instance for Fleury-en-Bière (gare_id
   302/303, Paris->Lyon's nearer, Ulys-matching A6 entry gate, the flagship case Phase
   5b-follow-up-1's own "done when" was written around): its nearest `/nearest` candidate (~72 m
   away) has a 30 km plain apron back to the gate (opposite-carriageway detour), while walking
   backward along the real Paris->gate route's own geometry finds a toll-free-reachable point
   only ~350 m from the gate. This module now does what the old docstring always said it did.

2. The gate-needs-an-anchor / candidate-is-reachable check was direction-blind: it only ever
   tested "candidate -> reference" (`sources=candidate, destinations=references`), i.e. the
   *exit* direction, and the single resulting anchor was then reused for `add_access_edges`'s
   *entry* legs too (`add_access_edges` queries the same anchor for both `entry_coords` and
   `exit_coords` - see `tollroute/graph.py`). Verified directly: of 8 gates sampled at random
   from the 67 anchors Phase 5b-follow-up-1 shipped, 7 are NOT toll-free-reachable in the entry
   direction (reference -> anchor) despite being reachable in the exit direction they were
   validated against - meaning most of that iteration's anchors likely never worked for entry
   access edges at all, silently falling back to "no route -> omitted" for entry only. This
   module now finds and validates an anchor separately per direction; `access_anchors` has one
   row per (gare_id, direction) that needed one (schema: `tollroute/db/schema.sql`).

**What this script does, per gate and per direction ('entry': reference -> gate,
'exit': gate -> reference).** First checks whether the gate's own coordinate is already
toll-free-reachable, in that direction, from any of `REFERENCE_POINTS` (widely-spread city
centres, reused from `tollroute.cli.GAZETTEER`/`analysis/phase5b_plausibility.py`). If so,
nothing to do for that direction - `add_access_edges` already handles it.

Otherwise, for each reference city (cheapest-first: stop as soon as one produces an apron
under `GOOD_ENOUGH_APRON_M`, otherwise keep the smallest apron found across all of them):
fetch the real plain (toll allowed) route between the reference and the gate, in the query
direction, with full geometry - a real, direction-correct driving path by construction.
Starting from the gate end of that geometry and walking outward (bounded to
`APRON_REJECT_DISTANCE_M` of cumulative route distance - beyond that, any candidate would be
rejected anyway), batch-test every point in one `exclude=toll` OSRM `/table` call for
reachability in the query direction; the first (nearest-to-gate) reachable point becomes the
anchor. `add_access_edges` then queries that anchor instead of the gate's own coordinate for
its `exclude=toll` batch call, adding the real plain-route apron leg (anchor<->gate, in the
right direction) on top - safe because `APRON_REJECT_DISTANCE_M` bounds it to a short local
hop, so it cannot resurrect the Phase 1c free-ride bug (`exclude=toll` on the full-length
access edge, unchanged here, is what fixed that).
"""

from __future__ import annotations

import argparse
import logging
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tollroute.etl.build_national import DEFAULT_NATIONAL_DB_PATH
from tollroute.graph import OSRM_TABLE_MAX_DIMENSION
from tollroute.routing_engine import DEFAULT_FULL_URL, DEFAULT_TOLLFREE_URL, RoutingEngine

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "tollroute" / "db" / "schema.sql"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase5b_followup1_continued_access_anchors.md"

Direction = Literal["entry", "exit"]

# Widely-spread city centres (N/S/E/W/centre) already used elsewhere in this project
# (tollroute.cli.GAZETTEER, analysis/phase5b_plausibility.py) without incident - reused here
# rather than picked fresh so "reachable from a reference city" means the same thing this
# project already trusts it to mean. A gate only needs to reach (or be reached from) ONE of
# these to be judged not-an-isolated-pocket.
REFERENCE_POINTS: list[tuple[float, float]] = [
    (48.8566, 2.3522),  # Paris
    (45.7640, 4.8357),  # Lyon
    (43.2965, 5.3698),  # Marseille
    (50.6292, 3.0573),  # Lille
    (44.8378, -0.5792),  # Bordeaux
    (48.5734, 7.7521),  # Strasbourg
]

# A candidate anchor whose apron leg is at or under this stops the per-reference search
# early (this reference's candidate is good enough - no need to try the rest). Fleury-en-
# Bière's real last-mile anchor (~350 m) comfortably clears this.
GOOD_ENOUGH_APRON_M = 500.0

# A candidate whose plain apron leg exceeds this is rejected outright (search continues
# along the route, then to the next reference), not just logged. 2 km comfortably covers
# every genuine last-mile apron seen in testing while rejecting anything that would start
# to resemble a real regional detour rather than a barrier-plaza pocket. Also bounds how far
# along a route's geometry this module scans before giving up on that reference.
APRON_REJECT_DISTANCE_M = 2_000.0

# Snap-based isolation thresholds: if the notoll graph snaps a gate coordinate
# more than this far AND more than RATIO× farther than the full graph, the gate
# sits inside a toll pocket (the nearest non-toll road is a distant service track,
# not a real approach road). Empirically from 30-gate sample: isolated gates have
# notoll snap 10–350m vs full 1–5m; genuinely accessible gates have both snapping
# within ~35m at similar distances. 50m / 3× clears both populations cleanly.
_ISOLATION_SNAP_M = 50.0
_ISOLATION_RATIO = 3.0

# Edge quality thresholds for snaps within _ISOLATION_SNAP_M: a snap landing on
# a track, driveway, or similarly poor road is not a usable access point even if
# it is geometrically close. Either criterion failing triggers anchor search.
_MIN_ANCHOR_SPEED_KMH = 30
_BAD_SNAP_USES = frozenset({
    "track", "driveway", "alley", "parking_aisle",
    "emergency_access", "drive_through", "golf_cart", "living_street",
})


@dataclass(frozen=True)
class AccessAnchor:
    gare_id: int
    direction: Direction
    anchor_lat: float
    anchor_lon: float
    apron_distance_m: float
    apron_duration_s: float


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres - used only to bound how far along a route's
    geometry the anchor search scans, not for the final apron figure (that's always a
    real OSRM plain-route leg, from `_plain_leg`).
    """
    lat1, lon1 = a
    lat2, lon2 = b
    earth_radius_m = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(h))


def _route_geometry(
    engine: RoutingEngine, origin: tuple[float, float], destination: tuple[float, float]
) -> list[tuple[float, float]] | None:
    """Full-resolution (lat, lon) geometry of the plain (toll allowed) route from
    `origin` to `destination`, in driving order; None on NoRoute.
    """
    data = engine.route(origin, destination, geometry=True)
    if data is None:
        return None
    return [(lat, lon) for lon, lat in data["routes"][0]["geometry"]["coordinates"]]


def _plain_leg(
    engine: RoutingEngine, origin: tuple[float, float], destination: tuple[float, float]
) -> tuple[float, float] | None:
    """(duration_s, distance_m) for the plain (toll allowed) route; None on NoRoute."""
    data = engine.route(origin, destination)
    if data is None:
        return None
    route = data["routes"][0]
    return route["duration"], route["distance"]


def _gate_reachable(
    engine: RoutingEngine,
    gate_point: tuple[float, float],
    reference_points: list[tuple[float, float]],
    direction: Direction,
) -> bool:
    """True if `gate_point` is not toll-isolated (no anchor needed for this direction).

    Uses snap distance comparison between the full and notoll Valhalla instances.
    A gate is isolated if the notoll graph snaps its coordinate significantly
    farther than the full graph — meaning the nearest non-toll road is a distant
    service track rather than a genuine approach road. `reference_points` and
    `direction` are kept for interface compatibility but not used in the check
    (snap distance is direction-agnostic and requires no matrix call).
    """
    lat, lon = gate_point
    notoll = engine.nearest(lat, lon, toll_free=True)
    if notoll["code"] == "NoSegment":
        return False
    wp = notoll["waypoints"][0]
    notoll_dist = wp["distance"]
    if notoll_dist <= _ISOLATION_SNAP_M:
        use = wp.get("use", "")
        speed = wp.get("default_speed", 0)
        if use in _BAD_SNAP_USES or speed < _MIN_ANCHOR_SPEED_KMH:
            return False  # snapped onto a track/driveway/slow road — needs anchor
        return True
    full = engine.nearest(lat, lon, toll_free=False)
    if full["code"] != "Ok":
        return True  # gate missing from full graph — treat as accessible
    full_dist = full["waypoints"][0]["distance"]
    return notoll_dist <= full_dist * _ISOLATION_RATIO


def _batch_reachable(
    engine: RoutingEngine,
    reference: tuple[float, float],
    points: list[tuple[float, float]],
    direction: Direction,
) -> list[bool]:
    """Per-point reachability of `points` to/from `reference`, in `direction`.

    `points` is already bounded to <= `OSRM_TABLE_MAX_DIMENSION` by the caller.
    """
    if direction == "entry":
        results = engine.one_to_many_table(reference, points, exclude_toll=True)
    else:
        results = engine.many_to_one_table(points, reference, exclude_toll=True)
    return [r is not None for r in results]


def find_anchor(
    engine: RoutingEngine,
    gare_id: int,
    direction: Direction,
    gate_point: tuple[float, float],
    reference_points: list[tuple[float, float]] = REFERENCE_POINTS,
) -> AccessAnchor | None:
    """Search along the real plain route between the gate and each reference city
    (caller has already checked the gate's own coordinate isn't directly toll-free-
    reachable in `direction`) for the nearest-to-gate point that clears the isolated
    pocket. None if no reference's route yields one within `APRON_REJECT_DISTANCE_M`.
    """
    best: AccessAnchor | None = None
    for reference in reference_points:
        geometry = (
            _route_geometry(engine, reference, gate_point)
            if direction == "entry"
            else _route_geometry(engine, gate_point, reference)
        )
        if geometry is None:
            continue
        # Reorder so index 0 is the gate end, walking outward toward the reference -
        # `_route_geometry`'s natural order is reference->gate for 'entry' (reversed
        # here) and already gate->reference for 'exit'.
        from_gate = list(reversed(geometry)) if direction == "entry" else geometry

        bounded: list[tuple[float, float]] = []
        cumulative = 0.0
        prev = gate_point
        for point in from_gate[1:]:  # [0] is ~the gate's own coordinate
            cumulative += _haversine_m(prev, point)
            if cumulative > APRON_REJECT_DISTANCE_M:
                break
            bounded.append(point)
            prev = point
            if len(bounded) >= OSRM_TABLE_MAX_DIMENSION:
                break
        if not bounded:
            continue

        reachable = _batch_reachable(engine, reference, bounded, direction)
        try:
            idx = reachable.index(True)
        except ValueError:
            continue  # this reference's route never clears the pocket within the bound
        candidate_point = bounded[idx]

        apron = (
            _plain_leg(engine, candidate_point, gate_point)
            if direction == "entry"
            else _plain_leg(engine, gate_point, candidate_point)
        )
        if apron is None:
            continue
        apron_duration_s, apron_distance_m = apron
        if apron_distance_m > APRON_REJECT_DISTANCE_M:
            continue  # geometry-distance bound is a heuristic; re-checked against the real leg

        anchor = AccessAnchor(
            gare_id, direction, candidate_point[0], candidate_point[1], apron_distance_m, apron_duration_s
        )
        if best is None or apron_distance_m < best.apron_distance_m:
            best = anchor
        if apron_distance_m <= GOOD_ENOUGH_APRON_M:
            break

    return best  # None means gate stays exactly as before for this direction: gap logged


def gate_rows(conn: sqlite3.Connection) -> list[tuple[int, float, float]]:
    """Same selection `tollroute.graph._gate_rows` uses: snapped, non-quarantined gates."""
    return conn.execute(
        "SELECT gare_id, snap_lat, snap_lon FROM gates "
        "WHERE snap_lat IS NOT NULL AND snap_lon IS NOT NULL "
        "AND gare_id NOT IN (SELECT gare_id FROM suspect_gates) "
        "ORDER BY gare_id"
    ).fetchall()


def write_anchors(conn: sqlite3.Connection, anchors: list[AccessAnchor]) -> None:
    # DROP rather than rely on CREATE TABLE IF NOT EXISTS: an older schema version of
    # this table (pre-Phase 5b-follow-up-1-continued, no `direction` column) may already
    # exist on disk - this table is purely a precompute cache, safe to rebuild from scratch.
    conn.execute("DROP TABLE IF EXISTS access_anchors")
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("DELETE FROM access_anchors")
    conn.executemany(
        "INSERT INTO access_anchors "
        "(gare_id, direction, anchor_lat, anchor_lon, apron_distance_m, apron_duration_s) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (a.gare_id, a.direction, a.anchor_lat, a.anchor_lon, a.apron_distance_m, a.apron_duration_s)
            for a in anchors
        ],
    )
    conn.commit()


def render_report(
    total_gates: int,
    anchors: list[AccessAnchor],
    needed: dict[Direction, int],
    found: dict[Direction, int],
) -> str:
    lines = ["# Phase 5b-follow-up-1-continued — direction-aware access-anchor precompute", ""]
    lines.append(
        "Rewrote the anchor search to do what this module's own docstring always claimed "
        "(walk backward along the real route's geometry, not probe outward from `/nearest` - "
        "the latter picks wrong-carriageway candidates on divided motorways) and made "
        "reachability direction-aware (entry: reference -> gate; exit: gate -> reference), "
        "since a shared anchor validated only in the exit direction was found silently wrong "
        "for entry in most of the previous iteration's shipped anchors. Full investigation in "
        "this module's docstring."
    )
    lines.append("")
    lines.append(f"Checked **{total_gates}** snapped, non-quarantined gates, per direction:")
    for direction in ("entry", "exit"):
        gapped = needed[direction] - found[direction]
        lines.append(
            f"- **{direction}**: {needed[direction]} needed an anchor; {found[direction]} found; "
            f"{gapped} still gapped (no verified-connected candidate within "
            f"{APRON_REJECT_DISTANCE_M:.0f} m of route distance)."
        )
    lines.append("")
    if anchors:
        aprons = sorted(a.apron_distance_m for a in anchors)
        mid = aprons[len(aprons) // 2]
        lines.append(
            f"Anchor apron distance (both directions combined): min {aprons[0]:.0f} m, "
            f"median {mid:.0f} m, max {aprons[-1]:.0f} m."
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def run(
    db_path: Path = DEFAULT_NATIONAL_DB_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    engine: RoutingEngine | None = None,
) -> list[AccessAnchor]:
    own_engine = engine is None
    if own_engine:
        engine = RoutingEngine()
    conn = sqlite3.connect(db_path)
    try:
        rows = gate_rows(conn)
        anchors: list[AccessAnchor] = []
        needed: dict[Direction, int] = {"entry": 0, "exit": 0}
        found: dict[Direction, int] = {"entry": 0, "exit": 0}
        for gare_id, lat, lon in rows:
            gate_point = (lat, lon)
            for direction in ("entry", "exit"):
                if _gate_reachable(engine, gate_point, REFERENCE_POINTS, direction):
                    continue
                needed[direction] += 1
                anchor = find_anchor(engine, gare_id, direction, gate_point)
                if anchor is not None:
                    anchors.append(anchor)
                    found[direction] += 1
        write_anchors(conn, anchors)
    finally:
        conn.close()
        if own_engine:
            engine.close()

    logger.info(
        "access anchors: entry %d/%d needed found, exit %d/%d needed found",
        found["entry"],
        needed["entry"],
        found["exit"],
        needed["exit"],
    )
    report = render_report(len(rows), anchors, needed, found)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    logger.info("report written to %s", report_path)
    return anchors


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_NATIONAL_DB_PATH)
    parser.add_argument("--full-url", default=DEFAULT_FULL_URL)
    parser.add_argument("--tollfree-url", default=DEFAULT_TOLLFREE_URL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    engine = RoutingEngine(full_url=args.full_url, tollfree_url=args.tollfree_url)
    try:
        run(db_path=args.db, report_path=args.report, engine=engine)
    finally:
        engine.close()


if __name__ == "__main__":
    main()
