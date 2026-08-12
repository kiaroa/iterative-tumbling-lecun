import dataclasses
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from tollroute import api
from tollroute import geocode as geocode_mod
from tollroute import graph as graph_mod
from tollroute import logging as logging_mod
from tollroute import osrm_client as osrm_client_mod
from tollroute.cli import GAZETTEER
from tollroute.cli import run as cli_run
from tollroute.etl import snap_report

DIJON = GAZETTEER["dijon"]
LYON = GAZETTEER["lyon"]
LILLE = GAZETTEER["lille"]
MARSEILLE = GAZETTEER["marseille"]


def _params(origin, destination, **extra):
    return {
        "origin_lat": origin[0], "origin_lon": origin[1],
        "destination_lat": destination[0], "destination_lon": destination[1],
        **extra,
    }


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


def test_graph_copy_preserves_every_graph_dataclass_field():
    """Regression guard: `_graph_copy` reconstructs a `Graph` field-by-field (it can't
    just `copy.copy` - `add_access_edges` mutates the copy in place, and a shallow
    `copy.copy` would still share the *same* `edges`/`nodes` lists as the startup
    graph). Every time `graph_mod.Graph` gains a new field, `_graph_copy` must be
    updated to carry it over, or the copy silently reverts to that field's default -
    exactly what happened to `freeflow_selfloop_gate_ids` here (Phase
    5b-follow-up-2-continued: it defaulted to an empty set on every per-request copy,
    so the Millau toll-skip fix in `add_access_edges` passed its own direct unit test
    yet never actually fired through the real API path, only surfacing when the golden
    fixtures were re-recorded and still showed `toll_eur: 0.0`). Iterates
    `dataclasses.fields` generically so this doesn't need hand-updating for the *next*
    new field either.
    """
    g = graph_mod.Graph(
        gate_coords={1: (1.0, 2.0)},
        access_anchors_entry={1: (1.0, 2.0, 3.0, 4.0)},
        access_anchors_exit={1: (1.0, 2.0, 3.0, 4.0)},
        freeflow_selfloop_gate_ids={1},
    )
    g.add_node(graph_mod.Node(1, graph_mod.NodeRole.IN))
    g.add_edge(
        graph_mod.Node(1, graph_mod.NodeRole.IN),
        graph_mod.Node(1, graph_mod.NodeRole.IN),
        graph_mod.EdgeType.DWELL,
        1.0,
        1.0,
    )

    copied = api._graph_copy(g)

    for f in dataclasses.fields(graph_mod.Graph):
        assert getattr(copied, f.name) == getattr(g, f.name), f"_graph_copy dropped field {f.name!r}"


@requires_osrm
def test_route_endpoint_fastest_option_matches_cli():
    # tollroute.cli.run uses the same duration-only routing.find_route as
    # response.shape_response's "fastest" label (Phase 4b), so the two must
    # agree exactly even though /route now returns a labelled option set
    # rather than a single flat route.
    cli_route = cli_run("dijon", "lyon", vehicle_class=1)

    with TestClient(api.app) as client:
        resp = client.get("/route", params=_params(DIJON, LYON, vehicle_class=1))

    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_class"] == 1
    assert data["baseline"] is not None
    assert data["baseline"]["duration_s"] > 0
    options = data["options"]
    assert 1 <= len(options) <= 5

    fastest = [o for o in options if "fastest" in o["labels"]]
    assert len(fastest) == 1
    assert fastest[0]["toll_eur"] == pytest.approx(cli_route.toll_eur)
    assert fastest[0]["duration_s"] == pytest.approx(cli_route.duration_s)
    assert fastest[0]["distance_m"] == pytest.approx(cli_route.distance_m)
    assert fastest[0]["gates"] == _gate_chain(cli_route)
    assert "route_id" in fastest[0]

    assert any("cheapest" in o["labels"] for o in options)
    assert any("best_value" in o["labels"] for o in options)


@requires_osrm
def test_route_endpoint_accepts_vot_override():
    with TestClient(api.app) as client:
        resp = client.get("/route", params=_params(DIJON, LYON, vehicle_class=1, vot_eur_per_hour=1.0))
    assert resp.status_code == 200
    assert resp.json()["vot_eur_per_hour"] == pytest.approx(1.0)


