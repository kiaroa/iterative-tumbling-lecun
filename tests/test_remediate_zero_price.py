from tollroute.etl import remediate_zero_price as rzp


def _row(from_id=1, to_id=2, from_gare="A", to_gare="B", operator="APRR", distance_km=""):
    return {
        "from_gare_id": str(from_id),
        "to_gare_id": str(to_id),
        "from_gare": from_gare,
        "to_gare": to_gare,
        "operator": operator,
        "distance_km": distance_km,
        "class1": "0.0",
    }


def test_operator_boundary_short_hop_wins_over_structural_name():
    # Both signals fire; boundary is first in priority order and should win.
    row = _row(from_gare="Bifurcation A vers B", distance_km="3.0")
    gate_lookup = {
        1: rzp.GateInfo(operators=frozenset({"APRR"}), lat=46.0, lon=4.0),
        2: rzp.GateInfo(operators=frozenset({"APRR", "ASFC"}), lat=46.02, lon=4.0),
    }

    result = rzp.classify_zero_price_row(row, gate_lookup)

    assert result.disposition is rzp.Disposition.FREE_TRANSFER
    assert result.rule == "operator_boundary_short_hop"


def test_structural_node_name_free_section_regardless_of_distance():
    row = _row(from_gare="Bifurcation A46S/A7 vers Lyon", to_gare="Far Gate", distance_km="")
    gate_lookup = {
        1: rzp.GateInfo(operators=frozenset({"ASFC"}), lat=45.0, lon=4.0),
        2: rzp.GateInfo(operators=frozenset({"ASFC"}), lat=48.0, lon=2.0),  # far away
    }

    result = rzp.classify_zero_price_row(row, gate_lookup)

    assert result.disposition is rzp.Disposition.FREE_SECTION
    assert result.rule == "structural_node_name"


def test_short_physical_hop_free_section_without_other_signals():
    row = _row(distance_km="")
    gate_lookup = {
        1: rzp.GateInfo(operators=frozenset({"APRR"}), lat=46.0, lon=4.0),
        2: rzp.GateInfo(operators=frozenset({"APRR"}), lat=46.03, lon=4.0),  # ~3.3 km
    }

    result = rzp.classify_zero_price_row(row, gate_lookup)

    assert result.disposition is rzp.Disposition.FREE_SECTION
    assert result.rule == "short_physical_hop"


def test_far_apart_same_operator_no_name_signal_is_dropped():
    row = _row(distance_km="")
    gate_lookup = {
        1: rzp.GateInfo(operators=frozenset({"ASFC"}), lat=44.0, lon=1.0),
        2: rzp.GateInfo(operators=frozenset({"ASFC"}), lat=45.0, lon=4.0),  # well over 8 km
    }

    result = rzp.classify_zero_price_row(row, gate_lookup)

    assert result.disposition is rzp.Disposition.DROP
    assert result.rule == "default_no_signal"


def test_missing_coordinates_falls_back_to_od_pairs_distance_km():
    row = _row(distance_km="5.5")
    gate_lookup = {
        1: rzp.GateInfo(operators=frozenset({"APRR"}), lat=None, lon=None),
        2: rzp.GateInfo(operators=frozenset({"APRR"}), lat=None, lon=None),
    }

    result = rzp.classify_zero_price_row(row, gate_lookup)

    assert result.disposition is rzp.Disposition.FREE_SECTION
    assert result.rule == "short_physical_hop"
    assert result.distance_km == 5.5


def test_missing_coordinates_and_no_od_pairs_distance_is_dropped():
    row = _row(distance_km="")
    gate_lookup = {
        1: rzp.GateInfo(operators=frozenset({"APRR"}), lat=None, lon=None),
        2: rzp.GateInfo(operators=frozenset({"APRR"}), lat=None, lon=None),
    }

    result = rzp.classify_zero_price_row(row, gate_lookup)

    assert result.disposition is rzp.Disposition.DROP
    assert result.distance_km is None


def test_remediate_gives_every_one_of_the_551_rows_a_disposition():
    classified = rzp.remediate(rzp.DEFAULT_OD_PAIRS_PATH, rzp.DEFAULT_GARE_MASTER_PATH)

    expected_row_count = len(rzp.read_zero_price_rows(rzp.DEFAULT_OD_PAIRS_PATH))
    assert expected_row_count == 551
    assert len(classified) == expected_row_count
    assert all(isinstance(r.disposition, rzp.Disposition) for r in classified)

    tally = rzp.tally(classified)
    assert sum(sum(c.values()) for c in tally.values()) == expected_row_count

    overall = {}
    for counts in tally.values():
        for disposition, n in counts.items():
            overall[disposition] = overall.get(disposition, 0) + n
    # Pinned to the known-good clustering computed against the current data
    # files; a change here should be a deliberate re-review, not a silent drift.
    assert overall == {"free_section": 307, "free_transfer": 6, "drop": 238}


def test_zero_price_rows_are_logged_not_dropped(caplog):
    with caplog.at_level("INFO", logger="tollroute.etl.remediate_zero_price"):
        classified = rzp.remediate(rzp.DEFAULT_OD_PAIRS_PATH, rzp.DEFAULT_GARE_MASTER_PATH)

    disposition_logs = [r for r in caplog.records if "zero-price row disposition=" in r.getMessage()]
    assert len(disposition_logs) == len(classified)

    drop_warnings = [r for r in disposition_logs if r.levelname == "WARNING"]
    assert len(drop_warnings) == sum(1 for r in classified if r.disposition is rzp.Disposition.DROP)


def test_render_report_contains_overall_tally_and_all_dispositions(tmp_path):
    classified = rzp.remediate(rzp.DEFAULT_OD_PAIRS_PATH, rzp.DEFAULT_GARE_MASTER_PATH)

    report = rzp.render_report(classified)

    assert "free_section" in report
    assert "free_transfer" in report
    assert "drop" in report
    assert "**551**" in report


def test_run_writes_report_file(tmp_path):
    report_path = tmp_path / "phase2b_zero_price.md"

    classified = rzp.run(
        od_pairs_path=rzp.DEFAULT_OD_PAIRS_PATH,
        gare_master_path=rzp.DEFAULT_GARE_MASTER_PATH,
        report_path=report_path,
    )

    assert report_path.exists()
    assert len(classified) == 551
