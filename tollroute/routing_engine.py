"""Valhalla routing engine: unified client replacing tollroute.osrm_client.

Two instances:
  full    (port 8002) — france.osm.pbf tiles, tolls allowed.
  notoll  (port 8003) — france-notoll.osm.pbf tiles, toll=yes ways stripped.

`toll_free=True` / `exclude_toll=True` routes at the notoll instance, which
gives a hard guarantee that tolled motorway is never used (equivalent to
OSRM's `exclude=toll`). Valhalla's `use_tolls` knob is not a guarantee, so
two separate tile sets are used instead.

Route calls use `format: "osrm"` so the response structure matches OSRM's
output and the callers that already parse it (response.py, api.py) survive
unchanged. Matrix calls use native Valhalla `/sources_to_targets`; distances
come back in km and are multiplied by 1000 to give metres (matching OSRM).
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

RETRY_DELAY_S = 0.5
TABLE_MAX_DIMENSION = 100
MAX_CONCURRENT_REQUESTS = 9

DEFAULT_FULL_URL = "http://localhost:8002"
DEFAULT_TOLLFREE_URL = "http://localhost:8003"


class RoutingUnavailableError(RuntimeError):
    """Valhalla did not answer after one retry at RETRY_DELAY_S.

    Callers (tollroute/api.py) turn this into {"osrm_unavailable": true}.
    """


@dataclass
class RoutingEngine:
    full_url: str = DEFAULT_FULL_URL
    tollfree_url: str = DEFAULT_TOLLFREE_URL
    timeout: float = 120.0
    _full: httpx.Client = field(init=False, repr=False)
    _notoll: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._full = httpx.Client(base_url=self.full_url, timeout=self.timeout)
        self._notoll = httpx.Client(base_url=self.tollfree_url, timeout=self.timeout)

    def close(self) -> None:
        self._full.close()
        self._notoll.close()

    def _client(self, toll_free: bool) -> httpx.Client:
        return self._notoll if toll_free else self._full

    def _post(self, client: httpx.Client, path: str, payload: dict) -> dict:
        """POST with retry-once-at-500 ms; raises RoutingUnavailableError."""
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = client.post(path, json=payload)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == 0:
                    logger.warning(
                        "Valhalla request failed, retrying in %.1fs: %s", RETRY_DELAY_S, exc
                    )
                    time.sleep(RETRY_DELAY_S)
        raise RoutingUnavailableError("Routing engine unreachable after retry") from last_exc

    def _post_concurrent(
        self, client: httpx.Client, path: str, payloads: list[dict]
    ) -> list[dict]:
        """Fire multiple POST requests concurrently on the same client."""
        if len(payloads) == 1:
            return [self._post(client, path, payloads[0])]
        with ThreadPoolExecutor(max_workers=min(len(payloads), MAX_CONCURRENT_REQUESTS)) as pool:
            return list(pool.map(lambda p: self._post(client, path, p), payloads))

    # ------------------------------------------------------------------
    # Connectivity

    def reachable(self, toll_free: bool = False) -> bool:
        """Quick connectivity probe (does not retry)."""
        try:
            self._client(toll_free).get("/status", timeout=2.0)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Snap

    def nearest(self, lat: float, lon: float, toll_free: bool = False) -> dict:
        """Snap (lat, lon) to the road network.

        Returns an OSRM-compatible /nearest response dict so callers
        (snap_report, snap_quality) need no changes.

        toll_free=True snaps against the notoll instance — used by
        toll_tagging_audit to detect toll-pocket gates.

        ponytail: verbose=True required to get edge.distance (metres) and
        edge.classification. Without verbose, those fields are absent.
        """
        payload = {"locations": [{"lat": lat, "lon": lon}], "costing": "auto", "verbose": True}
        data = self._post(self._client(toll_free), "/locate", payload)
        if not data or not isinstance(data, list) or not data[0].get("edges"):
            return {"code": "NoSegment", "waypoints": []}
        edge = data[0]["edges"][0]
        snapped_lat = edge.get("correlated_lat", lat)
        snapped_lon = edge.get("correlated_lon", lon)
        edge_info = edge.get("edge", {})
        cls = edge_info.get("classification", {})
        speeds = edge_info.get("speeds", {})
        return {
            "code": "Ok",
            "waypoints": [{
                "location": [snapped_lon, snapped_lat],
                "name": ((edge.get("edge_info") or {}).get("names") or [""])[0],
                "distance": edge.get("distance", 0.0),  # metres
                "road_class": cls.get("classification"),
                "use": cls.get("use", ""),
                "default_speed": speeds.get("default", 0),
            }],
        }

    # ------------------------------------------------------------------
    # Route

    def baseline_route(
        self, origin: tuple[float, float], destination: tuple[float, float]
    ) -> dict | None:
        """Tolls-allowed direct route.

        Returns {"duration": s, "distance": m} or None (genuine no-route).
        Raises RoutingUnavailableError when Valhalla is down — callers use
        this as an availability canary before the heavier table calls.
        """
        o_lat, o_lon = origin
        d_lat, d_lon = destination
        payload = {
            "locations": [{"lat": o_lat, "lon": o_lon}, {"lat": d_lat, "lon": d_lon}],
            "costing": "auto",
            "format": "osrm",
        }
        data = self._post(self._full, "/route", payload)
        if data.get("code") == "NoRoute":
            return None
        if data.get("code") != "Ok":
            raise RuntimeError(f"Valhalla /route failed for {origin}->{destination}: {data}")
        r = data["routes"][0]
        return {"duration": r["duration"], "distance": r["distance"]}

    def route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        toll_free: bool = False,
        geometry: bool = False,
    ) -> dict | None:
        """General route call; returns OSRM-format dict or None (no route).

        Used by snap_report, access_anchors, and the geometry path. When
        geometry=True, sets shape_format=geojson so coordinate lists come
        back as [[lon, lat], ...] matching OSRM's geometries=geojson output.
        """
        o_lat, o_lon = origin
        d_lat, d_lon = destination
        payload: dict = {
            "locations": [{"lat": o_lat, "lon": o_lon}, {"lat": d_lat, "lon": d_lon}],
            "costing": "auto",
            "format": "osrm",
        }
        if geometry:
            payload["shape_format"] = "geojson"
        data = self._post(self._client(toll_free), "/route", payload)
        if data.get("code") == "NoRoute":
            return None
        if data.get("code") != "Ok":
            raise RuntimeError(f"Valhalla /route failed: {data}")
        return data

    def route_geometry(
        self,
        waypoints: list[tuple[float, float]],
        toll_leg_indices: set[int] | None = None,
    ) -> dict:
        """Full-geometry /route for all waypoints, toll/free segment annotations.

        Routes each leg independently to avoid the carriageway U-turn problem:
        a gate snap on a directional motorway carriageway forces Valhalla to
        satisfy the via-point in the wrong direction, then U-turn (often 50+ km)
        at the next interchange before continuing. Per-leg routing eliminates
        this because each two-point call lets Valhalla choose either carriageway
        and naturally picks the shorter path. Access legs use the toll-free
        instance; toll legs use the full instance. Returns:
          geometry      — GeoJSON LineString of the full route
          roads         — ordered list of road names seen
          segments      — list of {is_toll, is_access, coords} dicts
          access_leg_toll_roads — toll road names found in access legs (unpriced)
        """
        n = len(waypoints)
        n_legs = n - 1
        priced_leg_indices = set(toll_leg_indices or [])
        access_leg_indices = {0, n_legs - 1} if n_legs > 1 else {0}

        all_roads: list[str] = []
        segments: list[dict] = []
        unpriced_toll_roads: list[str] = []
        all_coords: list = []

        for leg_idx in range(n_legs):
            src_lat, src_lon = waypoints[leg_idx]
            dst_lat, dst_lon = waypoints[leg_idx + 1]
            is_access_leg = leg_idx in access_leg_indices
            client = self._notoll if is_access_leg else self._full
            payload = {
                "locations": [
                    {"lat": src_lat, "lon": src_lon},
                    {"lat": dst_lat, "lon": dst_lon},
                ],
                "costing": "auto",
                "format": "osrm",
                "shape_format": "geojson",
            }
            data = self._post(client, "/route", payload)
            if data.get("code") != "Ok":
                raise RuntimeError(f"Valhalla /route geometry failed on leg {leg_idx}: {data}")
            leg = data["routes"][0]["legs"][0]

            for step in leg.get("steps", []):
                ref = (step.get("ref") or step.get("name") or "").strip()
                if ref and (not all_roads or all_roads[-1] != ref):
                    all_roads.append(ref)
                step_geom = step.get("geometry", {})
                step_coords = (
                    step_geom.get("coordinates", []) if isinstance(step_geom, dict) else []
                )
                if not step_coords:
                    continue
                is_toll = any(
                    "toll" in i.get("classes", []) for i in step.get("intersections", [])
                )
                if is_toll and is_access_leg and ref and ref not in unpriced_toll_roads:
                    unpriced_toll_roads.append(ref)
                if (
                    segments
                    and segments[-1]["is_toll"] == is_toll
                    and segments[-1]["is_access"] == is_access_leg
                ):
                    segments[-1]["coords"].extend(step_coords[1:])
                else:
                    segments.append(
                        {"is_toll": is_toll, "is_access": is_access_leg, "coords": list(step_coords)}
                    )
                all_coords.extend(step_coords if not all_coords else step_coords[1:])

        return {
            "geometry": {"type": "LineString", "coordinates": all_coords},
            "roads": all_roads,
            "segments": segments,
            "access_leg_toll_roads": unpriced_toll_roads,
        }

    # ------------------------------------------------------------------
    # Matrix — per-request (access edges)

    def one_to_many_table(
        self,
        origin: tuple[float, float],
        many: list[tuple[float, float]],
        exclude_toll: bool = False,
    ) -> list[tuple[float, float] | None]:
        """Duration (s) / distance (m) from origin to each point in many.

        Tiled into <=TABLE_MAX_DIMENSION-target blocks fired concurrently.
        Replaces osrm_client.one_to_many_table.
        """
        if not many:
            return []
        client = self._client(exclude_toll)
        o_lat, o_lon = origin
        starts = list(range(0, len(many), TABLE_MAX_DIMENSION))
        out: list[tuple[float, float] | None] = [None] * len(many)

        payloads = [
            {
                "sources": [{"lat": o_lat, "lon": o_lon}],
                "targets": [{"lat": lat, "lon": lon} for lat, lon in many[s : s + TABLE_MAX_DIMENSION]],
                "costing": "auto",
                "units": "km",
            }
            for s in starts
        ]
        responses = self._post_concurrent(client, "/sources_to_targets", payloads)

        for start, data in zip(starts, responses):
            block_size = min(TABLE_MAX_DIMENSION, len(many) - start)
            for bi in range(block_size):
                cell = data["sources_to_targets"][0][bi]
                if cell and cell.get("time") is not None and cell.get("distance") is not None:
                    out[start + bi] = (cell["time"], cell["distance"] * 1000.0)
        return out

    def many_to_one_table(
        self,
        many: list[tuple[float, float]],
        destination: tuple[float, float],
        exclude_toll: bool = False,
    ) -> list[tuple[float, float] | None]:
        """Duration (s) / distance (m) from each point in many to destination.

        Tiled the same way as one_to_many_table.
        Replaces osrm_client.many_to_one_table.
        """
        if not many:
            return []
        client = self._client(exclude_toll)
        d_lat, d_lon = destination
        starts = list(range(0, len(many), TABLE_MAX_DIMENSION))
        out: list[tuple[float, float] | None] = [None] * len(many)

        payloads = [
            {
                "sources": [{"lat": lat, "lon": lon} for lat, lon in many[s : s + TABLE_MAX_DIMENSION]],
                "targets": [{"lat": d_lat, "lon": d_lon}],
                "costing": "auto",
                "units": "km",
            }
            for s in starts
        ]
        responses = self._post_concurrent(client, "/sources_to_targets", payloads)

        for start, data in zip(starts, responses):
            block_size = min(TABLE_MAX_DIMENSION, len(many) - start)
            for bi in range(block_size):
                cell = data["sources_to_targets"][bi][0]
                if cell and cell.get("time") is not None and cell.get("distance") is not None:
                    out[start + bi] = (cell["time"], cell["distance"] * 1000.0)
        return out

    # ------------------------------------------------------------------
    # Matrix — build-time (replaces graph.osrm_table / osrm_asymmetric_table)

    def table(
        self,
        coords: list[tuple[float, float]],
        toll_free: bool = False,
    ) -> tuple[list[list[float | None]], list[list[float | None]]]:
        """Full N×N duration+distance matrices, tiled into <=TABLE_MAX_DIMENSION blocks.

        Replaces tollroute.graph.osrm_table. Used by matrices.py at build time.
        Returns (durations_s, distances_m).
        """
        n = len(coords)
        client = self._client(toll_free)

        durations: list[list[float | None]] = [[None] * n for _ in range(n)]
        distances: list[list[float | None]] = [[None] * n for _ in range(n)]

        src_blocks = [range(s, min(s + TABLE_MAX_DIMENSION, n)) for s in range(0, n, TABLE_MAX_DIMENSION)]
        dst_blocks = [range(s, min(s + TABLE_MAX_DIMENSION, n)) for s in range(0, n, TABLE_MAX_DIMENSION)]

        for sb in src_blocks:
            for db in dst_blocks:
                payload = {
                    "sources": [{"lat": coords[i][0], "lon": coords[i][1]} for i in sb],
                    "targets": [{"lat": coords[j][0], "lon": coords[j][1]} for j in db],
                    "costing": "auto",
                    "units": "km",
                }
                data = self._post(client, "/sources_to_targets", payload)
                for bi, i in enumerate(sb):
                    for bj, j in enumerate(db):
                        cell = data["sources_to_targets"][bi][bj]
                        if cell and cell.get("time") is not None and cell.get("distance") is not None:
                            durations[i][j] = cell["time"]
                            distances[i][j] = cell["distance"] * 1000.0

        return durations, distances

    def asymmetric_table(
        self,
        source_coords: list[tuple[float, float]],
        dest_coords: list[tuple[float, float]],
        toll_free: bool = False,
    ) -> tuple[list[list[float | None]], list[list[float | None]]]:
        """M×N duration+distance matrices with distinct source and dest coords.

        Replaces tollroute.graph.osrm_asymmetric_table. Used by matrices.py.
        Returns (durations_s, distances_m).
        """
        m = len(source_coords)
        n = len(dest_coords)
        client = self._client(toll_free)

        durations: list[list[float | None]] = [[None] * n for _ in range(m)]
        distances: list[list[float | None]] = [[None] * n for _ in range(m)]

        src_blocks = [range(s, min(s + TABLE_MAX_DIMENSION, m)) for s in range(0, m, TABLE_MAX_DIMENSION)]
        dst_blocks = [range(s, min(s + TABLE_MAX_DIMENSION, n)) for s in range(0, n, TABLE_MAX_DIMENSION)]

        for sb in src_blocks:
            for db in dst_blocks:
                payload = {
                    "sources": [{"lat": source_coords[i][0], "lon": source_coords[i][1]} for i in sb],
                    "targets": [{"lat": dest_coords[j][0], "lon": dest_coords[j][1]} for j in db],
                    "costing": "auto",
                    "units": "km",
                }
                data = self._post(client, "/sources_to_targets", payload)
                for bi, i in enumerate(sb):
                    for bj, j in enumerate(db):
                        cell = data["sources_to_targets"][bi][bj]
                        if cell and cell.get("time") is not None and cell.get("distance") is not None:
                            durations[i][j] = cell["time"]
                            distances[i][j] = cell["distance"] * 1000.0

        return durations, distances
