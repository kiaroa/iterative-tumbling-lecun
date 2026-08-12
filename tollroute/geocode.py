"""Free-text address geocoding wrapper (Phase 6b).

Resolves a free-text address to (lat, lon) via the French government's Base
Adresse Nationale (BAN) search API (api-adresse.data.gouv.fr) - free,
keyless and scoped to France, which matches this service's own scope, so no
extra API key configuration is needed. Feeds the (unchanged) routing core
exactly as if the caller had supplied lat/lon directly: `tollroute/api.py`
calls `geocode` once per free-text `origin_address`/`destination_address`
before anything else runs.
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

DEFAULT_GEOCODE_BASE_URL = "https://api-adresse.data.gouv.fr"
RETRY_DELAY_S = 0.5


class GeocodeError(Exception):
    """Raised when a free-text address cannot be resolved to coordinates -
    either the geocoding service is unreachable after one retry, or it
    answered but found no matching address."""


def geocode(client: httpx.Client, query: str) -> tuple[float, float]:
    """Resolve free text to (lat, lon), retrying once on transport failure
    (the same one-retry-at-500ms policy `tollroute.osrm_client` uses for the
    other external call on the `/route` path). Returns the BAN API's
    top-scored match; raises `GeocodeError` if the service stays
    unreachable after the retry or returns no candidates for `query`.
    """
    last_exc: Exception | None = None
    data: dict | None = None
    for attempt in range(2):
        try:
            resp = client.get("/search/", params={"q": query, "limit": 1})
            resp.raise_for_status()
            data = resp.json()
            break
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning(
                    "geocoding request failed, retrying once in %.1fs: %s (%s)",
                    RETRY_DELAY_S, query, exc,
                )
                time.sleep(RETRY_DELAY_S)
    if data is None:
        raise GeocodeError(f"geocoding service unreachable for {query!r}") from last_exc

    features = data.get("features", [])
    if not features:
        raise GeocodeError(f"no address match for {query!r}")

    lon, lat = features[0]["geometry"]["coordinates"]
    return (lat, lon)
