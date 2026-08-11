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
def test_route_endpoint_fastest_option_matches_cli():
    # tollroute.cli.run uses the same duration-only routing.find_route as
    # response.shape_response's "fastest" label (Phase 4b), so the two must
    # agree exactly even though /route now returns a labelled option set
    # rather than a single flat route.
    cli_route = cli_run("dijon", "lyon", vehicle_class=1)

    with TestClient(api.app) as client:
        resp = client.get("/route", params={"origin": "dijon", "destination": "lyon", "vehicle_class": 1})

    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_class"] == 1
    options = data["options"]
    assert 1 <= len(options) <= 5

    fastest = [o for o in options if "fastest" in o["labels"]]
    assert len(fastest) == 1
    assert fastest[0]["toll_eur"] == pytest.approx(cli_route.toll_eur)
    assert fastest[0]["duration_s"] == pytest.approx(cli_route.duration_s)
    assert fastest[0]["distance_m"] == pytest.approx(cli_route.distance_m)
    assert fastest[0]["gates"] == _gate_chain(cli_route)

    assert any("cheapest" in o["labels"] for o in options)
    assert any("best_value" in o["labels"] for o in options)


@requires_osrm
def test_route_endpoint_accepts_vot_override():
    with TestClient(api.app) as client:
        resp = client.get(
            "/route",
            params={"origin": "dijon", "destination": "lyon", "vehicle_class": 1, "vot_eur_per_hour": 1.0},
        )
    assert resp.status_code == 200
    assert resp.json()["vot_eur_per_hour"] == pytest.approx(1.0)


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
