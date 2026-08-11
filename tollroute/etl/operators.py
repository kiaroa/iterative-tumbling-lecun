"""Operator name normalisation — casefold + hand alias map (Phase 2d).

Run as: python3 -m tollroute.etl.operators [--db PATH]

`iterative-tumbling-lecun.md` Phase 2d requires operator names normalised via a
"casefold + alias map in SQLite" (the `operator_alias` table, defined in
`schema.sql` — a table, deliberately "not source code" per the spec). The 13
raw operator spellings in `od_pairs.csv` are inconsistently cased
(`sanef`/`ASFC`/`escota`/`Cofiroute`/`aliea`/`sapn`/...), so the concrete
normalisation this module applies is **uppercase casefold**: `canonical_operator
= raw_name.upper()`. That alone resolves the spec's "`aliea` may be mis-cased"
worry — `aliea` and any future `ALIEA`/`Aliea` spelling both canonicalise to
`ALIEA`.

**Conjectures flagged (per CLAUDE.md — highlight anything not backed by fact):**

- *Spec conjecture "ASFC = ASF".* There is **no** `ASF` token anywhere in the
  source CSVs (verified against `od_pairs.csv` and `gare_master.csv`), so there
  is nothing to merge and rewriting `ASFC -> ASF` would invent a canonical name
  not backed by the data and desync it from `fares.operator`. `ASFC` is
  therefore kept as its own canonical form; the ASFC=ASF equivalence is recorded
  as a conjecture in `reports/phase2d_coverage.md`, not silently applied.
- Any genuine alternate spelling that later appears can be added to
  ``HAND_ALIASES`` to fold onto an existing canonical name; it is empty today
  because the current 13 names each appear under exactly one spelling.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
from pathlib import Path

from tollroute.etl.load import (
    DEFAULT_DB_PATH,
    DEFAULT_GARE_MASTER_PATH,
    DEFAULT_OD_PAIRS_PATH,
    SCHEMA_PATH,
)

logger = logging.getLogger(__name__)

# Alternate raw spellings that must fold onto a *different* canonical name than
# their plain uppercase would give. Empty on the current dataset (every operator
# appears under one consistent spelling); present so a future stray spelling
# (e.g. "ASF" -> "ASFC", "ALIÉNOR" -> "ALIEA") is a one-line data edit, not code
# surgery. Keyed by the raw string exactly as it appears in the CSV.
HAND_ALIASES: dict[str, str] = {}


def canonical_operator(raw_name: str) -> str:
    """Normalise one raw operator spelling to its canonical form.

    Hand alias first (rare, explicit), otherwise plain uppercase casefold.
    """
    if raw_name in HAND_ALIASES:
        return HAND_ALIASES[raw_name]
    return raw_name.upper()


def _distinct_operators(od_pairs_path: Path, gare_master_path: Path) -> set[str]:
    """Every distinct raw operator spelling across BOTH source CSVs.

    `od_pairs.csv` has a single `operator` column; `gare_master.csv` carries a
    pipe-delimited `operators` field (a gate can belong to several concessions),
    so both are scanned to catch a spelling that appears in one file but not the
    other.
    """
    names: set[str] = set()
    with od_pairs_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["operator"]:
                names.add(row["operator"])
    with gare_master_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for token in row["operators"].split("|"):
                token = token.strip()
                if token:
                    names.add(token)
    return names


def build_alias_map(
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
) -> dict[str, str]:
    """Return the full ``raw_name -> canonical_operator`` map, data-driven."""
    return {
        raw: canonical_operator(raw)
        for raw in _distinct_operators(od_pairs_path, gare_master_path)
    }


def write_operator_alias(conn: sqlite3.Connection, alias_map: dict[str, str]) -> int:
    """Idempotently populate the `operator_alias` table. Returns row count."""
    conn.executemany(
        "INSERT OR REPLACE INTO operator_alias (raw_name, canonical_operator) "
        "VALUES (?, ?)",
        sorted(alias_map.items()),
    )
    return len(alias_map)


def run(
    db_path: Path = DEFAULT_DB_PATH,
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
    gare_master_path: Path = DEFAULT_GARE_MASTER_PATH,
) -> dict[str, str]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        alias_map = build_alias_map(od_pairs_path, gare_master_path)
        write_operator_alias(conn, alias_map)
        conn.commit()
        logger.info(
            "wrote %d operator aliases into %s", len(alias_map), db_path
        )
        for raw, canon in sorted(alias_map.items()):
            marker = "  (uppercased)" if raw != canon else ""
            logger.info("  %-12s -> %s%s", raw, canon, marker)
        return alias_map
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--od-pairs", type=Path, default=DEFAULT_OD_PAIRS_PATH)
    parser.add_argument("--gare-master", type=Path, default=DEFAULT_GARE_MASTER_PATH)
    args = parser.parse_args()
    run(db_path=args.db, od_pairs_path=args.od_pairs, gare_master_path=args.gare_master)


if __name__ == "__main__":
    main()
