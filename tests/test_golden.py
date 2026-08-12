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
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL
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


def _mock_osrm_transport(exchanges: list[dict]) -> httpx.MockTransport:
    """Replays recorded OSRM responses keyed on the exact request URL the
    production `osrm_client` code builds - identical DB/coordinates produce
    identical URLs, so an exact string match is a fair replacement for a
    live OSRM instance. Raises loudly (rather than falling through to the
    network) if the code under test issues a request the fixture didn't
    record, e.g. because a code change added/removed an OSRM call.
    """
    by_url: dict[str, list[dict]] = {}
    for exchange in exchanges:
        by_url.setdefault(exchange["url"], []).append(exchange)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        recorded = by_url.get(url)
        if not recorded:
            raise AssertionError(f"golden replay: no recorded OSRM exchange for {url}")
        exchange = recorded.pop(0)
        return httpx.Response(exchange["status_code"], json=exchange["body"])

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("fixture_path", GOLDEN_FIXTURES, ids=lambda p: p.stem)
def test_golden_route_replay(fixture_path):
    fixture = json.loads(fixture_path.read_text())

    with TestClient(api.app) as client:
        real_osrm_client = api.app.state.osrm_client
        api.app.state.osrm_client = httpx.Client(
            base_url=DEFAULT_OSRM_BASE_URL, transport=_mock_osrm_transport(fixture["exchanges"])
        )
        try:
            resp = client.get(
                "/route",
                params={
                    "origin_lat": fixture["origin"][0],
                    "origin_lon": fixture["origin"][1],
                    "destination_lat": fixture["destination"][0],
                    "destination_lon": fixture["destination"][1],
                    "vehicle_class": fixture["vehicle_class"],
                },
            )
        finally:
            api.app.state.osrm_client.close()
            api.app.state.osrm_client = real_osrm_client

    assert resp.status_code == 200
    assert resp.json() == fixture["expected"], (
        f"{fixture['origin_name']} -> {fixture['dest_name']}: response diverged from the "
        "recorded golden value - re-run analysis/record_golden_fixtures.py and confirm the "
        "change is understood before updating the fixture"
    )
