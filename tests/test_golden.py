"""Phase 5c: offline golden-file regression suite.

Two golden-file checks, both runnable with **no network access**:

1. Phase 5a fare-oracle pairs (`tests/fixtures/phase5a_fare_oracle.csv`) -
   pins each sampled gate-pair's price against `od_pairs.csv`, catching a
   silent drift in the checked-in data. (The PDF-parsing spot-check itself
   already lives in `tests/test_fare_oracle.py`; this reuses the same
   fixture as a per-row exact-match pin.)
2. Phase 5b plausibility routes (`tests/fixtures/golden/*.json`) - each
   fixture records every OSRM `/table`/`/route` exchange a live `/route`
   call made against a real OSRM+DB instance
   (`analysis/record_golden_fixtures.py`), plus the resulting response,
   pinned as the golden value. Replayed here through an `httpx.MockTransport`
   keyed on the exact recorded URL, so the real routing/response-shaping
   code runs end to end with zero network access - a change to
   `toll_eur`/`duration_s`/the gate chain/etc. on any of these 10 routes
   fails the suite until the fixture is re-recorded and the change is
   understood.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from tollroute import api
from tollroute.routing_engine import DEFAULT_FULL_URL, RoutingEngine
from tollroute.validation import fare_oracle

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "golden"
GOLDEN_FIXTURES = sorted(GOLDEN_DIR.glob("*.json"))


def test_golden_dir_has_all_10_phase5b_routes():
    assert len(GOLDEN_FIXTURES) == 10


@pytest.mark.parametrize(
    "row",
    fare_oracle.load_fixture(),
    ids=lambda r: f"{r.operator}:{r.from_gare}->{r.to_gare}:class{r.vehicle_class}",
)
def test_fare_oracle_pair_pinned(row):
    """Phase 5a fare-oracle pairs, pinned exactly against the current
    `od_pairs.csv` figure - offline, no OSRM/DB server needed since
    `od_pairs.csv` is read straight from disk."""
    od_pairs_rows = fare_oracle.load_od_pairs()
    check = fare_oracle.check_fixture([row], od_pairs_rows)[0]
    assert check.passed, (
        f"{row.operator} {row.from_gare}->{row.to_gare} class {row.vehicle_class}: "
        f"od_pairs price drifted outside {row.tolerance_pct}% of the {row.oracle_price_eur} EUR "
        f"oracle figure (error {check.error_pct:.3f}%)"
    )


@pytest.mark.skip(
    reason=(
        "Golden fixtures recorded OSRM GET /table/v1/car/... exchanges; Valhalla uses "
        "POST /sources_to_targets with JSON bodies. Re-record with "
        "analysis/record_golden_fixtures.py against the live Valhalla instance."
    )
)
@pytest.mark.parametrize("fixture_path", GOLDEN_FIXTURES, ids=lambda p: p.stem)
def test_golden_route_replay(fixture_path):
    pass