@requires_osrm
def test_route_endpoint_serves_national_multi_operator_pair():
    # Phase 4b's named exit criterion (Lille -> Marseille) is only servable
    # once the API is wired to the national (all-operator) DB with Phase 2c's
    # transfer edges - this is the Phase 4b-follow-up item's own regression
    # guard: the fastest route's gate chain must cross more than one operator
    # to prove cross-operator connectivity is actually exercised, not just
    # present.
    with TestClient(api.app) as client:
        resp = client.get("/route", params=_params(LILLE, MARSEILLE, vehicle_class=1))
    assert resp.status_code == 200
    data = resp.json()
    fastest = next(o for o in data["options"] if "fastest" in o["labels"])
    assert fastest["toll_eur"] > 0
    assert len(fastest["gates"]) >= 2

    import sqlite3

    from tollroute.etl.build_national import DEFAULT_NATIONAL_DB_PATH

    conn = sqlite3.connect(DEFAULT_NATIONAL_DB_PATH)
    try:
        operators = {
            conn.execute("SELECT operators FROM gates WHERE gare_id = ?", (gid,)).fetchone()[0]
            for gid in fastest["gates"]
        }
    finally:
        conn.close()
    assert len(operators) > 1, f"expected a cross-operator gate chain, got {operators}"


@requires_osrm
def test_route_endpoint_invalid_vehicle_class_returns_400():
    with TestClient(api.app) as client:
        resp = client.get("/route", params=_params(DIJON, LYON, vehicle_class=9))
    assert resp.status_code == 400


@requires_osrm
def test_route_endpoint_returns_osrm_unavailable_when_osrm_mocked_down(monkeypatch):
    # Point the app's OSRM client at a port nothing listens on so every OSRM
    # call fails; the retry-once policy (osrm_client.RETRY_DELAY_S) still
    # runs, then the endpoint must degrade to {"osrm_unavailable": true}
    # rather than a 500 (spec: Phase 4c OSRM-failure exit criterion).
    import httpx

    monkeypatch.setattr(osrm_client_mod, "RETRY_DELAY_S", 0.01)
    with TestClient(api.app) as client:
        real_client = api.app.state.osrm_client
        api.app.state.osrm_client = httpx.Client(base_url="http://127.0.0.1:1", timeout=2.0)
        try:
            resp = client.get("/route", params=_params(DIJON, LYON))
        finally:
            api.app.state.osrm_client = real_client
    assert resp.status_code == 200
    assert resp.json() == {"osrm_unavailable": True}


@requires_osrm
def test_geometry_endpoint_returns_geojson_for_selected_option():
    with TestClient(api.app) as client:
        resp = client.get("/route", params=_params(DIJON, LYON, vehicle_class=1))
        assert resp.status_code == 200
        route_id = resp.json()["options"][0]["route_id"]

        geo_resp = client.get(f"/geometry/{route_id}")
    assert geo_resp.status_code == 200
    geometry = geo_resp.json()
    assert geometry["type"] == "LineString"
    assert len(geometry["coordinates"]) >= 2


@requires_osrm
def test_geometry_endpoint_unknown_route_id_returns_404():
    with TestClient(api.app) as client:
        resp = client.get("/geometry/does-not-exist")
    assert resp.status_code == 404


@requires_osrm
def test_route_endpoint_logs_full_gate_chain(caplog):
    # Phase 6a exit criterion: "a single request log contains the full gate
    # chain" - checked here for every option, not just the labelled winner,
    # since "why this route" debugging usually means "why not that one".
    with caplog.at_level(logging.INFO, logger=logging_mod.ROUTE_LOGGER_NAME):
        with TestClient(api.app) as client:
            resp = client.get("/route", params=_params(DIJON, LYON, vehicle_class=1))
    assert resp.status_code == 200
    data = resp.json()

    route_records = [r for r in caplog.records if r.name == logging_mod.ROUTE_LOGGER_NAME]
    assert len(route_records) == 1
    fields = route_records[0].fields
    assert fields["vehicle_class"] == 1

    logged_chains = {tuple(o["gates"]) for o in fields["options"]}
    response_chains = {tuple(o["gates"]) for o in data["options"]}
    assert logged_chains == response_chains
    assert len(fields["options"]) == len(data["options"])


@requires_osrm
def test_health_endpoint_returns_200_when_osrm_up():
    with TestClient(api.app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"osrm_reachable": True, "matrix_loaded": True, "gate_count": body["gate_count"]}
    assert body["gate_count"] > 0


