"""Phase 5c: record OSRM request/response fixtures for the offline golden-file
suite (`tests/test_golden.py`).

Drives the real `tollroute.api` app in-process (FastAPI `TestClient`, same
pattern as `tests/test_api.py`) against a **live** OSRM instance, recording
every OSRM exchange the request makes via an `httpx` response event hook.
Each of Phase 5b's 10 plausibility routes (`analysis/phase5b_plausibility.ROUTES`)
is written to its own fixture file: the recorded OSRM exchanges (so
`tests/test_golden.py` can replay them through a `MockTransport` with zero
network access) plus the resulting `/route` response, pinned as the golden
value.

Run whenever the underlying data (DB, OSRM extract) legitimately changes and
the golden values need updating - re-run in full, not edited by hand:

    python3 -m analysis.record_golden_fixtures
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from analysis.phase5b_plausibility import ROUTES
from tollroute import api

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "golden"
VEHICLE_CLASS = 1  # matches analysis/phase5b_plausibility.py's live-run script


def _slug(origin_name: str, dest_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", f"{origin_name}_{dest_name}".lower()).strip("_")


def record_route(client: TestClient, origin: tuple[float, float], destination: tuple[float, float]) -> dict:
    exchanges: list[dict] = []
    lock = threading.Lock()

    def _record(response: httpx.Response) -> None:
        response.read()
        with lock:
            exchanges.append({
                "url": str(response.request.url),
                "status_code": response.status_code,
                "body": response.json(),
            })

    real_osrm_client = api.app.state.osrm_client
    real_osrm_client.event_hooks = {"response": [_record]}
    try:
        resp = client.get("/route", params={
            "origin_lat": origin[0], "origin_lon": origin[1],
            "destination_lat": destination[0], "destination_lon": destination[1],
            "vehicle_class": VEHICLE_CLASS,
        })
    finally:
        real_osrm_client.event_hooks = {}
    resp.raise_for_status()
    return {"exchanges": exchanges, "expected": resp.json()}


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    with TestClient(api.app) as client:
        for origin_name, dest_name, origin, destination, note in ROUTES:
            recorded = record_route(client, origin, destination)
            fixture = {
                "origin_name": origin_name,
                "dest_name": dest_name,
                "note": note,
                "origin": list(origin),
                "destination": list(destination),
                "vehicle_class": VEHICLE_CLASS,
                **recorded,
            }
            slug = _slug(origin_name, dest_name)
            out_path = FIXTURE_DIR / f"{slug}.json"
            out_path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
            print(f"wrote {out_path} ({len(recorded['exchanges'])} OSRM exchanges)")


if __name__ == "__main__":
    main()
