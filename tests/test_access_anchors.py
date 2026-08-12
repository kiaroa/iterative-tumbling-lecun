import httpx
import pytest

from tollroute.etl import access_anchors


def _geojson_route(points: list[tuple[float, float]]) -> dict:
    """A minimal OSRM /route Ok response with full geometry through `points` (lat, lon)."""
    return {
        "code": "Ok",
        "routes": [{"geometry": {"coordinates": [[lon, lat] for lat, lon in points]}}],
    }


def test_find_anchor_walks_geometry_from_gate_and_stops_at_first_reachable_point():
    """Phase 5b-follow-up-1-continued: `find_anchor` must walk the real plain route's
    geometry outward from the gate (not radiate from an undirected `/nearest`, which
    picks wrong-carriageway candidates on divided motorways - see this module's
    docstring for the Fleury-en-Bière evidence) and pick the *nearest-to-gate* point
    that clears the isolated pocket, using OSRM's `/table` in the query direction to
    test reachability.

    Sets up a route reference->gate with three candidate points at increasing distance
    from the gate (p1 closest, then p2, then p3), where only p2 and p3 are toll-free-
    reachable from the reference. Expects the anchor to land on p2 (nearest reachable),
    not p3, and the apron leg to come from the real `/route` p2->gate call.
    """
    gate = (48.00000, 2.00000)
    reference = (50.00000, 3.00000)
    p1 = (48.00000, 2.00080)  # ~60 m from gate, NOT reachable
    p2 = (48.00000, 2.00200)  # ~149 m cumulative from gate, reachable - expected anchor
    p3 = (48.00000, 2.00500)  # ~372 m cumulative from gate, also reachable but farther

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.path.startswith("/route/") and "overview=full" in url:
            # Geometry call: reference -> gate, in that driving order.
            return httpx.Response(200, json=_geojson_route([reference, p3, p2, p1, gate]))
        if request.url.path.startswith("/table/"):
            # Batched reachability call for the bounded points [p1, p2, p3]: only
            # p2 and p3 are reachable from the reference (source 0).
            return httpx.Response(200, json={"code": "Ok", "durations": [[None, 120.0, 300.0]]})
        if request.url.path.startswith("/route/") and "overview=false" in url:
            # Apron leg: p2 -> gate.
            return httpx.Response(
                200, json={"code": "Ok", "routes": [{"duration": 12.5, "distance": 149.0}]}
            )
        raise AssertionError(f"unexpected request: {url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://osrm.test")
    anchor = access_anchors.find_anchor(
        client, gare_id=999, direction="entry", gate_point=gate, reference_points=[reference]
    )

    assert anchor is not None
    assert anchor.gare_id == 999
    assert anchor.direction == "entry"
    assert (anchor.anchor_lat, anchor.anchor_lon) == p2
    assert anchor.apron_distance_m == pytest.approx(149.0)
    assert anchor.apron_duration_s == pytest.approx(12.5)


def test_find_anchor_exit_direction_walks_gate_to_reference_order():
    """Exit-direction anchors walk the gate->reference route forward from the gate end
    and test point->reference reachability (the mirror of the entry case) - pinning
    that entry and exit are not accidentally swapped or share one direction's logic.
    """
    gate = (48.00000, 2.00000)
    reference = (50.00000, 3.00000)
    p1 = (48.00000, 2.00080)  # NOT reachable
    p2 = (48.00000, 2.00200)  # reachable - expected anchor

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.path.startswith("/route/") and "overview=full" in url:
            # Geometry call: gate -> reference, in that driving order.
            return httpx.Response(200, json=_geojson_route([gate, p1, p2, reference]))
        if request.url.path.startswith("/table/"):
            return httpx.Response(200, json={"code": "Ok", "durations": [[None], [90.0]]})
        if request.url.path.startswith("/route/") and "overview=false" in url:
            # Apron leg: gate -> p2.
            return httpx.Response(
                200, json={"code": "Ok", "routes": [{"duration": 11.0, "distance": 149.0}]}
            )
        raise AssertionError(f"unexpected request: {url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://osrm.test")
    anchor = access_anchors.find_anchor(
        client, gare_id=999, direction="exit", gate_point=gate, reference_points=[reference]
    )

    assert anchor is not None
    assert anchor.direction == "exit"
    assert (anchor.anchor_lat, anchor.anchor_lon) == p2


def test_find_anchor_returns_none_when_no_candidate_clears_the_pocket():
    """No reachable point within the apron-reject bound -> gate stays gapped, matching
    the pre-existing "leg is None -> omitted" fallback in `add_access_edges`.
    """
    gate = (48.00000, 2.00000)
    reference = (50.00000, 3.00000)
    p1 = (48.00000, 2.00080)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.path.startswith("/route/") and "overview=full" in url:
            return httpx.Response(200, json=_geojson_route([reference, p1, gate]))
        if request.url.path.startswith("/table/"):
            return httpx.Response(200, json={"code": "Ok", "durations": [[None]]})
        raise AssertionError(f"unexpected request: {url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://osrm.test")
    anchor = access_anchors.find_anchor(
        client, gare_id=999, direction="entry", gate_point=gate, reference_points=[reference]
    )

    assert anchor is None
