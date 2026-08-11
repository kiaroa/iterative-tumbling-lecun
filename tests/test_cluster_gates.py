from tollroute.etl import cluster_gates as cg


def _gate(gare_id, lat, lon, operators, name=""):
    return cg.Gate(
        gare_id=gare_id,
        lat=lat,
        lon=lon,
        operators=frozenset(operators),
        canonical_name=name or f"gate{gare_id}",
    )


def test_exact_coordinates_collapse_to_one_physical_point():
    gates = [
        _gate(4, 48.526501, 1.834938, {"ASFC"}),
        _gate(5, 48.526501, 1.834938, {"Cofiroute"}),
        _gate(9, 45.0, 4.0, {"APRR"}),
    ]

    clusters = cg.cluster_physical_points(gates)

    assert len(clusters) == 2
    ablis = next(c for c in clusters if 4 in c.gare_ids)
    assert ablis.gare_ids == (4, 5)


def test_lookup_maps_every_gare_id_to_its_physical_point():
    gates = [
        _gate(4, 48.526501, 1.834938, {"ASFC"}),
        _gate(5, 48.526501, 1.834938, {"Cofiroute"}),
        _gate(9, 45.0, 4.0, {"APRR"}),
    ]

    lookup = cg.build_lookup(cg.cluster_physical_points(gates))

    assert lookup[4] == lookup[5]
    assert lookup[9] != lookup[4]
    assert set(lookup) == {4, 5, 9}


def test_physical_gate_id_is_stable_by_min_member_gare_id():
    # Insertion order shuffled; ids must still follow ascending min member gare_id.
    gates = [
        _gate(9, 45.0, 4.0, {"APRR"}),
        _gate(5, 48.526501, 1.834938, {"Cofiroute"}),
        _gate(4, 48.526501, 1.834938, {"ASFC"}),
    ]

    clusters = cg.cluster_physical_points(gates)

    assert clusters[0].physical_gate_id == 1 and 4 in clusters[0].gare_ids
    assert clusters[1].physical_gate_id == 2 and clusters[1].gare_ids == (9,)


def test_disjoint_operators_within_radius_are_boundary():
    gates = [
        _gate(4, 48.526501, 1.834938, {"ASFC"}),
        _gate(5, 48.526501, 1.834938, {"Cofiroute"}),
    ]

    edges = cg.type_transfer_edges(gates)

    assert len(edges) == 1
    assert edges[0].transfer_type is cg.TransferType.BOUNDARY
    assert edges[0].dwell_min == 0.0 and edges[0].dwell_km == 0.0


def test_shared_operator_within_radius_is_exit_reentry_with_dwell():
    gates = [
        _gate(10, 46.0, 4.0, {"APRR"}),
        _gate(11, 46.0, 4.0, {"APRR"}),
    ]

    edges = cg.type_transfer_edges(gates)

    assert len(edges) == 1
    assert edges[0].transfer_type is cg.TransferType.EXIT_REENTRY
    assert edges[0].dwell_min == cg.EXIT_REENTRY_DWELL_MIN
    assert edges[0].dwell_km == cg.EXIT_REENTRY_DWELL_KM


def test_gates_beyond_co_location_radius_get_no_transfer_edge():
    gates = [
        _gate(1, 45.0000, 4.0, {"ASFC"}),
        _gate(2, 45.0100, 4.0, {"Cofiroute"}),  # ~1.1 km apart
    ]

    assert cg.type_transfer_edges(gates) == []


def test_full_dataset_yields_815_physical_points_and_pinned_edge_tallies():
    gates, coordinateless = cg.read_gates(cg.DEFAULT_GARE_MASTER_PATH)
    clusters = cg.cluster_physical_points(gates)
    edges = cg.type_transfer_edges(gates)

    # Pinned to the spec's ground-truth figure (953 geocoded gates -> 815
    # distinct physical points) and the transfer-edge tallies computed against
    # the current data files. A change here should be a deliberate re-review.
    assert len(gates) == 953
    assert len(coordinateless) == 3
    assert len(clusters) == 815

    from collections import Counter

    by_type = Counter(e.transfer_type.value for e in edges)
    assert dict(by_type) == {"boundary": 110, "exit_reentry": 71}

    lookup = cg.build_lookup(clusters)
    assert len(lookup) == 953


def test_ablis_cross_operator_boundary_is_verified():
    gates, _ = cg.read_gates(cg.DEFAULT_GARE_MASTER_PATH)
    edges = cg.type_transfer_edges(gates)

    ablis = cg.find_transfer_edge(edges, *cg.ABLIS_GARE_IDS)

    assert ablis is not None
    assert ablis.transfer_type is cg.TransferType.BOUNDARY
    assert ablis.distance_m == 0.0  # ASFC id 4 and Cofiroute id 5 share coordinates


def test_run_writes_report_and_returns_lookup(tmp_path):
    report_path = tmp_path / "phase2c_clustering.md"

    clusters, edges, lookup = cg.run(
        gare_master_path=cg.DEFAULT_GARE_MASTER_PATH,
        report_path=report_path,
    )

    assert report_path.exists()
    report = report_path.read_text()
    assert "815 physical points" in report or "**815 physical points**" in report
    assert "boundary" in report and "exit_reentry" in report
    assert "ABLIS" in report
    assert len(clusters) == 815
    assert len(lookup) == 953
