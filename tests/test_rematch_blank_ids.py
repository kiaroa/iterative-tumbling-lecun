from tollroute.etl import rematch_blank_ids as rbi


def _gate(gare_id, canonical_name, aliases=(), operators=("APRR",), lat=None, lon=None):
    return rbi.GateInfo(
        gare_id=gare_id,
        canonical_name=rbi.normalise_name(canonical_name),
        alias_names=frozenset(rbi.normalise_name(a) for a in aliases),
        operators=frozenset(operators),
        lat=lat,
        lon=lon,
    )


def _indexes(gates):
    return rbi.build_name_indexes(gates)


def test_canonical_name_exact_match_wins_over_alias_only_candidate():
    # Mirrors the real MONTLUCON collision: one gate's canonical_name matches
    # exactly, another only lists it as an alias.
    gates = [
        _gate(550, "Peage de Montlucon", aliases=("MONTLUCON", "Peage de Montlucon")),
        _gate(551, "MONTLUCON", aliases=("MONTLUCON",)),
    ]
    canonical_index, alias_index = _indexes(gates)

    gate, rule, reason = rbi.resolve_endpoint(
        name="MONTLUCON",
        operator="APRR",
        known_lat=None,
        known_lon=None,
        distance_km=None,
        canonical_index=canonical_index,
        alias_index=alias_index,
    )

    assert gate.gare_id == 551
    assert rule == "canonical_name_exact_match"


def test_accent_and_case_are_normalised_away():
    gates = [_gate(551, "MONTLUCON")]
    canonical_index, alias_index = _indexes(gates)

    gate, rule, _ = rbi.resolve_endpoint(
        name="montluçon",
        operator="APRR",
        known_lat=None,
        known_lon=None,
        distance_km=None,
        canonical_index=canonical_index,
        alias_index=alias_index,
    )

    assert gate.gare_id == 551
    assert rule == "canonical_name_exact_match"


def test_alias_name_match_when_no_canonical_candidate():
    gates = [_gate(10, "Peage de Foo", aliases=("Foo", "Peage de Foo"))]
    canonical_index, alias_index = _indexes(gates)

    gate, rule, _ = rbi.resolve_endpoint(
        name="Foo",
        operator="APRR",
        known_lat=None,
        known_lon=None,
        distance_km=None,
        canonical_index=canonical_index,
        alias_index=alias_index,
    )

    assert gate.gare_id == 10
    assert rule == "alias_name_match"


def test_coordinate_proximity_breaks_a_duplicate_canonical_name_tie():
    # Two gates share an (unrealistic but test-only) identical canonical name;
    # only one's coordinates are consistent with the row's distance_km from
    # the known endpoint.
    gates = [
        _gate(1, "DUP", operators=("APRR",), lat=46.0, lon=4.0),
        _gate(2, "DUP", operators=("APRR",), lat=48.0, lon=6.0),
    ]
    canonical_index, alias_index = _indexes(gates)
    known_lat, known_lon = 46.01, 4.0  # ~1.1 km from gate 1, ~280 km from gate 2

    gate, rule, _ = rbi.resolve_endpoint(
        name="DUP",
        operator="APRR",
        known_lat=known_lat,
        known_lon=known_lon,
        distance_km=1.0,
        canonical_index=canonical_index,
        alias_index=alias_index,
    )

    assert gate.gare_id == 1
    assert rule == "coordinate_proximity_disambiguation"


def test_operator_tag_disambiguation_when_coordinates_also_tie():
    # Identical coordinates (as with the real MONTLUCON 550/551 pair): the
    # coordinate rule cannot fire, so operator tag membership breaks the tie.
    gates = [
        _gate(550, "MONTLUCON", operators=("ASFC",), lat=46.4, lon=2.7),
        _gate(551, "MONTLUCON", operators=("Cofiroute",), lat=46.4, lon=2.7),
    ]
    canonical_index, alias_index = _indexes(gates)

    gate, rule, _ = rbi.resolve_endpoint(
        name="MONTLUCON",
        operator="Cofiroute",
        known_lat=46.0,
        known_lon=2.0,
        distance_km=50.0,
        canonical_index=canonical_index,
        alias_index=alias_index,
    )

    assert gate.gare_id == 551
    assert rule == "operator_tag_disambiguation"


