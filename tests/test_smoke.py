import sqlite3
from pathlib import Path

import tollroute

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "tollroute" / "db" / "schema.sql"


def test_package_imports():
    assert tollroute is not None


def test_schema_creates_required_tables():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text())

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    conn.close()

    assert {"gates", "fares", "operator_alias", "class_config"} <= tables
