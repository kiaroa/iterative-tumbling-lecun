import pytest
from fastapi.testclient import TestClient

from tollroute import api
from tollroute.cli import run as cli_run
from tollroute.etl import snap_report


def _gate_chain(route) -> list[int]:
    chain: list[int] = []
    for node in route.nodes:
        if node.gare_id < 0:
            continue
        if not chain or chain[-1] != node.gare_id:
            chain.append(node.gare_id)
    return chain


def _osrm_reachable() -> bool:
    try:
        import httpx

        httpx.get(f"{snap_report.DEFAULT_OSRM_BASE_URL}/nearest/v1/car/5.0,47.0", timeout=2.0)
        return True
    except Exception:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live OSRM instance not reachable on DEFAULT_OSRM_BASE_URL"
)


@requires_osrm
def test_route_endpoint_returns_same_option_set_as_cli():
    cli_route = cli_run("dijon", "lyon", vehicle_class=1)

    with TestClient(api.app) as client:
        resp = client.get("/route", params={"origin": "dijon", "destination": "lyon", "vehicle_class": 1})

    assert resp.status_code == 200
    data = resp.json()
    assert data["toll_eur"] == pytest.approx(cli_route.toll_eur)
    assert data["duration_s"] == pytest.approx(cli_route.duration_s)
    assert data["distance_m"] == pytest.approx(cli_route.distance_m)
    assert data["gates"] == _gate_chain(cli_route)


@requires_osrm
def test_route_endpoint_unknown_city_returns_400():
    with TestClient(api.app) as client:
        resp = client.get("/route", params={"origin": "nowhere", "destination": "lyon"})
    assert resp.status_code == 400


@requires_osrm
def test_route_endpoint_invalid_vehicle_class_returns_400():
    with TestClient(api.app) as client:
        resp = client.get("/route", params={"origin": "dijon", "destination": "lyon", "vehicle_class": 9})
    assert resp.status_code == 400