def test_unresolved_when_every_rule_ties_and_row_is_dropped():
    gates = [
        _gate(550, "MONTLUCON", operators=("APRR", "ASFC"), lat=46.4, lon=2.7),
        _gate(551, "MONTLUCON", operators=("APRR", "Cofiroute"), lat=46.4, lon=2.7),
    ]
    canonical_index, alias_index = _indexes(gates)

    gate, rule, reason = rbi.resolve_endpoint(
        name="MONTLUCON",
        operator="APRR",  # matches both candidates' operator tags
        known_lat=46.0,
        known_lon=2.0,
        distance_km=50.0,
        canonical_index=canonical_index,
        alias_index=alias_index,
    )

    assert gate is None
    assert rule == "default_unresolved"
    assert "550" in reason and "551" in reason


def test_no_candidate_at_all_is_dropped():
    gates = [_gate(1, "SOMEWHERE ELSE")]
    canonical_index, alias_index = _indexes(gates)

    gate, rule, reason = rbi.resolve_endpoint(
        name="NOWHERE",
        operator="APRR",
        known_lat=None,
        known_lon=None,
        distance_km=None,
        canonical_index=canonical_index,
        alias_index=alias_index,
    )

    assert gate is None
    assert rule == "default_unresolved"
    assert "no gate" in reason


def test_rematch_resolves_all_326_blank_endpoints_against_real_data():
    endpoints = rbi.rematch(rbi.DEFAULT_OD_PAIRS_PATH, rbi.DEFAULT_GARE_MASTER_PATH)

    assert len(endpoints) == 326
    assert sum(1 for e in endpoints if e.endpoint == "to") == 163
    assert sum(1 for e in endpoints if e.endpoint == "from") == 163

    # Pinned to the known-good result computed against the current data
    # files (the single MONTLUCON name collision resolves cleanly via
    # canonical_name_exact_match to gare_id 551): a change here should be a
    # deliberate re-review, not a silent drift.
    assert all(e.resolution is rbi.Resolution.MATCHED for e in endpoints)
    assert all(e.matched_gare_id == 551 for e in endpoints)
    assert all(e.rule == "canonical_name_exact_match" for e in endpoints)

    tally = rbi.tally(endpoints)
    assert tally["APRR"]["matched"] == 324
    assert tally["aliea"]["matched"] == 2
    assert sum(sum(c.values()) for c in tally.values()) == 326


def test_blank_endpoints_are_logged_with_per_operator_drop_counts(caplog):
    with caplog.at_level("INFO", logger="tollroute.etl.rematch_blank_ids"):
        endpoints = rbi.rematch(rbi.DEFAULT_OD_PAIRS_PATH, rbi.DEFAULT_GARE_MASTER_PATH)

    endpoint_logs = [r for r in caplog.records if "resolution=" in r.getMessage()]
    assert len(endpoint_logs) == len(endpoints)

    drop_warnings = [r for r in endpoint_logs if r.levelname == "WARNING"]
    assert len(drop_warnings) == sum(1 for e in endpoints if e.resolution is rbi.Resolution.DROP)


def test_render_report_contains_tally_and_per_operator_drop_counts():
    endpoints = rbi.rematch(rbi.DEFAULT_OD_PAIRS_PATH, rbi.DEFAULT_GARE_MASTER_PATH)

    report = rbi.render_report(endpoints)

    assert "**326**" in report
    assert "APRR" in report and "aliea" in report
    assert "canonical_name_exact_match" in report


def test_run_writes_report_file(tmp_path):
    report_path = tmp_path / "phase2b_rematch.md"

    endpoints = rbi.run(
        od_pairs_path=rbi.DEFAULT_OD_PAIRS_PATH,
        gare_master_path=rbi.DEFAULT_GARE_MASTER_PATH,
        report_path=report_path,
    )

    assert report_path.exists()
    assert len(endpoints) == 326
