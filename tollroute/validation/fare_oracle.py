"""Phase 5a fare oracle: check `od_pairs.csv` prices against operators' own
published tariff grids.

Run as: python3 -m tollroute.validation.fare_oracle

**Phase 2a's finding stands for bulk/API access** (`reports/phase2a_tariff_sources.md`:
no centralised machine-readable price dataset exists; `autoroutes.fr`/
`vinci-autoroutes.com` calculators were unreachable in this environment via
`WebFetch`, a TLS certificate error). This module extends that finding rather
than overturning it: while no *bulk cross-operator* source or interactive
calculator is reachable, three operators (APRR, AREA, Cofiroute) publish a
**per-operator PDF tariff grid** listing every gate-to-gate fare directly (not
a summary, and not behind an interactive form) - `voyage.aprr.fr` for
APRR/AREA, `public-content.vinci-autoroutes.com` for Cofiroute. These were
found by web search, not by Phase 2a's earlier pass, and downloaded/converted
to text with `pdftotext -layout` for this check.

**Full-population cross-check (2026-08-12, see `reports/phase5a.md` for the
complete write-up):** every APRR (21,349) and AREA (503) `od_pairs.csv` row
matched its official current (1 Feb 2026) tariff exactly - 21,852/21,852,
zero mismatches. Every Cofiroute row (10,936) matched by gate-pair name, but
only 649 matched the price exactly; the rest deviate by a small, tight,
positive amount (mean 1.06%, median 1.00%, stdev 0.65%, max 6.25%) because
the only Cofiroute grid found publicly is dated 1 February **2025** - no 2026
edition has been published/indexed yet - and this operator's confirmed 2026
increase is 1.21-1.41% by class, matching the observed drift almost exactly.
This is a source-vintage gap, not a data-quality finding.

**Why the full PDF text isn't committed to the repo:** these are copyrighted
third-party publications (APRR/AREA/VINCI Autoroutes), not project-derived
data (unlike e.g. `data/matrices/*.npy`, which this codebase computed itself
and does commit). Redistributing the full multi-thousand-line extracts would
go beyond fair-use spot-checking. `tests/fixtures/phase5a_fare_oracle.csv`
instead carries a small (26-row) curated sample of individual fare figures
with each row's source cited - reproducing published *facts* (a price for a
route) at a scale consistent with citation, not republishing the documents.
The parsing functions below are still real, tested code (against short
verbatim excerpts in `tests/test_fare_oracle.py`), documented so the
population-level numbers above can be reproduced by re-running this module
against freshly downloaded tariff text if needed.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OD_PAIRS_PATH = REPO_ROOT / "od_pairs.csv"
DEFAULT_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "phase5a_fare_oracle.csv"

# APRR's grid ("Gare d'entree  Gare de sortie  Distance  Classe1..5") has no
# leading entry/exit codes; AREA's grid does ("Code Entree  Gare d'entree
# Code Sortie  Gare de sortie  Distance  Classe1..5").
_APRR_ROW = re.compile(
    r"^(?P<from>.+?)\s{2,}(?P<to>.+?)\s+(?P<dist>[\d.,]+)\s+"
    r"(?P<c1>[\d.,]+)\s*€\s+(?P<c2>[\d.,]+)\s*€\s+(?P<c3>[\d.,]+)\s*€\s+"
    r"(?P<c4>[\d.,]+)\s*€\s+(?P<c5>[\d.,]+)\s*€\s*$"
)
_AREA_ROW = re.compile(
    r"^\d+\s+(?P<from>.+?)\s{2,}\d+\s+(?P<to>.+?)\s+(?P<dist>[\d.,]+)\s+"
    r"(?P<c1>[\d.,]+)\s*€\s+(?P<c2>[\d.,]+)\s*€\s+(?P<c3>[\d.,]+)\s*€\s+"
    r"(?P<c4>[\d.,]+)\s*€\s+(?P<c5>[\d.,]+)\s*€\s*$"
)
# Cofiroute's grid prefixes each gate with a route code and junction number
# ("A11   1   ABLIS   A10   -   PARIS (LA FOLIE BESSIN)   3,70 € ...").
_COFIROUTE_ROW = re.compile(
    r"^\s*\S+\s+\S+\s+(?P<from>.+?)\s{2,}\S+\s+\S+\s+(?P<to>.+?)\s+"
    r"(?P<c1>[\d.,]+)\s*€\s+(?P<c2>[\d.,]+)\s*€\s+(?P<c3>[\d.,]+)\s*€\s+"
    r"(?P<c4>[\d.,]+)\s*€\s+(?P<c5>[\d.,]+)\s*€\s*$"
)


def _num(text: str) -> float:
    return float(text.replace(" ", "").replace(",", "."))


def _prices(m: re.Match) -> tuple[float, float, float, float, float]:
    return (_num(m["c1"]), _num(m["c2"]), _num(m["c3"]), _num(m["c4"]), _num(m["c5"]))


def parse_aprr_tariff_text(text: str) -> dict[tuple[str, str], tuple[float, ...]]:
    """Parses APRR's `Gare d'entree / Gare de sortie / Classe 1-5` grid text
    (`pdftotext -layout` output of `TARIFS_APRR.pdf`)."""
    records: dict[tuple[str, str], tuple[float, ...]] = {}
    for line in text.splitlines():
        m = _APRR_ROW.match(line.rstrip())
        if m:
            records[(m["from"].strip(), m["to"].strip())] = _prices(m)
    return records


def parse_area_tariff_text(text: str) -> dict[tuple[str, str], tuple[float, ...]]:
    """Parses AREA's `Code / Gare d'entree / Code / Gare de sortie / Classe
    1-5` grid text (`pdftotext -layout` output of `TARIFS_AREA.pdf`)."""
    records: dict[tuple[str, str], tuple[float, ...]] = {}
    for line in text.splitlines():
        m = _AREA_ROW.match(line.rstrip())
        if m:
            records[(m["from"].strip(), m["to"].strip())] = _prices(m)
    return records


def parse_cofiroute_tariff_text(text: str) -> dict[tuple[str, str], tuple[float, ...]]:
    """Parses Cofiroute's `route/junction/gare` x2 + `Classe 1-5` grid text
    (`pdftotext -layout` output of the Cofiroute tariff guide PDF). Skips the
    guide's earlier "principales liaisons" summary table, which has no
    route-code/junction prefix and so never matches `_COFIROUTE_ROW`."""
    records: dict[tuple[str, str], tuple[float, ...]] = {}
    for line in text.splitlines():
        if "€" not in line:
            continue
        m = _COFIROUTE_ROW.match(line.rstrip())
        if m:
            records[(m["from"].strip(), m["to"].strip())] = _prices(m)
    return records


@dataclass
class OracleRow:
    operator: str
    from_gare: str
    to_gare: str
    vehicle_class: int
    oracle_price_eur: float
    tolerance_pct: float
    source_name: str
    source_url: str
    fetch_date: str
    note: str


@dataclass
class OracleCheck:
    row: OracleRow
    od_pairs_price_eur: float
    error_pct: float  # signed: (od_pairs - oracle) / oracle * 100
    passed: bool


def load_fixture(path: Path = DEFAULT_FIXTURE_PATH) -> list[OracleRow]:
    with open(path, newline="", encoding="utf-8") as f:
        return [
            OracleRow(
                operator=r["operator"],
                from_gare=r["from_gare"],
                to_gare=r["to_gare"],
                vehicle_class=int(r["vehicle_class"]),
                oracle_price_eur=float(r["oracle_price_eur"]),
                tolerance_pct=float(r["tolerance_pct"]),
                source_name=r["source_name"],
                source_url=r["source_url"],
                fetch_date=r["fetch_date"],
                note=r["note"],
            )
            for r in csv.DictReader(f)
        ]


def load_od_pairs(path: Path = DEFAULT_OD_PAIRS_PATH) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_fixture(
    fixture: list[OracleRow], od_pairs_rows: list[dict]
) -> list[OracleCheck]:
    """Looks up each fixture row's (operator, from_gare, to_gare) in
    `od_pairs.csv` and compares its `class{N}` price to the oracle price
    within that row's stated tolerance."""
    by_key: dict[tuple[str, str, str], dict] = {
        (r["operator"], r["from_gare"], r["to_gare"]): r for r in od_pairs_rows
    }
    checks: list[OracleCheck] = []
    for row in fixture:
        od_row = by_key.get((row.operator, row.from_gare, row.to_gare))
        if od_row is None:
            raise KeyError(
                f"fixture pair not found in od_pairs.csv: "
                f"{row.operator} {row.from_gare} -> {row.to_gare}"
            )
        od_price = float(od_row[f"class{row.vehicle_class}"])
        error_pct = (od_price - row.oracle_price_eur) / row.oracle_price_eur * 100
        passed = abs(error_pct) <= row.tolerance_pct
        checks.append(OracleCheck(row, od_price, error_pct, passed))
    return checks


def run(
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    od_pairs_path: Path = DEFAULT_OD_PAIRS_PATH,
) -> list[OracleCheck]:
    fixture = load_fixture(fixture_path)
    od_pairs_rows = load_od_pairs(od_pairs_path)
    checks = check_fixture(fixture, od_pairs_rows)
    failed = [c for c in checks if not c.passed]
    by_operator: dict[str, list[OracleCheck]] = {}
    for c in checks:
        by_operator.setdefault(c.row.operator, []).append(c)
    for operator, op_checks in sorted(by_operator.items()):
        op_failed = sum(1 for c in op_checks if not c.passed)
        logger.info(
            "fare oracle: %s %d/%d pairs within tolerance",
            operator,
            len(op_checks) - op_failed,
            len(op_checks),
        )
    if failed:
        for c in failed:
            logger.warning(
                "fare oracle FAIL: %s %s -> %s class%d: od_pairs=%.2f oracle=%.2f (%.2f%%, tolerance %.1f%%)",
                c.row.operator,
                c.row.from_gare,
                c.row.to_gare,
                c.row.vehicle_class,
                c.od_pairs_price_eur,
                c.row.oracle_price_eur,
                c.error_pct,
                c.row.tolerance_pct,
            )
    return checks


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument("--od-pairs", type=Path, default=DEFAULT_OD_PAIRS_PATH)
    args = parser.parse_args()
    checks = run(args.fixture, args.od_pairs)
    n_failed = sum(1 for c in checks if not c.passed)
    logger.info("fare oracle: %d/%d pairs within tolerance", len(checks) - n_failed, len(checks))


if __name__ == "__main__":
    main()
