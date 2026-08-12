import httpx
import pytest

from tollroute import geocode


def _ban_response(lat: float, lon: float, label: str = "Paris") -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"label": label, "score": 0.95},
            }
        ],
    }


def _no_match_response() -> dict:
    return {"type": "FeatureCollection", "features": []}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ban.test")


def test_geocode_returns_top_scored_lat_lon():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/"
        assert request.url.params["q"] == "Dijon"
        return httpx.Response(200, json=_ban_response(47.3220, 5.0415, "Dijon"))

    result = geocode.geocode(_client(handler), "Dijon")
    assert result == (47.3220, 5.0415)


def test_geocode_raises_on_no_match():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_no_match_response())

    with pytest.raises(geocode.GeocodeError, match="no address match"):
        geocode.geocode(_client(handler), "not a real place at all")


def test_geocode_retries_once_then_succeeds(monkeypatch):
    monkeypatch.setattr(geocode, "RETRY_DELAY_S", 0.0)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=_ban_response(45.7640, 4.8357, "Lyon"))

    result = geocode.geocode(_client(handler), "Lyon")
    assert result == (45.7640, 4.8357)
    assert len(calls) == 2


def test_geocode_raises_after_retry_exhausted(monkeypatch):
    monkeypatch.setattr(geocode, "RETRY_DELAY_S", 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(geocode.GeocodeError, match="unreachable"):
        geocode.geocode(_client(handler), "Lyon")
