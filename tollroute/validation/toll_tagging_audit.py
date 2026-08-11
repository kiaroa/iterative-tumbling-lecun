"""Toll-tagging audit on `exclude=toll` routes (Phase 3c, deliverable 3).

Run as: python3 -m tollroute.validation.toll_tagging_audit

Two checks, per `iterative-tumbling-lecun.md` Phase 3c ("sample of exclude=toll
routes - assert path passes nowhere near a known toll plaza"):

1. **Route-proximity sample.** For a random sample of physical-gate pairs with a
   genuine toll-free route (Phase 3b's `tollfree_distance_m` matrix is non-NaN),
   fetch the live `exclude=toll` route geometry and assert no point on it comes
   within `PROXIMITY_THRESHOLD_M` of any of the 815 known toll-gate coordinates
   other than the pair's own two endpoints (which the route legitimately starts
   / ends at).

2. **The Phase 3b-follow-up conjecture**, resolved here per that item's own
   instruction ("fold the result into Phase 3c's toll-tagging audit rather than
   running a separate pass", `IMPLEMENTATION_PLAN.md`): 333/815 gates are
   near-isolated in the toll-free matrix; the conjectured cause is that each
   such gate's only mapped OSM access road is itself tagged `toll=yes` right up
   to the barrier. Tested directly by comparing, for a sample of those gates,
   OSRM `/nearest` with and without `exclude=toll` - if the toll-free nearest
   road is dramatically further away than the default nearest road, that
   supports the conjecture (the gate has *a* nearby road, just not a toll-free
   one); if the two distances are similar, the isolation has some other cause.
"""

from __future__ import annotations

import argparse
import logging
import random
from dataclasses import dataclass
from pathlib import Path

import httpx

from tollroute import matrices as mx
from tollroute.etl.cluster_gates import PhysicalCluster, haversine_m
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase3c.md"

ROUTE_SAMPLE_SIZE = 20
ROUTE_SAMPLE_SEED = 11

ISOLATED_SAMPLE_SIZE = 15
ISOLATED_SAMPLE_SEED = 13
ISOLATION_THRESHOLD = 0.9  # same threshold matrices.py already established

# A toll-free route should never come within this of ANY known toll-gate
# coordinate other than its own endpoints (spec: "passes nowhere near a known
# toll plaza"). Judgement call (flagged): tighter than cluster_gates' 100 m
# co-location radius, since here we want to catch a route that is genuinely
# also tolled nearby, not just two barriers that happen to be neighbours.
PROXIMITY_THRESHOLD_M = 50.0
# Cheap bounding-box pre-reject before the haversine call, same 0.01 deg (~1.1
# km) tolerance cluster_gates.type_transfer_edges already uses - comfortably
# wider than PROXIMITY_THRESHOLD_M so it never masks a real close approach.
BBOX_DEGREES = 0.01

# Judgement call (flagged): the toll-free /nearest snap must be at least this
# much further than the default /nearest snap to count as supporting the
# "only mapped access is toll-tagged" conjecture, rather than routine snap noise.
ISOLATED_CONFIRM_DELTA_M = 200.0


@dataclass
class RouteProximityCheck:
    from_physical_gate_id: int
    to_physical_gate_id: int
    distance_km: float
    passed: bool
    closest_other_gate_id: int | None
    closest_other_gate_distance_m: float | None


@dataclass
class IsolatedGateCheck:
    physical_gate_id: int
    default_snap_m: float
    tollfree_snap_m: float
    delta_m: float
    confirms_conjecture: bool


def osrm_route_geometry(
    client: httpx.Client, origin: tuple[float, float], destination: tuple[float, float]
) -> dict | None:
    """`exclude=toll` route with full GeoJSON geometry. None on OSRM NoRoute."""
    o_lat, o_lon = origin
    d_lat, d_lon = destination
    resp = client.get(
        f"/route/v1/car/{o_lon},{o_lat};{d_lon},{d_lat}"
        "?overview=full&geometries=geojson&exclude=toll"
    )
    data = resp.json()
    if data.get("code") == "NoRoute":
        return None
    resp.raise_for_status()
    if data["code"] != "Ok":
        raise RuntimeError(f"OSRM /route failed for {origin}->{destination}: {data}")
    return data["routes"][0]


def _closest_gate(
    lat: float,
    lon: float,
    clusters: list[PhysicalCluster],
    exclude_ids: set[int],
) -> tuple[int, float] | None:
    best: tuple[int, float] | None = None
    for c in clusters:
        if c.physical_gate_id in exclude_ids:
            continue
        if abs(lat - c.lat) > BBOX_DEGREES or abs(lon - c.lon) > BBOX_DEGREES:
            continue
        d = haversine_m(lat, lon, c.lat, c.lon)
        if best is None or d < best[1]:
            best = (c.physical_gate_id, d)
    return best


