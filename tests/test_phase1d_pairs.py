"""Phase 1d validation of the 5 named APRR test pairs against `od_pairs` and OSRM.

This item's three checks (iterative-tumbling-lecun.md Phase 1d) are:
  1. Price:      direct gate-to-gate tolled route == `od_pairs` class1 exactly.
  2. Guard rail: >=1 cheaper alternative adds >=10 km AND >=5 min vs the tolled route.
  3. Distance:   OSRM tolled route distance within "a few percent" of `distance_km`.

Outcome of the investigation (full write-up: reports/phase1d_pair_validation.md):

  * Check 1 PASSES for all 4 fare pairs (pair 3 is the deliberate no-fare A75 edge
    case) - the graph wires class1 straight through, verified here.

  * Check 3 FAILS at regional/gate-node scale. Well-snapped corridor gates
    (<8 m snap) still produce OSRM tolled routes 7-36% longer than `distance_km`,
    because the destination gate coordinate snaps to a single directional
    carriageway node: a route arriving from the opposite carriageway overshoots
    to the next interchange and U-turns back (verified: reverse-direction and
    overshoot-corrected distances land within ~1.5% for pairs 1 and 4). Pair 2's
    Paris gate is outside the regional bfc-ara extract entirely (71 km snap) and
    is not testable until the Phase 3a national build. A broader 6-pair spot-check
    (in the report) shows the same 28-94% inflation, so this is systemic, not a
    property of these 3 corridors - it is Phase 3c's national snap-quality +
    distance-error audit that resolves it, not this item.

  * Check 2 FAILS the *literal* ">=10 km AND >=5 min" wording. The toll-free
    alternative to each A6 pair is much slower (+32 to +112 min, so the >=5 min
    half always holds) but NOT longer (-0.3 to -33 km, so the >=10 km half never
    holds) - N-roads paralleling a French motorway are similar length, just
    slower. The guard rail needs a documented interpretation (OR, or time-only)
    before it is testable; that is a Phase 4b concern.

Per the project's Phase 0 precedent (a genuine finding is documented in a report
and filed as a new blocking plan item rather than silently forced to pass), the
two failing checks are encoded here as non-strict `xfail`s pointing at the report
and the new Phase 1d-follow-up plan item. The suite therefore stays green while
the failures remain visible and self-documenting. `test_uturn_overshoot_explains
_distance_gap` turns the root-cause claim into a *passing* positive assertion for
pairs 1 and 4, so the diagnosis is regression-guarded, not just prose.

All OSRM-dependent tests skip cleanly when no live instance is reachable, using
the same `requires_osrm` pattern as tests/test_routing.py.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import httpx
import pytest

from tollroute import graph as graph_mod
from tollroute import routing
from tollroute.etl import load, snap_report

REPORT = "reports/phase1d_pair_validation.md"

# "A few percent" - justified in the report: with a clean, single-carriageway
# snap and no U-turn, OSRM motorway routing agrees with the operator's tariff
# distance_km to ~1.5% (demonstrated via the reverse-direction and
# overshoot-corrected distances). 5% is a generous "few percent" ceiling.
DISTANCE_TOLERANCE = 0.05

# Guard-rail thresholds, taken verbatim from the spec's "Guard rails" section.
GUARDRAIL_MIN_EXTRA_KM = 10.0
GUARDRAIL_MIN_EXTRA_MIN = 5.0

# (label, from_gare_id, to_gare_id, od distance_km, od class1) for the 4 real
# APRR fare pairs. Values verified against the loaded `fares` table 2026-08-11.
# Pair 3 (Clermont-Ferrand -> Montpellier) has no APRR fare row at all (A75 is
# untolled) and is handled as an explicit skip in the price test below.
PAIR1 = ("1 Dijon->Lyon", 269, 930, 149.15, 14.10)
PAIR2 = ("2 Paris->Lyon", 393, 930, 493.17, 62.80)
PAIR4 = ("4 Dijon->Macon", 269, 495, 118.93, 11.10)
PAIR5 = ("5 Beaune->Macon", 96, 494, 74.10, 6.60)


def _osrm_reachable() -> bool:
    try:
        httpx.get(f"{snap_report.DEFAULT_OSRM_BASE_URL}/nearest/v1/car/5.0,47.0", timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live OSRM instance not reachable on DEFAULT_OSRM_BASE_URL"
)


@pytest.fixture(scope="module")
def base_graph():
    # Same build path as tests/test_routing.py: load APRR into a throwaway DB,
    # snap every gate, then build the overlay graph once for the whole module.
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "tollroute.sqlite"
        load.run(
            db_path=db_path,
            od_pairs_path=load.DEFAULT_OD_PAIRS_PATH,
            gare_master_path=load.DEFAULT_GARE_MASTER_PATH,
        )
        conn = sqlite3.connect(db_path)
        try:
            with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
                snap_report.snap_all_gates(conn, client)
                g = graph_mod.build_graph(conn)
        finally:
            conn.close()
    return g


def _osrm_route(
    client: httpx.Client,
    origin: tuple[float, float],
    destination: tuple[float, float],
    exclude_toll: bool,
    geometry: bool = False,
) -> dict:
    o_lat, o_lon = origin
    d_lat, d_lon = destination
    params = "overview=full&geometries=geojson" if geometry else "overview=false"
    if exclude_toll:
        params += "&exclude=toll"
    resp = client.get(f"/route/v1/car/{o_lon},{o_lat};{d_lon},{d_lat}?{params}")
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != "Ok":
        raise RuntimeError(f"OSRM /route failed for {origin}->{destination}: {data}")
    return data["routes"][0]


# --- Check 1: price ----------------------------------------------------------


@requires_osrm
@pytest.mark.parametrize(
    "label,from_id,to_id,distance_km,class1",
    [
        pytest.param(*PAIR1, id=PAIR1[0]),
        pytest.param(*PAIR2, id=PAIR2[0]),
        pytest.param(
            "3 Clermont->Montpellier",
            None,
            None,
            None,
            None,
            marks=pytest.mark.skip(
                reason="pair 3 is the A75-untolled edge case: no APRR fare row exists "
                "(iterative-tumbling-lecun.md Phase 1b), so there is no direct-toll price to check"
            ),
            id="3 Clermont->Montpellier",
        ),
        pytest.param(*PAIR4, id=PAIR4[0]),
        pytest.param(*PAIR5, id=PAIR5[0]),
    ],
)
def test_direct_toll_edge_matches_od_pairs(base_graph, label, from_id, to_id, distance_km, class1):
    """The single gate-to-gate TOLL edge carries exactly the `od_pairs` class1 price."""
    route = routing.find_route(
        base_graph,
        graph_mod.Node(from_id, graph_mod.NodeRole.OUT),
        graph_mod.Node(to_id, graph_mod.NodeRole.IN_TOLL),
        vehicle_class=1,
    )
    assert len(route.edges) == 1
    assert route.edges[0].edge_type == graph_mod.EdgeType.TOLL
    assert route.toll_eur == pytest.approx(class1)


# --- Check 3: OSRM tolled distance vs distance_km ----------------------------

_DIST_XFAIL = pytest.mark.xfail(
    strict=False,
    reason=f"carriageway-snap U-turn detour inflates gate-node OSRM distance beyond "
    f"{DISTANCE_TOLERANCE:.0%}; systemic (see {REPORT}); resolved by Phase 3c national "
    "snap-quality + distance-error audit, not this item",
)
_DIST_SKIP = pytest.mark.skip(
    reason="gate 393 (Paris) is outside the regional bfc-ara extract (71 km snap); "
    "OSRM distance is not meaningful until the Phase 3a national build"
)


@requires_osrm
@pytest.mark.parametrize(
    "label,from_id,to_id,distance_km,class1",
    [
        pytest.param(*PAIR1, id=PAIR1[0], marks=_DIST_XFAIL),
        pytest.param(*PAIR2, id=PAIR2[0], marks=_DIST_SKIP),
        pytest.param(*PAIR4, id=PAIR4[0], marks=_DIST_XFAIL),
        pytest.param(*PAIR5, id=PAIR5[0], marks=_DIST_XFAIL),
    ],
)
def test_osrm_tolled_distance_within_tolerance(
    base_graph, label, from_id, to_id, distance_km, class1
):
    """OSRM tolled gate-to-gate distance should match `distance_km` within a few percent.

    Expected to fail at regional/gate-node scale - see the module docstring and report.
    """
    o = base_graph.gate_coords[from_id]
    d = base_graph.gate_coords[to_id]
    with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
        tolled = _osrm_route(client, o, d, exclude_toll=False)
    rel_err = abs(tolled["distance"] - distance_km * 1000.0) / (distance_km * 1000.0)
    assert rel_err <= DISTANCE_TOLERANCE, (
        f"{label}: OSRM {tolled['distance']:.0f} m vs distance_km {distance_km * 1000:.0f} m "
        f"= {rel_err:.1%} > {DISTANCE_TOLERANCE:.0%}"
    )


@requires_osrm
@pytest.mark.parametrize(
    "label,from_id,to_id,distance_km,class1",
    [
        pytest.param(*PAIR1, id=PAIR1[0]),
        pytest.param(*PAIR4, id=PAIR4[0]),
        pytest.param(
            *PAIR5,
            id=PAIR5[0],
            marks=pytest.mark.xfail(
                strict=False,
                reason="pair 5 has a smaller (~4 km) overshoot; correcting it still leaves "
                f"~8% residual (see {REPORT}) - the U-turn is not the sole error source here",
            ),
        ),
    ],
)
def test_uturn_overshoot_explains_distance_gap(
    base_graph, label, from_id, to_id, distance_km, class1
):
    """Positive check on the root cause: removing the southward U-turn overshoot from the
    forward tolled distance recovers `distance_km` within ~3%.

    All these pairs run north -> south (Dijon/Beaune -> Lyon/Macon), so the detour shows up
    as the route dipping to a latitude *south* of the destination gate before doubling back.
    corrected = forward_distance - 2 * (that overshoot). This encodes the carriageway-snap
    diagnosis as a checked assertion, so it can regress rather than merely being asserted in prose.
    """
    o = base_graph.gate_coords[from_id]
    d = base_graph.gate_coords[to_id]
    dest_lat = d[0]
    with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
        tolled = _osrm_route(client, o, d, exclude_toll=False, geometry=True)
    min_lat = min(pt[1] for pt in tolled["geometry"]["coordinates"])
    overshoot_m = max(0.0, (dest_lat - min_lat)) * 111_000.0  # deg lat -> m (~111 km/deg)
    corrected_m = tolled["distance"] - 2.0 * overshoot_m
    rel_err = abs(corrected_m - distance_km * 1000.0) / (distance_km * 1000.0)
    assert rel_err <= 0.03, (
        f"{label}: overshoot-corrected {corrected_m:.0f} m (raw {tolled['distance']:.0f} m, "
        f"overshoot {overshoot_m:.0f} m) vs distance_km {distance_km * 1000:.0f} m = {rel_err:.1%}"
    )


# --- Check 2: guard-rail / cheaper alternative -------------------------------


@requires_osrm
@pytest.mark.parametrize(
    "label,from_id,to_id,distance_km,class1",
    [
        pytest.param(
            *PAIR1,
            id=PAIR1[0],
            marks=pytest.mark.xfail(
                strict=False,
                reason="literal '>=10 km AND >=5 min' fails: the toll-free A6 alternative is "
                f"much slower but not >=10 km longer (see {REPORT}); guard-rail wording needs a "
                "documented interpretation (Phase 4b)",
            ),
        ),
        pytest.param(*PAIR2, id=PAIR2[0], marks=_DIST_SKIP),
        pytest.param(
            *PAIR4,
            id=PAIR4[0],
            marks=pytest.mark.xfail(
                strict=False,
                reason="literal '>=10 km AND >=5 min' fails: the toll-free alternative is "
                f"actually shorter here, just slower (see {REPORT})",
            ),
        ),
        pytest.param(
            *PAIR5,
            id=PAIR5[0],
            marks=pytest.mark.xfail(
                strict=False,
                reason="literal '>=10 km AND >=5 min' fails: the toll-free alternative is "
                f"~same length, just slower (see {REPORT})",
            ),
        ),
    ],
)
def test_cheaper_alternative_meets_guardrails(
    base_graph, label, from_id, to_id, distance_km, class1
):
    """The cheaper (toll-free, EUR 0) alternative must add >=10 km AND >=5 min vs the tolled route.

    Methodology (documented in the report): the "cheaper alternative" is the plain OSRM
    `exclude=toll` gate-to-gate route - this is exactly the EUR 0 option the overlay graph would
    surface against the tolled EUR{class1} direct edge, so a raw point-to-point OSRM pair is the
    most faithful, least-assumption way to measure its extra km/min. Expected to fail the distance
    half - see the module docstring.
    """
    o = base_graph.gate_coords[from_id]
    d = base_graph.gate_coords[to_id]
    with httpx.Client(base_url=snap_report.DEFAULT_OSRM_BASE_URL, timeout=30.0) as client:
        tolled = _osrm_route(client, o, d, exclude_toll=False)
        toll_free = _osrm_route(client, o, d, exclude_toll=True)
    extra_km = (toll_free["distance"] - tolled["distance"]) / 1000.0
    extra_min = (toll_free["duration"] - tolled["duration"]) / 60.0
    # The time half of the guard rail genuinely holds for every A6 pair; it is the
    # distance half that fails, which is the finding.
    assert extra_min >= GUARDRAIL_MIN_EXTRA_MIN, (
        f"{label}: toll-free only +{extra_min:.1f} min (expected the time half to hold)"
    )
    assert extra_km >= GUARDRAIL_MIN_EXTRA_KM, (
        f"{label}: toll-free adds {extra_km:+.1f} km (< {GUARDRAIL_MIN_EXTRA_KM} km guard rail)"
    )
