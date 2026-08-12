"""Per-request OSRM I/O: retry-once failure handling, batched /table access
edges, a baseline /route and lazy route geometry (Phase 4c).

Build-time OSRM helpers stay where they are - `tollroute.graph.osrm_table`
(full N x N tiling for the Phase 3b matrix precompute) and its private
`_osrm_route` (the old per-gate access-edge caller this module replaces) are
unrelated to a live request's latency budget. This module owns exactly the
three per-request OSRM interactions the spec names for Phase 4c: two /table
calls (origin<->access-gate set) and one baseline /route, all wrapped in the
same retry-once-at-500ms policy, plus the on-demand geometry fetch for the
lazy `/geometry/{route_id}` endpoint (`tollroute/api.py`).
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

logger = logging.getLogger(__name__)

RETRY_DELAY_S = 0.5

# Same OSRM /table server-side cap as tollroute.graph.OSRM_TABLE_MAX_DIMENSION
# (osrm-routed's default --max-table-size, confirmed empirically there).
# Duplicated rather than imported so this module has no dependency on
# graph.py's build-time code.
TABLE_MAX_DIMENSION = 100

# A national access-edge query tiles into ~9 blocks per side (815 gates /
# 100). Raising osrm-routed's --max-table-size would collapse each side to
# one request, but that's a shared Docker service's startup flag, not
# something this per-request client controls - firing the existing tiled
# requests concurrently instead is what gets a warm request under the
# spec's ~300 ms budget without touching the running OSRM container
# (measured: ~1.5s sequential -> ~250-350ms concurrent for Dijon->Lyon
# against the national 815-gate DB).
MAX_CONCURRENT_REQUESTS = 9


class OSRMUnavailableError(RuntimeError):
    """OSRM did not answer after one retry at RETRY_DELAY_S.

    Callers (`tollroute/api.py`) turn this into the spec's
    `{"osrm_unavailable": true}` response rather than a 500.
    """


def _get_json(client: httpx.Client, url: str) -> dict:
    """GET url, retrying once after RETRY_DELAY_S on any transport/HTTP
    failure; raises OSRMUnavailableError if the retry also fails (spec:
    "retry once at 500 ms; return osrm_unavailable if still down")."""
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning(
                    "OSRM request failed, retrying once in %.1fs: %s (%s)", RETRY_DELAY_S, url, exc
                )
                time.sleep(RETRY_DELAY_S)
    raise OSRMUnavailableError(f"OSRM unreachable after retry: {url}") from last_exc


def _get_json_concurrent(client: httpx.Client, urls: list[str]) -> list[dict]:
    """`_get_json` for each url, fired concurrently (httpx.Client is
    thread-safe for concurrent requests on the same connection pool) - the
    tiled /table blocks below are independent requests, so there is no
    reason to pay their latency sequentially.
    """
    if len(urls) == 1:
        return [_get_json(client, urls[0])]
    with ThreadPoolExecutor(max_workers=min(len(urls), MAX_CONCURRENT_REQUESTS)) as pool:
        return list(pool.map(lambda u: _get_json(client, u), urls))


def baseline_route(
    client: httpx.Client, origin: tuple[float, float], destination: tuple[float, float]
) -> dict | None:
    """Direct origin->destination /route, tolls allowed (spec: "one baseline
    `/route`"). Deliberately the first OSRM call issued per request (see
    `tollroute/api.py`): it is the cheapest possible OSRM call, so it doubles
    as the availability canary that catches a down OSRM (with its own single
    retry) before the two heavier /table batches below run.

    Returns None (not an exception) for OSRM's own NoRoute - a genuine "no
    road connects these two points" is a real result, not an availability
    failure.

    **Known non-determinism, measured not assumed (Phase 5c-follow-up-2,
    `reports/phase5c_followup2_production_route_determinism.md`):** on a
    near-tied corridor, `osrm-routed`'s MLD engine can return either of two
    candidate routes (differing here by <=1.8% distance / <=6.1% duration)
    across otherwise-identical repeat calls once thread count exceeds ~2 -
    production runs at the host's full core count. This call is the one
    OSRM interaction on the `/route` path not protected by the frozen,
    precomputed gate-to-gate matrix that makes `tollroute.graph`'s own
    Dijkstra route choice (`fastest`/`cheapest`/`best_value`, verified
    unaffected across 45 repeat live requests) deterministic, so `baseline`
    is the one field that can flip between two fresh (cache-miss) requests
    for the same query. Left as-is deliberately: see the report for the
    full tradeoff against pinning `osrm-routed --threads` service-wide.
    """
    o_lat, o_lon = origin
    d_lat, d_lon = destination
    data = _get_json(client, f"/route/v1/car/{o_lon},{o_lat};{d_lon},{d_lat}?overview=false")
    if data.get("code") == "NoRoute":
        return None
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM /route failed for {origin}->{destination}: {data}")
    leg = data["routes"][0]
    return {"duration": leg["duration"], "distance": leg["distance"]}


def one_to_many_table(
    client: httpx.Client,
    origin: tuple[float, float],
    many: list[tuple[float, float]],
    exclude_toll: bool,
) -> list[tuple[float, float] | None]:
    """duration/distance from `origin` to each point in `many`, tiled into
    <=100-wide /table requests (TABLE_MAX_DIMENSION). One list entry per
    `many` element, in order; None where OSRM has no route for that pair.
    """
    if not many:
        return []
    params = "annotations=duration,distance"
    if exclude_toll:
        params += "&exclude=toll"
    o_lat, o_lon = origin
    starts = list(range(0, len(many), TABLE_MAX_DIMENSION))
    blocks = [many[start : start + TABLE_MAX_DIMENSION] for start in starts]
    urls = [
        "/table/v1/car/"
        + ";".join([f"{o_lon},{o_lat}"] + [f"{lon},{lat}" for lat, lon in block])
        + f"?{params}&sources=0&destinations=" + ";".join(str(i) for i in range(1, len(block) + 1))
        for block in blocks
    ]
    responses = _get_json_concurrent(client, urls)

    out: list[tuple[float, float] | None] = [None] * len(many)
    for start, block, data in zip(starts, blocks, responses):
        if data.get("code") != "Ok":
            raise RuntimeError(f"OSRM /table failed: {data}")
        for bi in range(len(block)):
            duration = data["durations"][0][bi]
            distance = data["distances"][0][bi]
            if duration is not None and distance is not None:
                out[start + bi] = (duration, distance)
    return out


def many_to_one_table(
    client: httpx.Client,
    many: list[tuple[float, float]],
    destination: tuple[float, float],
    exclude_toll: bool,
) -> list[tuple[float, float] | None]:
    """duration/distance from each point in `many` to `destination`, tiled
    the same way as `one_to_many_table`."""
    if not many:
        return []
    params = "annotations=duration,distance"
    if exclude_toll:
        params += "&exclude=toll"
    d_lat, d_lon = destination
    starts = list(range(0, len(many), TABLE_MAX_DIMENSION))
    blocks = [many[start : start + TABLE_MAX_DIMENSION] for start in starts]
    urls = [
        "/table/v1/car/"
        + ";".join([f"{lon},{lat}" for lat, lon in block] + [f"{d_lon},{d_lat}"])
        + f"?{params}&sources=" + ";".join(str(i) for i in range(len(block))) + f"&destinations={len(block)}"
        for block in blocks
    ]
    responses = _get_json_concurrent(client, urls)

    out: list[tuple[float, float] | None] = [None] * len(many)
    for start, block, data in zip(starts, blocks, responses):
        if data.get("code") != "Ok":
            raise RuntimeError(f"OSRM /table failed: {data}")
        for bi in range(len(block)):
            duration = data["durations"][bi][0]
            distance = data["distances"][bi][0]
            if duration is not None and distance is not None:
                out[start + bi] = (duration, distance)
    return out


def route_geometry(client: httpx.Client, waypoints: list[tuple[float, float]]) -> dict:
    """Full-geometry /route across an ordered list of (lat, lon) waypoints
    (origin, physical gate points along the chosen gate chain, destination),
    for the lazy `/geometry/{route_id}` endpoint.

    **Judgement call, flagged:** tolls are allowed end to end rather than
    replaying each leg's original exclude=toll setting. The priced route and
    its toll/duration/distance totals are already fixed by the Dijkstra
    result before this ever runs (spec: "All geometry from OSRM; Python
    never touches a road segment" - geometry is a display concern, not a
    pricing one), so the polyline only needs to be a visually plausible path
    through the same waypoints, not per-leg toll-exclusion-faithful.
    """
    coords = ";".join(f"{lon},{lat}" for lat, lon in waypoints)
    data = _get_json(client, f"/route/v1/car/{coords}?overview=full&geometries=geojson")
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM /route geometry failed: {data}")
    return data["routes"][0]["geometry"]
