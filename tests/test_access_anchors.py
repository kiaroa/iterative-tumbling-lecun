import pytest

from tollroute.etl import access_anchors


def _geojson_route(points: list[tuple[float, float]]) -> dict:
    """OSRM-compat route response with geometry through `points` (lat, lon)."""
    return {
        "code": "Ok",
        "routes": [{"geometry": {"coordinates": [[lon, lat] for lat, lon in points]}}],
    }


def _plain_route(duration: float, distance: float) -> dict:
    return {"code": "Ok", "routes": [{"duration": duration, "distance": distance}]}


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

    class _MockEngine:
        def route(self, origin, destination, geometry=False, toll_free=False):
            if geometry:
                # geometry call: reference -> gate
                return _geojson_route([reference, p3, p2, p1, gate])
            # apron call: p2 -> gate
            return _plain_route(12.5, 149.0)

        def one_to_many_table(self, origin, destinations, exclude_toll=False):
            # Only p2 and p3 reachable from reference; p1 is not.
            return [None if d == p1 else (120.0, 500.0) for d in destinations]

    anchor = access_anchors.find_anchor(
        _MockEngine(), gare_id=999, direction="entry", gate_point=gate, reference_points=[reference]
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

    class _MockEngine:
        def route(self, origin, destination, geometry=False, toll_free=False):
            if geometry:
                return _geojson_route([gate, p1, p2, reference])
            # apron call: gate -> p2
            return _plain_route(11.0, 149.0)

        def many_to_one_table(self, sources, destination, exclude_toll=False):
            return [None if s == p1 else (90.0, 200.0) for s in sources]

    anchor = access_anchors.find_anchor(
        _MockEngine(), gare_id=999, direction="exit", gate_point=gate, reference_points=[reference]
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

    class _MockEngine:
        def route(self, origin, destination, geometry=False, toll_free=False):
            return _geojson_route([reference, p1, gate])

        def one_to_many_table(self, origin, destinations, exclude_toll=False):
            return [None for _ in destinations]

    anchor = access_anchors.find_anchor(
        _MockEngine(), gare_id=999, direction="entry", gate_point=gate, reference_points=[reference]
    )

    assert anchor is None
