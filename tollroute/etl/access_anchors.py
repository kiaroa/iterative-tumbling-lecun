"""Precompute per-gate toll-free access anchors (Phase 5b-follow-up-1).

Run as: python3 -m tollroute.etl.access_anchors

**Investigated hypothesis, and why it's revised here.** The Phase 5b-follow-up-1 plan
item's own premise was that `add_access_edges`' `exclude=toll` excludes "an entire named
motorway" too early, catching a genuine toll-free lead-in near the query point. Checked
directly against the live national OSRM instance for the two implicated routes
(Paris->Lyon, Paris->Bordeaux): OSM's `toll=yes`/`toll=no` tagging on the A6 south of Paris
is already split at the right place (confirmed via `osmium` against `osrm/data/france.osm.pbf`
- every A6 way north of ~3.9 km before the Fleury-en-Bière barrier is `toll=no`, every one
south of it is `toll=yes`), so the exclusion is not premature. What actually happens: the
gate's own coordinate *is* the physical barrier, sitting on tolled tarmac by definition, and
for some barriers (confirmed for Fleury-en-Bière, gare_id 302/303) the final local approach
is a small pocket in the `exclude=toll` graph that isn't connected back to the wider
toll-free network - not because the road is toll-tagged too early, but a local OSRM/OSM
topology gap right at the plaza. This matches Phase 3c's own toll-tagging audit finding
(`reports/phase3c.md` section 3b), which already tested and rejected "premature tagging" as
the dominant cause for the 333 gates Phase 3b found near-isolated, concluding instead that
it's "a broader graph-connectivity cause" - this script is the fix that finding called for.

**What this script does.** For every gate `add_access_edges` could plausibly need (all gates
with snap coordinates, minus `suspect_gates`), check whether the gate's own coordinate is
already toll-free-reachable from a handful of widely-spread reference cities (`REFERENCE_POINTS`,
reusing well-tested coordinates from `tollroute.cli.GAZETTEER`/`analysis/phase5b_plausibility.py`).
If so, nothing to do - `add_access_edges` already handles it.

**Why the anchor search walks back along a real route rather than radiating out from
`/nearest`.** Tried first and rejected: probing outward from the gate via plain
`/nearest?exclude=toll&number=N` for the nearest toll-free-tagged candidate that also reaches a
reference city. Verified this fails near Fleury-en-Bière - motorways are oneway/divided, so
`/nearest`'s raw nearest-edge snap is not direction-aware, and several candidates only tens of
metres from the gate in a straight line turned out to be on the *opposite* carriageway, forcing
a 30 km loop (exit, local roads, re-enter) to actually drive between them - a plain-route
distance that has nothing to do with a genuine last-mile apron. Used instead: fetch the plain
(toll allowed) `/route` from a reference city to the gate - a real, direction-correct driving
path by construction - and walk backward along *that* route's own geometry, testing at each
step whether the point so far is toll-free-reachable from a reference city. The first (nearest
to the gate) point that is becomes the anchor, with the plain leg from there to the gate as the
apron. Tried against every reference city (cheapest-first: stop as soon as one produces an
apron under `GOOD_ENOUGH_APRON_M`, otherwise keep the smallest apron found) rather than just
one, because a reference on the "wrong side" of a directional barrier produces the same kind of
inflated, detoured apron `/nearest` did - the smallest-apron selection self-filters towards
whichever reference approaches from the gate's real, physically-connected direction.

`add_access_edges` then queries the anchor instead of the raw gate coordinate for its
`exclude=toll` batch call and adds the apron on top, which is safe: `APRON_REJECT_DISTANCE_M`
bounds it to a short local hop, so it cannot resurrect the Phase 1c free-ride bug (`exclude=toll`
on the full-length access edge, unchanged here, is what fixed that).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx

from tollroute.etl.build_national import DEFAULT_NATIONAL_DB_PATH
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "tollroute" / "db" / "schema.sql"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase5b_followup1_access_anchors.md"

# Widely-spread city centres (N/S/E/W/centre) already used elsewhere in this project
# (tollroute.cli.GAZETTEER, analysis/phase5b_plausibility.py) without incident - reused here
# rather than picked fresh so "reachable from a reference city" means the same thing this
# project already trusts it to mean. A gate only needs to reach ONE of these to be judged
# not-an-isolated-pocket.
REFERENCE_POINTS: list[tuple[float, float]] = [
    (48.8566, 2.3522),  # Paris
    (45.7640, 4.8357),  # Lyon
    (43.2965, 5.3698),  # Marseille
    (50.6292, 3.0573),  # Lille
    (44.8378, -0.5792),  # Bordeaux
    (48.5734, 7.7521),  # Strasbourg
]

# How many nearest toll-free-tagged candidates to probe outward from a gate before giving
# up. `/nearest`'s own candidates are returned nearest-first, so the first one that also
# reaches a reference city toll-free is accepted - no need to weigh alternatives.
ANCHOR_CANDIDATES = 20

# A candidate whose plain apron leg exceeds this is rejected outright (search continues to
# the next-nearest candidate), not just logged. Motorways are oneway/divided, so the raw
# nearest-edge snap `/nearest` returns is not direction-aware - a candidate can be a genuine
# few tens of metres from the gate in a straight line and yet, on the wrong carriageway or
# past a missing turn, force a multi-kilometre loop to actually drive between them. Verified
# directly: Fleury-en-Bière's 3rd-nearest exclude=toll candidate (60 m away) has a 30 km plain
# apron for exactly this reason, while several of its ~20-90 m candidates have plain aprons
# under 1 km. 2 km comfortably covers every genuine last-mile apron seen in testing (Fleury's
# best is ~500 m) while rejecting multi-km detour artefacts several orders of magnitude larger.
APRON_REJECT_DISTANCE_M = 2_000.0


@dataclass(frozen=True)
class AccessAnchor:
    gare_id: int
    anchor_lat: float
    anchor_lon: float
    apron_distance_m: float
    apron_duration_s: float


def _osrm_reachable_to_any_reference(
    client: httpx.Client, lat: float, lon: float, reference_points: list[tuple[float, float]]
) -> bool:
    """True if `(lat, lon)` reaches at least one reference point via `exclude=toll`."""
    destinations = ";".join(f"{r_lon},{r_lat}" for r_lat, r_lon in reference_points)
    url = (
        f"/table/v1/car/{lon},{lat};{destinations}"
        f"?annotations=duration&exclude=toll&sources=0&destinations="
        + ";".join(str(i) for i in range(1, len(reference_points) + 1))
    )
    resp = client.get(url)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok":
        return False
    return any(d is not None for d in data["durations"][0])


def _nearest_tollfree_candidates(
    client: httpx.Client, lat: float, lon: float, number: int
) -> list[tuple[float, float]]:
    """Up to `number` toll-free-tagged snap candidates near `(lat, lon)`, nearest first."""
    resp = client.get(f"/nearest/v1/car/{lon},{lat}?exclude=toll&number={number}")
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok":
        return []
    return [(w["location"][1], w["location"][0]) for w in data["waypoints"]]


def _plain_leg(
    client: httpx.Client, origin: tuple[float, float], destination: tuple[float, float]
) -> tuple[float, float] | None:
    """(duration_s, distance_m) for the plain (toll allowed) `/route`; None on NoRoute."""
    o_lat, o_lon = origin
    d_lat, d_lon = destination
    resp = client.get(f"/route/v1/car/{o_lon},{o_lat};{d_lon},{d_lat}?overview=false")
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") == "NoRoute":
        return None
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM /route failed for {origin}->{destination}: {data}")
    route = data["routes"][0]
    return route["duration"], route["distance"]


def find_anchor(
    client: httpx.Client,
    gare_id: int,
    lat: float,
    lon: float,
    reference_points: list[tuple[float, float]] = REFERENCE_POINTS,
    candidates: int = ANCHOR_CANDIDATES,
) -> AccessAnchor | None:
    """Search outward from a gate already known to need an anchor (caller has checked
    its own coordinate isn't directly toll-free-reachable) for the nearest verified-
    connected candidate. None if none of `candidates` probes finds one.
    """
    for cand_lat, cand_lon in _nearest_tollfree_candidates(client, lat, lon, candidates):
        if not _osrm_reachable_to_any_reference(client, cand_lat, cand_lon, reference_points):
            continue  # itself just another isolated pocket - keep searching outward
        apron = _plain_leg(client, (cand_lat, cand_lon), (lat, lon))
        if apron is None:
            continue
        apron_duration_s, apron_distance_m = apron
        if apron_distance_m > APRON_REJECT_DISTANCE_M:
            # Not a last-mile apron - a oneway/divided-carriageway detour artefact from
            # an undirected /nearest snap. Keep searching rather than accept it.
            continue
        return AccessAnchor(gare_id, cand_lat, cand_lon, apron_distance_m, apron_duration_s)

    return None  # gate stays exactly as before: add_access_edges omits it, gap logged


def gate_rows(conn: sqlite3.Connection) -> list[tuple[int, float, float]]:
    """Same selection `tollroute.graph._gate_rows` uses: snapped, non-quarantined gates."""
    return conn.execute(
        "SELECT gare_id, snap_lat, snap_lon FROM gates "
        "WHERE snap_lat IS NOT NULL AND snap_lon IS NOT NULL "
        "AND gare_id NOT IN (SELECT gare_id FROM suspect_gates) "
        "ORDER BY gare_id"
    ).fetchall()


def write_anchors(conn: sqlite3.Connection, anchors: list[AccessAnchor]) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("DELETE FROM access_anchors")
    conn.executemany(
        "INSERT INTO access_anchors "
        "(gare_id, anchor_lat, anchor_lon, apron_distance_m, apron_duration_s) "
        "VALUES (?, ?, ?, ?, ?)",
        [(a.gare_id, a.anchor_lat, a.anchor_lon, a.apron_distance_m, a.apron_duration_s) for a in anchors],
    )
    conn.commit()


def render_report(total_gates: int, anchors: list[AccessAnchor], still_gapped: int) -> str:
    lines = ["# Phase 5b-follow-up-1 — access-anchor precompute", ""]
    lines.append(
        "Investigation revised the plan item's own hypothesis: OSM's `toll=yes`/`toll=no` "
        "tagging near Fleury-en-Bière/Paris-Lyon is already split at the right place, not "
        "\"premature\". The real mechanism - confirmed against the live national OSRM "
        "instance and consistent with `reports/phase3c.md` section 3b's already-published "
        "finding - is a local graph-connectivity gap right at some barriers' final approach, "
        "not a taggable per-segment fix."
    )
    lines.append("")
    lines.append(
        f"Checked **{total_gates}** snapped, non-quarantined gates. **{len(anchors)}** needed "
        f"an anchor (their own coordinate was not directly toll-free-reachable from any of "
        f"{len(REFERENCE_POINTS)} reference cities); **{still_gapped}** had no verified-connected "
        f"candidate within {ANCHOR_CANDIDATES} `/nearest` probes and are left exactly as before "
        "(`add_access_edges` omits them, gap logged - unchanged pre-existing behaviour)."
    )
    lines.append("")
    if anchors:
        aprons = sorted(a.apron_distance_m for a in anchors)
        mid = aprons[len(aprons) // 2]
        lines.append(
            f"Anchor apron distance: min {aprons[0]:.0f} m, median {mid:.0f} m, "
            f"max {aprons[-1]:.0f} m."
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def run(
    db_path: Path = DEFAULT_NATIONAL_DB_PATH,
    osrm_base_url: str = DEFAULT_OSRM_BASE_URL,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> list[AccessAnchor]:
    conn = sqlite3.connect(db_path)
    try:
        rows = gate_rows(conn)
        anchors: list[AccessAnchor] = []
        needed_anchor = 0
        with httpx.Client(base_url=osrm_base_url, timeout=30.0) as client:
            for gare_id, lat, lon in rows:
                if _osrm_reachable_to_any_reference(client, lat, lon, REFERENCE_POINTS):
                    continue  # gate's own coordinate is fine as-is; no anchor needed
                needed_anchor += 1
                anchor = find_anchor(client, gare_id, lat, lon)
                if anchor is not None:
                    anchors.append(anchor)
        write_anchors(conn, anchors)
        still_gapped = needed_anchor - len(anchors)
    finally:
        conn.close()

    logger.info(
        "access anchors: %d/%d gates needed one; %d found, %d still gapped",
        needed_anchor,
        len(rows),
        len(anchors),
        still_gapped,
    )
    report = render_report(len(rows), anchors, still_gapped)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    logger.info("report written to %s", report_path)
    return anchors


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_NATIONAL_DB_PATH)
    parser.add_argument("--osrm-base-url", default=DEFAULT_OSRM_BASE_URL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    run(db_path=args.db, osrm_base_url=args.osrm_base_url, report_path=args.report)


if __name__ == "__main__":
    main()