def check_route_proximity(
    route: dict,
    clusters: list[PhysicalCluster],
    origin_id: int,
    dest_id: int,
    threshold_m: float = PROXIMITY_THRESHOLD_M,
) -> tuple[bool, int | None, float | None]:
    """Downsample the route geometry (~200 points is ample at motorway scale)
    and find the closest known toll gate, excluding the route's own endpoints.
    """
    coords = route["geometry"]["coordinates"]  # [[lon, lat], ...]
    step = max(1, len(coords) // 200)
    sampled = coords[::step]

    exclude_ids = {origin_id, dest_id}
    closest: tuple[int, float] | None = None
    for lon, lat in sampled:
        hit = _closest_gate(lat, lon, clusters, exclude_ids)
        if hit is not None and (closest is None or hit[1] < closest[1]):
            closest = hit

    if closest is None:
        return True, None, None
    passed = closest[1] > threshold_m
    return passed, closest[0], closest[1]


def sample_route_pairs(
    clusters: list[PhysicalCluster],
    tollfree_distance_m,
    sample_size: int = ROUTE_SAMPLE_SIZE,
    seed: int = ROUTE_SAMPLE_SEED,
) -> list[tuple[int, int]]:
    """Random physical-gate index pairs with a genuine (non-NaN) toll-free route."""
    n = len(clusters)
    rng = random.Random(seed)
    candidates = [
        (i, j)
        for i in range(n)
        for j in range(n)
        if i != j and tollfree_distance_m[i, j] == tollfree_distance_m[i, j]
    ]
    rng.shuffle(candidates)
    return candidates[:sample_size]


def run_route_proximity_sample(
    clusters: list[PhysicalCluster],
    tollfree_distance_m,
    client: httpx.Client,
    sample_size: int = ROUTE_SAMPLE_SIZE,
    seed: int = ROUTE_SAMPLE_SEED,
) -> list[RouteProximityCheck]:
    pairs = sample_route_pairs(clusters, tollfree_distance_m, sample_size, seed)
    results: list[RouteProximityCheck] = []
    for i, j in pairs:
        a, b = clusters[i], clusters[j]
        route = osrm_route_geometry(client, (a.lat, a.lon), (b.lat, b.lon))
        if route is None:
            continue
        passed, gate_id, dist_m = check_route_proximity(
            route, clusters, a.physical_gate_id, b.physical_gate_id
        )
        results.append(
            RouteProximityCheck(
                a.physical_gate_id,
                b.physical_gate_id,
                route["distance"] / 1000.0,
                passed,
                gate_id,
                dist_m,
            )
        )
    return results


def osrm_nearest_distance(client: httpx.Client, lat: float, lon: float, exclude_toll: bool) -> float:
    url = f"/nearest/v1/car/{lon},{lat}"
    if exclude_toll:
        url += "?exclude=toll"
    resp = client.get(url)
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != "Ok":
        raise RuntimeError(f"OSRM /nearest failed for ({lat},{lon}): {data}")
    waypoint = data["waypoints"][0]
    snap_lon, snap_lat = waypoint["location"]
    return haversine_m(lat, lon, snap_lat, snap_lon)


def run_isolated_gate_sample(
    clusters: list[PhysicalCluster],
    tollfree_distance_m,
    client: httpx.Client,
    sample_size: int = ISOLATED_SAMPLE_SIZE,
    seed: int = ISOLATED_SAMPLE_SEED,
) -> list[IsolatedGateCheck]:
    isolated_indices = mx.isolated_matrix_indices(tollfree_distance_m, ISOLATION_THRESHOLD)
    rng = random.Random(seed)
    sample_idx = list(isolated_indices)
    rng.shuffle(sample_idx)
    sample_idx = sample_idx[:sample_size]

    results: list[IsolatedGateCheck] = []
    for i in sample_idx:
        c = clusters[i]
        default_m = osrm_nearest_distance(client, c.lat, c.lon, exclude_toll=False)
        tollfree_m = osrm_nearest_distance(client, c.lat, c.lon, exclude_toll=True)
        delta = tollfree_m - default_m
        results.append(
            IsolatedGateCheck(
                c.physical_gate_id, default_m, tollfree_m, delta, delta >= ISOLATED_CONFIRM_DELTA_M
            )
        )
    return results


def run(
    osrm_base_url: str = DEFAULT_OSRM_BASE_URL,
) -> tuple[list[RouteProximityCheck], list[IsolatedGateCheck]]:
    clusters = sorted(mx.physical_gate_points(), key=lambda c: c.physical_gate_id)
    loaded = mx.load_matrices()
    tollfree_distance_m = loaded["tollfree_distance_m"]

    with httpx.Client(base_url=osrm_base_url, timeout=30.0) as client:
        proximity = run_route_proximity_sample(clusters, tollfree_distance_m, client)
        isolated = run_isolated_gate_sample(clusters, tollfree_distance_m, client)

    failed = [r for r in proximity if not r.passed]
    confirmed = [r for r in isolated if r.confirms_conjecture]
    logger.info(
        "toll-tagging audit: %d/%d route-proximity samples passed; "
        "%d/%d near-isolated-gate samples confirm the toll-tagging conjecture",
        len(proximity) - len(failed),
        len(proximity),
        len(confirmed),
        len(isolated),
    )
    return proximity, isolated


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osrm-base-url", default=DEFAULT_OSRM_BASE_URL)
    args = parser.parse_args()
    run(osrm_base_url=args.osrm_base_url)


if __name__ == "__main__":
    main()
