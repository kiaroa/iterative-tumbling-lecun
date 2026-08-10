"""Directed overlay graph for toll-minimising routing (Phase 1c).

Implements the spec's "Core architectural decision" virtual-edge model
(iterative-tumbling-lecun.md): each `fares` row becomes one toll edge priced
from `od_pairs`, with distance/time taken from OSRM rather than the CSV, so
toll cost stays additive and Dijkstra stays valid over closed tolling.

Node-split: every gate becomes four nodes, not the naive two ("in"/"out").
The extra split is what makes the spec's "same-operator toll-edge chaining
is forbidden via the dwell edge" rule structurally true rather than a
runtime path check:

    IN        -- dwell -->      OUT        -- toll edge -->  IN_TOLL (another gate)
    IN_TOLL   -- dwell -->      OUT_TOLL

- IN is the landing node for toll-free and access edges (an ordinary
  approach to a gate). Its dwell edge leads to OUT, which *may* start a
  toll edge, a toll-free edge, or a destination access edge.
- IN_TOLL is the landing node for toll edges only (arriving at a gate having
  just driven a priced tolled segment). Its dwell edge leads to OUT_TOLL,
  which may start a toll-free edge or a destination access edge, but never
  another toll edge.

Because a toll edge can only ever originate at an OUT node, and OUT is only
ever reached via a dwell that followed a toll-free/access arrival (never a
toll arrival), the pattern "toll edge -> dwell -> toll edge" is
unrepresentable in the graph: it would require a toll edge sourced at
OUT_TOLL, and no such edge is ever added. A genuine toll-free detour between
two toll edges (a real "fractionnement") remains reachable via
OUT_TOLL -> [toll-free edge] -> IN -> [dwell] -> OUT -> [toll edge], which is
exactly the case the spec allows (flagged `same_operator_split` in Phase 4b,
not this module's concern).

Vacuous while Phase 1 is APRR-only (every toll edge shares one operator), but
implemented now so Phase 2c's multi-operator graph inherits it unchanged.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

DWELL_DURATION_S = 180.0
DWELL_DISTANCE_M = 500.0

# Fallback motorway speed used only when OSRM has no route between two
# snapped points in the current (regional) extract, e.g. a gate outside the
# bfc-ara coverage area — see Phase 1b's snapping report. The toll edge is
# still added (never silently dropped) rather than losing the fare entirely.
FALLBACK_SPEED_KMH = 110.0


class EdgeType(str, Enum):
    TOLL = "toll"
    TOLL_FREE = "toll_free"
    DWELL = "dwell"
    ACCESS = "access"


class NodeRole(str, Enum):
    IN = "in"
    OUT = "out"
    IN_TOLL = "in_toll"
    OUT_TOLL = "out_toll"


@dataclass(frozen=True)
class Node:
    gare_id: int
    role: NodeRole


@dataclass(frozen=True)
class Edge:
    from_node: Node
    to_node: Node
    edge_type: EdgeType
    duration_s: float
    distance_m: float
    operator: str | None = None
    toll_eur: dict[int, float] | None = None  # vehicle class -> price; TOLL edges only


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    node_index: dict[Node, int] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    # gare_id -> (lat, lon), snap coordinates used to build this graph; kept
    # alongside it so add_access_edges can OSRM-route to/from any gate
    # without a second DB round-trip.
    gate_coords: dict[int, tuple[float, float]] = field(default_factory=dict)

    def add_node(self, node: Node) -> int:
        if node not in self.node_index:
            self.node_index[node] = len(self.nodes)
            self.nodes.append(node)
        return self.node_index[node]


def _gate_rows(conn: sqlite3.Connection) -> list[tuple[int, float, float]]:
    return conn.execute(
        "SELECT gare_id, snap_lat, snap_lon FROM gates "
        "WHERE snap_lat IS NOT NULL AND snap_lon IS NOT NULL "
        "ORDER BY gare_id"
    ).fetchall()


# osrm-routed's default --max-table-size caps max(len(sources), len(destinations))
# at 100 per request (confirmed empirically against the running bfc-ara instance:
# 100 passes, 101 returns {"code":"TooBig"}), independent of the full location
# list's length. With ~209 APRR gates the full N x N matrix needs tiling into
# <=100 x <=100 blocks and stitching, rather than one request.
OSRM_TABLE_MAX_DIMENSION = 100


def _osrm_table(
    client: httpx.Client, coords: list[tuple[float, float]], exclude_toll: bool
) -> tuple[list[list[float | None]], list[list[float | None]]]:
    """Full N x N duration+distance matrices, tiled into <=100x100 OSRM /table calls.

    `coords` is a list of (lat, lon); OSRM's own wire format is lon,lat.
    """
    n = len(coords)
    locations = ";".join(f"{lon},{lat}" for lat, lon in coords)
    params = "annotations=duration,distance"
    if exclude_toll:
        params += "&exclude=toll"

    durations: list[list[float | None]] = [[None] * n for _ in range(n)]
    distances: list[list[float | None]] = [[None] * n for _ in range(n)]

    blocks = [
        range(start, min(start + OSRM_TABLE_MAX_DIMENSION, n))
        for start in range(0, n, OSRM_TABLE_MAX_DIMENSION)
    ]
    for src_block in blocks:
        sources = ";".join(str(i) for i in src_block)
        for dst_block in blocks:
            destinations = ";".join(str(i) for i in dst_block)
            resp = client.get(
                f"/table/v1/car/{locations}?{params}&sources={sources}&destinations={destinations}"
            )
            resp.raise_for_status()
            data = resp.json()
            if data["code"] != "Ok":
                raise RuntimeError(f"OSRM /table failed: {data}")
            for bi, i in enumerate(src_block):
                for bj, j in enumerate(dst_block):
                    durations[i][j] = data["durations"][bi][bj]
                    distances[i][j] = data["distances"][bi][bj]

    return durations, distances


def build_graph(conn: sqlite3.Connection, osrm_client: httpx.Client) -> Graph:
    gate_rows = _gate_rows(conn)
    gare_ids = [r[0] for r in gate_rows]
    coords = [(r[1], r[2]) for r in gate_rows]
    n = len(gare_ids)
    if n == 0:
        raise RuntimeError(
            "no APRR gates have snapped coordinates - run tollroute.etl.snap_report first"
        )
    gate_position = {gid: i for i, gid in enumerate(gare_ids)}

    logger.info("building overlay graph for %d snapped APRR gates", n)

    tolled_durations, tolled_distances = _osrm_table(osrm_client, coords, exclude_toll=False)
    tollfree_durations, tollfree_distances = _osrm_table(osrm_client, coords, exclude_toll=True)

    graph = Graph(gate_coords={gid: (lat, lon) for gid, (lat, lon) in zip(gare_ids, coords)})

    for gid in gare_ids:
        in_node = Node(gid, NodeRole.IN)
        out_node = Node(gid, NodeRole.OUT)
        in_toll_node = Node(gid, NodeRole.IN_TOLL)
        out_toll_node = Node(gid, NodeRole.OUT_TOLL)
        for node in (in_node, out_node, in_toll_node, out_toll_node):
            graph.add_node(node)
        graph.edges.append(
            Edge(in_node, out_node, EdgeType.DWELL, DWELL_DURATION_S, DWELL_DISTANCE_M)
        )
        graph.edges.append(
            Edge(in_toll_node, out_toll_node, EdgeType.DWELL, DWELL_DURATION_S, DWELL_DISTANCE_M)
        )
    dwell_edge_count = 2 * n

    fare_rows = conn.execute(
        "SELECT from_gare_id, to_gare_id, operator, class1, class2, class3, class4, class5, "
        "distance_km FROM fares WHERE from_gare_id IS NOT NULL AND to_gare_id IS NOT NULL"
    ).fetchall()

    toll_edge_count = 0
    no_coords_count = 0
    no_osrm_route_count = 0
    for from_id, to_id, operator, c1, c2, c3, c4, c5, distance_km in fare_rows:
        if from_id not in gate_position or to_id not in gate_position:
            # References a gate with no lat/lon (e.g. CHARMONT) - can't be
            # snapped or matrixed, so there's no OSRM-derived distance/time
            # to attach. Quarantining coordinate-less gates is Phase 2c's
            # job; here the edge is just logged as skipped, not dropped
            # silently.
            no_coords_count += 1
            continue

        i, j = gate_position[from_id], gate_position[to_id]
        duration_s = tolled_durations[i][j]
        distance_m = tolled_distances[i][j]
        if duration_s is None or distance_m is None:
            no_osrm_route_count += 1
            distance_m = (distance_km or 0.0) * 1000.0
            duration_s = distance_m / (FALLBACK_SPEED_KMH * 1000.0 / 3600.0)

        graph.edges.append(
            Edge(
                Node(from_id, NodeRole.OUT),
                Node(to_id, NodeRole.IN_TOLL),
                EdgeType.TOLL,
                duration_s,
                distance_m,
                operator=operator,
                toll_eur={1: c1, 2: c2, 3: c3, 4: c4, 5: c5},
            )
        )
        toll_edge_count += 1

    if no_coords_count:
        logger.warning(
            "%d fare rows reference a gate with no coordinates; skipped as toll edges",
            no_coords_count,
        )
    if no_osrm_route_count:
        logger.warning(
            "%d toll edges had no OSRM route in this extract; used distance_km + "
            "%.0f km/h fallback instead",
            no_osrm_route_count,
            FALLBACK_SPEED_KMH,
        )

    tollfree_edge_count = 0
    no_tollfree_route_count = 0
    for i, from_id in enumerate(gare_ids):
        for j, to_id in enumerate(gare_ids):
            if i == j:
                continue
            duration_s = tollfree_durations[i][j]
            distance_m = tollfree_distances[i][j]
            if duration_s is None or distance_m is None:
                # No toll-free route between these two points in this extract
                # (e.g. one or both gates lie outside bfc-ara coverage).
                # Missing edges are silently omitted per spec; the gap is
                # logged (aggregate count) and reconciled in Phase 2d's
                # coverage audit, not here.
                no_tollfree_route_count += 1
                continue
            in_node = Node(to_id, NodeRole.IN)
            for source_role in (NodeRole.OUT, NodeRole.OUT_TOLL):
                graph.edges.append(
                    Edge(Node(from_id, source_role), in_node, EdgeType.TOLL_FREE, duration_s, distance_m)
                )
                tollfree_edge_count += 1

    if no_tollfree_route_count:
        logger.info(
            "%d of %d gate pairs had no toll-free OSRM route in this extract; omitted",
            no_tollfree_route_count,
            n * (n - 1),
        )

    logger.info(
        "overlay graph built: %d nodes, %d toll edges, %d toll-free edges, %d dwell "
        "edges (%d edges total)",
        len(graph.nodes),
        toll_edge_count,
        tollfree_edge_count,
        dwell_edge_count,
        len(graph.edges),
    )
    return graph


def add_access_edges(
    graph: Graph,
    osrm_client: httpx.Client,
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> tuple[Node, Node]:
    """Add per-query origin/destination access edges to an existing graph.

    Origin and destination aren't part of the static gate graph (they're
    arbitrary query-time coordinates), so this is a separate step from
    `build_graph`, called once per routing request by the CLI/API (Phase 1c
    CLI item, Phase 1d API item). Returns the (origin_node, destination_node)
    added so the caller can run Dijkstra from/to them.

    Origin lands on every gate's IN node (an ordinary approach — fine to
    enter a toll edge immediately afterwards, same as any other IN arrival).
    Destination is reachable from every gate's OUT and OUT_TOLL node (both
    are valid "off the tolled network, free to finish the journey" points).
    """
    origin_node = Node(-1, NodeRole.IN)
    destination_node = Node(-2, NodeRole.OUT)
    graph.add_node(origin_node)
    graph.add_node(destination_node)

    o_lat, o_lon = origin
    d_lat, d_lon = destination

    for node in list(graph.node_index):
        gid, role = node.gare_id, node.role
        if gid < 0:
            continue  # origin_node/destination_node just added above
        if role is NodeRole.IN:
            g_lat, g_lon = graph.gate_coords[gid]
            route = _osrm_route(osrm_client, (o_lat, o_lon), (g_lat, g_lon))
            graph.edges.append(
                Edge(
                    origin_node,
                    Node(gid, NodeRole.IN),
                    EdgeType.ACCESS,
                    route["duration"],
                    route["distance"],
                )
            )
        elif role in (NodeRole.OUT, NodeRole.OUT_TOLL):
            g_lat, g_lon = graph.gate_coords[gid]
            route = _osrm_route(osrm_client, (g_lat, g_lon), (d_lat, d_lon))
            graph.edges.append(
                Edge(
                    Node(gid, role),
                    destination_node,
                    EdgeType.ACCESS,
                    route["duration"],
                    route["distance"],
                )
            )

    return origin_node, destination_node


def _osrm_route(
    client: httpx.Client, origin: tuple[float, float], destination: tuple[float, float]
) -> dict:
    o_lat, o_lon = origin
    d_lat, d_lon = destination
    resp = client.get(f"/route/v1/car/{o_lon},{o_lat};{d_lon},{d_lat}?overview=false")
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != "Ok":
        raise RuntimeError(f"OSRM /route failed for {origin}->{destination}: {data}")
    return data["routes"][0]
