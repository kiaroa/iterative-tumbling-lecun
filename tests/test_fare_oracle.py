"""Phase 5a fare oracle (tollroute/validation/fare_oracle.py).

Parser unit tests use short verbatim excerpts (a handful of lines) from each
operator's official tariff PDF text, not the full documents - see the module
docstring for why the full extracts aren't committed to this repo. The
fixture check reproduces, at spot-check scale, the full-population
cross-check documented in `reports/phase5a.md` (APRR 21,349/21,349 and AREA
503/503 exact; Cofiroute 10,936/10,936 matched with a small, tight,
vintage-explained deviation).
"""

import pytest

from tollroute.validation import fare_oracle

# Verbatim excerpt from TARIFS_APRR.pdf (pdftotext -layout), "en vigueur au
# 1er fevrier 2026".
APRR_EXCERPT = """\
       Gare d'entrée         Gare de sortie    Distance      Classe 1   Classe 2     Classe 3   Classe 4   Classe 5
                                              tarifaire en
                                                   Km

ALLAINES               AMBERIEU                 462,61       58,20 €    89,10 €      143,00 €   190,70 €   32,80 €
ALLAINES               ARLAY                    403,12       52,30 €    80,90 €      131,70 €   173,90 €   29,10 €
"""

# Verbatim excerpt from TARIFS_AREA.pdf (pdftotext -layout).
AREA_EXCERPT = """\
Code Entrée                Gare d'entrée   Code Sortie        Gare de sortie         Distance      Classe 1     Classe 2   Classe 3   Classe 4   Classe 5
                                                                                    tarifaire en
                                                                                         Km
3007                  AIGUEBELETTE         3010          AIX NORD                       24,00       3,50 €       5,50 €     7,60 €    10,20 €     1,60 €
3007                  AIGUEBELETTE         3009          AIX SUD                        17,00       2,90 €       4,40 €     6,30 €     8,30 €     1,20 €
"""

# Verbatim excerpt from the Cofiroute tariff guide PDF (pdftotext -layout),
# detailed gate-to-gate matrix section (not the earlier "principales
# liaisons" summary table, which this module deliberately skips).
COFIROUTE_EXCERPT = """\
   A11      1    ABLIS                    A10       -    PARIS (LA FOLIE BESSIN)            3,70 €         5,70 €       9,90 €       13,00 €        2,30 €
   A11      1    ABLIS                    A85       -    RESTIGNE                           35,90 €        54,00 €      82,00 €     110,80 €        21,90 €
    A7/A8 Lyon / Marseille - Aix                            28,00 €    45,70 €    60,30 €    81,70 €    17,00 €
"""


def test_parse_aprr_tariff_text():
    records = fare_oracle.parse_aprr_tariff_text(APRR_EXCERPT)
    assert records[("ALLAINES", "AMBERIEU")] == (58.2, 89.1, 143.0, 190.7, 32.8)
    assert records[("ALLAINES", "ARLAY")] == (52.3, 80.9, 131.7, 173.9, 29.1)
    assert len(records) == 2


def test_parse_area_tariff_text():
    records = fare_oracle.parse_area_tariff_text(AREA_EXCERPT)
    assert records[("AIGUEBELETTE", "AIX NORD")] == (3.5, 5.5, 7.6, 10.2, 1.6)
    assert records[("AIGUEBELETTE", "AIX SUD")] == (2.9, 4.4, 6.3, 8.3, 1.2)
    assert len(records) == 2


def test_parse_cofiroute_tariff_text_skips_summary_table():
    records = fare_oracle.parse_cofiroute_tariff_text(COFIROUTE_EXCERPT)
    assert records[("ABLIS", "PARIS (LA FOLIE BESSIN)")] == (3.7, 5.7, 9.9, 13.0, 2.3)
    assert records[("ABLIS", "RESTIGNE")] == (35.9, 54.0, 82.0, 110.8, 21.9)
    # The "Lyon / Marseille - Aix" summary-table row has no route-code/junction
    # prefix and must not be picked up as a gate-to-gate pair.
    assert len(records) == 2


def test_load_fixture_has_20_to_30_pairs_across_operators_and_classes():
    fixture = fare_oracle.load_fixture()
    assert 20 <= len(fixture) <= 30
    assert {row.operator for row in fixture} == {"APRR", "AREA", "Cofiroute"}
    assert {row.vehicle_class for row in fixture} == {1, 2, 3, 4, 5}


def test_fixture_pairs_pass_within_their_stated_tolerance():
    fixture = fare_oracle.load_fixture()
    od_pairs_rows = fare_oracle.load_od_pairs()
    checks = fare_oracle.check_fixture(fixture, od_pairs_rows)
    assert len(checks) == len(fixture)
    failed = [c for c in checks if not c.passed]
    assert failed == []


def test_aprr_and_area_pairs_match_exactly():
    """Current-vintage sources (APRR/AREA, both dated 1 Feb 2026): the
    population-level check in reports/phase5a.md found zero mismatches
    across all 21,852 rows, so the spot-check sample should also be exact,
    not merely within tolerance.
    """
    fixture = fare_oracle.load_fixture()
    od_pairs_rows = fare_oracle.load_od_pairs()
    checks = fare_oracle.check_fixture(fixture, od_pairs_rows)
    for c in checks:
        if c.row.operator in ("APRR", "AREA"):
            assert c.error_pct == pytest.approx(0.0, abs=1e-9)


def test_cofiroute_pairs_show_the_documented_vintage_drift():
    """Prior-vintage source (Cofiroute, dated 1 Feb 2025 - no 2026 edition
    found published): every sampled row should be *at or slightly above* the
    oracle price in od_pairs.csv (the 2026 price), consistent with the
    confirmed ~1.2-1.4% 2026 Cofiroute increase - never *below* it, the way a
    genuine data error could push it in either direction. LE MANS SUD -> LE
    MANS ZI NORD (class 3) lands exactly on 0%: at these small absolute
    values (4,70 EUR) the annual increase rounds away to nothing.
    """
    fixture = fare_oracle.load_fixture()
    od_pairs_rows = fare_oracle.load_od_pairs()
    checks = fare_oracle.check_fixture(fixture, od_pairs_rows)
    cofiroute_checks = [c for c in checks if c.row.operator == "Cofiroute"]
    assert len(cofiroute_checks) == 10
    for c in cofiroute_checks:
        assert 0.0 <= c.error_pct <= 2.5


def test_check_fixture_raises_on_pair_not_in_od_pairs():
    row = fare_oracle.OracleRow(
        operator="APRR",
        from_gare="NOWHERE",
        to_gare="NOWHERE-ELSE",
        vehicle_class=1,
        oracle_price_eur=1.0,
        tolerance_pct=0.5,
        source_name="test",
        source_url="test",
        fetch_date="2026-08-12",
        note="",
    )
    with pytest.raises(KeyError):
        fare_oracle.check_fixture([row], fare_oracle.load_od_pairs())
