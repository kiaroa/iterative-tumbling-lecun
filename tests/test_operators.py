"""Phase 2d operator alias map (tollroute/etl/operators.py)."""

import sqlite3

from tollroute.etl import operators
from tollroute.etl.load import SCHEMA_PATH

# The 13 raw operator spellings present in the source CSVs (ground truth,
# IMPLEMENTATION_PLAN.md), and their expected uppercase canonical form.
EXPECTED_CANONICAL = {
    "APRR": "APRR",
    "ASFC": "ASFC",
    "Cofiroute": "COFIROUTE",
    "sanef": "SANEF",
    "escota": "ESCOTA",
    "AREA": "AREA",
    "aliea": "ALIEA",
    "sapn": "SAPN",
    "SFTRF": "SFTRF",
    "Landes": "LANDES",
    "ALIS": "ALIS",
    "Alicorne": "ALICORNE",
    "ATMB": "ATMB",
}


def test_canonical_operator_uppercases():
    assert operators.canonical_operator("Cofiroute") == "COFIROUTE"
    assert operators.canonical_operator("sanef") == "SANEF"
    assert operators.canonical_operator("APRR") == "APRR"


def test_canonical_operator_resolves_aliea_miscasing():
    # Spec conjecture "aliea may be mis-cased" is resolved by the uppercase
    # casefold: any casing folds onto the single canonical ALIEA.
    assert operators.canonical_operator("aliea") == "ALIEA"
    assert operators.canonical_operator("ALIEA") == "ALIEA"
    assert operators.canonical_operator("Aliea") == "ALIEA"


def test_build_alias_map_covers_all_operators():
    alias_map = operators.build_alias_map()
    for raw, canonical in EXPECTED_CANONICAL.items():
        assert alias_map[raw] == canonical, raw
    # No stray operators beyond the known 13.
    assert set(alias_map) == set(EXPECTED_CANONICAL)


def test_asfc_conjecture_not_silently_applied():
    # Spec conjectures ASFC = ASF; with no ASF token in the data we must NOT
    # rename ASFC -> ASF on an unverified equivalence.
    alias_map = operators.build_alias_map()
    assert alias_map["ASFC"] == "ASFC"
    assert "ASF" not in alias_map


def test_write_operator_alias_populates_table():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        n = operators.write_operator_alias(conn, operators.build_alias_map())
        assert n == 13
        rows = dict(
            conn.execute(
                "SELECT raw_name, canonical_operator FROM operator_alias"
            ).fetchall()
        )
        assert rows["aliea"] == "ALIEA"
        assert rows["ASFC"] == "ASFC"
        assert rows["Cofiroute"] == "COFIROUTE"
    finally:
        conn.close()