@requires_osrm
def test_health_endpoint_returns_503_when_osrm_mocked_down():
    with TestClient(api.app) as client:
        real_client = api.app.state.osrm_client
        api.app.state.osrm_client = httpx.Client(base_url="http://127.0.0.1:1", timeout=2.0)
        try:
            resp = client.get("/health")
        finally:
            api.app.state.osrm_client = real_client
    assert resp.status_code == 503
    body = resp.json()
    assert body["osrm_reachable"] is False
    assert body["matrix_loaded"] is True


def _mock_geocode_client(coords_by_query: dict[str, tuple[float, float]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        if query not in coords_by_query:
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        lat, lon = coords_by_query[query]
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"geometry": {"coordinates": [lon, lat]}, "properties": {"label": query}}],
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ban.test")


@requires_osrm
def test_route_endpoint_resolves_free_text_address_same_as_coordinates():
    # Phase 6b exit criterion: a city-name query must return the same result
    # as the corresponding coordinates. The mocked BAN client returns
    # DIJON's exact coordinates for "Dijon" so both requests hit the same
    # cached_shape entry and must therefore agree exactly, not just approximately.
    with TestClient(api.app) as client:
        real_geocode_client = api.app.state.geocode_client
        api.app.state.geocode_client = _mock_geocode_client({"Dijon": DIJON})
        try:
            address_resp = client.get(
                "/route", params={"origin_address": "Dijon", "destination_lat": LYON[0],
                                   "destination_lon": LYON[1], "vehicle_class": 1}
            )
        finally:
            api.app.state.geocode_client = real_geocode_client
        coord_resp = client.get("/route", params=_params(DIJON, LYON, vehicle_class=1))

    assert address_resp.status_code == 200
    assert coord_resp.status_code == 200
    address_data = address_resp.json()
    coord_data = coord_resp.json()
    assert address_data["origin"] == coord_data["origin"] == {"lat": DIJON[0], "lon": DIJON[1]}
    assert [o["toll_eur"] for o in address_data["options"]] == [o["toll_eur"] for o in coord_data["options"]]
    assert [o["gates"] for o in address_data["options"]] == [o["gates"] for o in coord_data["options"]]


@requires_osrm
def test_route_endpoint_address_response_has_match_tier_and_agreement_on_every_gate():
    # Phase 6b's second exit condition: match_tier/match_agreement present
    # on every response - unchanged from the coordinate path since the
    # routing core itself never changes, only the input resolution step.
    with TestClient(api.app) as client:
        real_geocode_client = api.app.state.geocode_client
        api.app.state.geocode_client = _mock_geocode_client({"Dijon": DIJON, "Lyon": LYON})
        try:
            resp = client.get(
                "/route", params={"origin_address": "Dijon", "destination_address": "Lyon", "vehicle_class": 1}
            )
        finally:
            api.app.state.geocode_client = real_geocode_client

    assert resp.status_code == 200
    data = resp.json()
    assert data["options"], "expected at least one option"
    for option in data["options"]:
        assert option["gate_detail"], "expected at least one gate on a real route"
        for gate in option["gate_detail"]:
            assert "match_tier" in gate
            assert "match_agreement" in gate


@requires_osrm
@pytest.mark.parametrize(
    "params",
    [
        {"origin_lat": DIJON[0], "origin_lon": DIJON[1], "origin_address": "Dijon"},  # both forms
        {"origin_lat": DIJON[0]},  # lat without lon
        {"origin_lon": DIJON[1]},  # lon without lat
        {},  # neither form
    ],
)
def test_route_endpoint_rejects_ambiguous_or_missing_origin(params):
    with TestClient(api.app) as client:
        resp = client.get(
            "/route",
            params={**params, "destination_lat": LYON[0], "destination_lon": LYON[1], "vehicle_class": 1},
        )
    assert resp.status_code == 400


@requires_osrm
def test_route_endpoint_geocode_unreachable_returns_422(monkeypatch):
    monkeypatch.setattr(geocode_mod, "RETRY_DELAY_S", 0.01)
    with TestClient(api.app) as client:
        real_geocode_client = api.app.state.geocode_client
        api.app.state.geocode_client = httpx.Client(base_url="http://127.0.0.1:1", timeout=2.0)
        try:
            resp = client.get(
                "/route",
                params={"origin_address": "Dijon", "destination_lat": LYON[0], "destination_lon": LYON[1]},
            )
        finally:
            api.app.state.geocode_client = real_geocode_client
    assert resp.status_code == 422
