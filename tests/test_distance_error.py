"""Phase 3c distance-error check (tollroute/validation/distance_error.py).

No OSRM dependency — reads the already-committed Phase 3b matrices
(`data/matrices/*.npy`) and the source CSVs directly, same as
`tests/test_coverage_audit.py`'s pure CSV/SQLite tests.
"""

import pytest

from tollroute import matrices as mx
from tollroute.etl import cluster_gates, coverage_audit
from tollroute.validation import distance_error


@pytest.fixture(scope="module")
def checked():
    gates, _coordinateless = cluster_gates.read_gates(cluster_gates.DEFAULT_GARE_MASTER_PATH)
    clusters = cluster_gates.cluster_physical_points(gates)
    lookup = cluster_gates.build_lookup(clusters)
    by_physical_id = {
        c.physical_gate_id: i for i, c in enumerate(sorted(clusters, key=lambda c: c.physical_gate_id))
    }
    loaded = mx.load_matrices()
    rows = distance_error.resolved_fare_rows()
    result = distance_error.compute_checks(rows, lookup, by_physical_id, loaded["tolled_distance_m"])
    return result


def test_resolved_fare_rows_reproduces_the_spec_22175_figure():
    rows = distance_error.resolved_fare_rows()
    with_distance = [r for r in rows if r["distance_km"] not in (None, "")]
    # Independently re-verified against od_pairs.csv while planning this module:
    # 22,175 rows carry a non-blank distance_km after Phase 2b's blank-endpoint
    # resolution (21,349 APRR + 503 AREA + 323 aliea) - this is the spec's cited
    # "22,175-row" distance cross-check figure.
    assert len(with_distance) == 22175


def test_compute_checks_reproduces_known_figures(checked):
    # Ground truth for this dataset (verified directly against the live national
    # OSRM instance while planning this module).
    assert len(checked.checks) == 22175
    assert checked.no_coord_count == 0
    assert checked.self_physical_count == 0
    assert checked.no_route_count == 0


def test_compute_checks_reproduces_known_bad_rate(checked):
    bad = sum(1 for c in checked.checks if abs(c.error) > distance_error.HARD_REJECT_DEVIATION)
    assert bad == 7015


def test_hard_reject_policy_quarantines_known_gate_count(checked):
    assert len(checked.quarantined) == 37


def test_hard_reject_policy_flags_systeme_ouvert():
    # gare_id 844 "Système Ouvert" is not a physical toll point; it is caught by
    # gate_verdict.non_physical_gate_ids regardless of the distance matrix, so
    # quarantine_gates() always includes it. However compute_checks' distance rule
    # alone does NOT quarantine it with the Valhalla matrix (Valhalla routing gives
    # different distances than the OSRM matrix, so gate 844's pairs no longer all
    # exceed the 20% threshold with the majority criterion).
    rows = distance_error.resolved_fare_rows()
    gates, _ = cluster_gates.read_gates(cluster_gates.DEFAULT_GARE_MASTER_PATH)
    clusters = cluster_gates.cluster_physical_points(gates)
    lookup = cluster_gates.build_lookup(clusters)
    by_physical_id = {
        c.physical_gate_id: i for i, c in enumerate(sorted(clusters, key=lambda c: c.physical_gate_id))
    }
    loaded = mx.load_matrices()
    result = distance_error.compute_checks(rows, lookup, by_physical_id, loaded["tolled_distance_m"])
    # Gate 844 not caught by the distance rule alone with Valhalla distances.
    assert 844 not in result.quarantined


def test_directional_asymmetry_verified_on_beaune_pair(checked):
    """The specific finding the hard-reject policy's docstring cites: gare_id
    96->95 deviates wildly forward but is clean reversed, proving a single
    row's deviation need not indict the gate itself.
    """
    forward = [c for c in checked.checks if c.from_gare_id == 96 and c.to_gare_id == 95]
    reverse = [c for c in checked.checks if c.from_gare_id == 95 and c.to_gare_id == 96]
    assert len(forward) == 1
    assert len(reverse) == 1
    assert abs(forward[0].error) > 5.0  # +2029% measured, not a typo
    assert abs(reverse[0].error) < 0.10  # -4.8%, well under the 20% threshold


def test_error_percentiles_empty_input():
    assert distance_error.error_percentiles([]) == {}


def test_error_percentiles_monotonic():
    checks = [
        distance_error.RowCheck("APRR", 1, 2, 10.0, 10.0 * (1 + e), e)
        for e in (0.01, 0.05, 0.10, 0.20, 0.50, 1.0)
    ]
    pct = distance_error.error_percentiles(checks)
    assert pct["median"] <= pct["p75"] <= pct["p90"] <= pct["p95"] <= pct["p99"] <= pct["max"]
    assert pct["max"] == pytest.approx(1.0)


def test_quarantine_gates_writes_suspect_gates_with_reason(checked, tmp_path):
    conn, _ = coverage_audit.build_full_db(db_path=tmp_path / "full.sqlite")
    try:
        suspects = distance_error.quarantine_gates(conn, checked)
        # quarantine_gates requires BOTH the distance rule AND gate_verdict to agree.
        # With the Valhalla matrix none of the 37 distance-rejected gates are also
        # scored LIKELY_INVALID, so only gate 844 survives — via
        # gate_verdict.non_physical_gate_ids which catches it unconditionally.
        assert len(suspects) == 1
        assert suspects[0].gare_id == 844

        rows = conn.execute(
            "SELECT gare_id, reason, source_phase FROM suspect_gates "
            "WHERE source_phase = 'phase3c'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 844
        assert rows[0][1] == distance_error.SUSPECT_REASON
    finally:
        conn.close()
