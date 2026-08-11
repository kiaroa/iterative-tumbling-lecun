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

Implemented from Phase 1c onward so Phase 2c's multi-operator graph (now wired
in via `boundary`/`exit_reentry` transfer edges, see `build_graph` below)
inherits the rule unchanged rather than needing a retrofit.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import httpx
import numpy as np

from tollroute.etl import cluster_gates

logger = logging.getLogger(__name__)

DWELL_DURATION_S = 180.0
DWELL_DISTANCE_M = 500.0

# Fallback motorway speed used only when the precomputed matrix has no route
# between two physical gate points (the national tolled matrix had zero such
# gaps as of Phase 3b, but the fallback stays as defensive handling for a
# regional-only DB or a future matrix rebuild with real gaps). The toll edge
# is still added (never silently dropped) rather than losing the fare entirely.
FALLBACK_SPEED_KMH = 110.0


class EdgeType(str, Enum):
    TOLL = "toll"
    TOLL_FREE = "toll_free"
    DWELL = "dwell"
    ACCESS = "access"
    BOUNDARY = "boundary"
    EXIT_REENTRY = "exit_reentry"


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
    # Excludes suspect_gates (Phase 2d/3c quarantine) so the graph never
    # routes through a gate flagged with a bad snap or >20% distance error.
    return conn.execute(
        "SELECT gare_id, snap_lat, snap_lon FROM gates "
        "WHERE snap_lat IS NOT NULL AND snap_lon IS NOT NULL "
        "AND gare_id NOT IN (SELECT gare_id FROM suspect_gates) "
        "ORDER BY gare_id"
    ).fetchall()


# osrm-routed's default --max-table-size caps max(len(sources), len(destinations))
# at 100 per request (confirmed empirically against the running bfc-ara instance:
# 100 passes, 101 returns {"code":"TooBig"}), independent of the full location
# list's length. With ~209 APRR gates the full N x N matrix needs tiling into
# <=100 x <=100 blocks and stitching, rather than one request.
OSRM_TABLE_MAX_DIMENSION = 100


def osrm_table(
    client: httpx.Client, coords: list[tuple[float, float]], exclude_toll: bool
) -> tuple[list[list[float | None]], list[list[float | None]]]:
    """Full N x N duration+distance matrices, tiled into <=100x100 OSRM /table calls.

    `coords` is a list of (lat, lon); OSRM's own wire format is lon,lat.
    Public because Phase 3b's national 815x815 matrix precompute
    (`tollroute/matrices.py`) reuses the same tiling logic rather than
    duplicating it.
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


def build_graph(
    conn: sqlite3.Connection,
    gare_master_path: Path = cluster_gates.DEFAULT_GARE_MASTER_PATH,
    matrix_dir: Path | None = None,
) -> Graph:
    """Build the overlay graph for whatever gates/fares `conn` has loaded.

    Generic over regional (APRR-only) and national (all-operator) DBs alike -
    the caller decides scope by which DB it connects to. Gate-to-gate
    distance/time comes from Phase 3b's precomputed 815-physical-point
    matrices rather than a live OSRM `/table` call (Phase 4b-follow-up
    decision: the matrix already covers every physical gate nationally, and
    re-fetching an 815x815 table live on every service boot would be far
    slower than reading a 10 MB `.npy` file - `add_access_edges` remains the
    only per-request/per-startup live OSRM caller). `tollroute.matrices` is
    imported lazily below because it itself imports `osrm_table` from this
    module - a module-level import here would be circular.
    """
    from tollroute import matrices as matrices_mod

    if matrix_dir is None:
        matrix_dir = matrices_mod.DEFAULT_MATRIX_DIR

    gate_rows = _gate_rows(conn)
    gare_ids = [r[0] for r in gate_rows]
    coords = [(r[1], r[2]) for r in gate_rows]
    n = len(gare_ids)
    if n == 0:
        raise RuntimeError(
            "no gates have snapped coordinates - run tollroute.etl.snap_report first"
        )
    gate_position = {gid: i for i, gid in enumerate(gare_ids)}

    logger.info("building overlay graph for %d snapped gates", n)

    # gare_id -> physical_gate_id -> matrix row/column, straight from Phase
    # 2c's clustering (same CSV, same ordering matrices.py used to compute
    # the .npy files, so the index is guaranteed to line up).
    clusters = matrices_mod.physical_gate_points(gare_master_path)
    physical_gate_id_of = cluster_gates.build_lookup(clusters)
    matrix_index_of_physical_id = {c.physical_gate_id: i for i, c in enumerate(clusters)}
    mats = matrices_mod.load_matrices(matrix_dir)
    tolled_durations = mats["tolled_duration_s"]
    tolled_distances = mats["tolled_distance_m"]
    tollfree_durations = mats["tollfree_duration_s"]
    tollfree_distances = mats["tollfree_distance_m"]

    def _matrix_index(gid: int) -> int | None:
        pid = physical_gate_id_of.get(gid)
        return None if pid is None else matrix_index_of_physical_id[pid]

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
    freeflow_selfloop_count = 0
    for from_id, to_id, operator, c1, c2, c3, c4, c5, distance_km in fare_rows:
        if from_id not in gate_position or to_id not in gate_position:
            # References a gate with no lat/lon, a quarantined suspect_gates
            # entry, or (defensively) one absent from gare_master.csv's own
            # clustering - can't be matrixed, so there's no OSRM-derived
            # distance/time to attach. The edge is logged as skipped, not
            # dropped silently.
            no_coords_count += 1
            continue

        if from_id == to_id:
            # Free-flow (barrierless) single-gantry flat fee (Phase 2c
            # finding: A14's 5 fare rows are self-loops, e.g. gate 547
            # "PEAGE DE MONTESSON"). There is no second endpoint to derive a
            # driven distance/time from - the gantry charges on pass-through,
            # not across a mapped entry->exit span - so the section is
            # priced at zero physical distance/duration rather than routed
            # through OSRM or the distance_km/FALLBACK_SPEED_KMH detour
            # fallback below (both of which assume two distinct points).
            # The fee still applies in full: routing.py sums toll_eur on
            # every TOLL edge regardless of duration/distance, so this is a
            # genuinely priced edge (OUT -> IN_TOLL of the same gate), not a
            # dropped or degenerate one.
            graph.edges.append(
                Edge(
                    Node(from_id, NodeRole.OUT),
                    Node(to_id, NodeRole.IN_TOLL),
                    EdgeType.TOLL,
                    0.0,
                    0.0,
                    operator=operator,
                    toll_eur={1: c1, 2: c2, 3: c3, 4: c4, 5: c5},
                )
            )
            freeflow_selfloop_count += 1
            toll_edge_count += 1
            continue

        pi, pj = _matrix_index(from_id), _matrix_index(to_id)
        if pi is None or pj is None:
            no_coords_count += 1
            continue
        duration_s = tolled_durations[pi, pj]
        distance_m = tolled_distances[pi, pj]
        if np.isnan(duration_s) or np.isnan(distance_m):
            no_osrm_route_count += 1
            distance_m = (distance_km or 0.0) * 1000.0
            duration_s = distance_m / (FALLBACK_SPEED_KMH * 1000.0 / 3600.0)
        else:
            duration_s, distance_m = float(duration_s), float(distance_m)

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
            "%d fare rows reference a gate with no coordinates, a quarantined gate, or "
            "an unclustered gate; skipped as toll edges",
            no_coords_count,
        )
    if no_osrm_route_count:
        logger.warning(
            "%d toll edges had no OSRM route in the precomputed matrix; used distance_km "
            "+ %.0f km/h fallback instead",
            no_osrm_route_count,
            FALLBACK_SPEED_KMH,
        )
    if freeflow_selfloop_count:
        logger.info(
            "%d toll edges are free-flow single-gantry self-loops (e.g. A14); "
            "priced at zero physical distance/duration",
            freeflow_selfloop_count,
        )

    tollfree_edge_count = 0
    no_tollfree_route_count = 0
    same_physical_point_count = 0
    for from_id in gare_ids:
        for to_id in gare_ids:
            if from_id == to_id:
                continue
            pi, pj = _matrix_index(from_id), _matrix_index(to_id)
            if pi is None or pj is None:
                no_tollfree_route_count += 1
                continue
            if pi == pj:
                # Same physical point, different gare_id (e.g. two operators'
                # co-located gates) - their connectivity is the transfer-edge
                # mechanism's job below, not a routed toll-free leg.
                same_physical_point_count += 1
                continue
            duration_s = tollfree_durations[pi, pj]
            distance_m = tollfree_distances[pi, pj]
            if np.isnan(duration_s) or np.isnan(distance_m):
                # No toll-free route between these two physical points (a
                # genuine OSRM NoRoute, per Phase 3b's near-isolated-gate
                # finding). Missing edges are silently omitted per spec; the
                # gap is logged (aggregate count) here, not fabricated.
                no_tollfree_route_count += 1
                continue
            in_node = Node(to_id, NodeRole.IN)
            for source_role in (NodeRole.OUT, NodeRole.OUT_TOLL):
                graph.edges.append(
                    Edge(
                        Node(from_id, source_role),
                        in_node,
                        EdgeType.TOLL_FREE,
                        float(duration_s),
                        float(distance_m),
                    )
                )
                tollfree_edge_count += 1

    if no_tollfree_route_count:
        logger.info(
            "%d of %d gate pairs had no toll-free OSRM route in the precomputed matrix; omitted",
            no_tollfree_route_count,
            n * (n - 1),
        )
    if same_physical_point_count:
        logger.info(
            "%d gate pairs share a physical point; connectivity left to transfer edges",
            same_physical_point_count,
        )

    boundary_edge_count, exit_reentry_edge_count = _add_transfer_edges(
        graph, gare_master_path, gate_position
    )

    logger.info(
        "overlay graph built: %d nodes, %d toll edges, %d toll-free edges, %d dwell "
        "edges, %d boundary edges, %d exit_reentry edges (%d edges total)",
        len(graph.nodes),
        toll_edge_count,
        tollfree_edge_count,
        dwell_edge_count,
        boundary_edge_count,
        exit_reentry_edge_count,
        len(graph.edges),
    )
    return graph


def _add_transfer_edges(
    graph: Graph, gare_master_path: Path, gate_position: dict[int, int]
) -> tuple[int, int]:
    """Wire Phase 2c's `boundary`/`exit_reentry` transfer edges into the graph.

    `boundary` (free, zero-time, disjoint operators) is the only permitted
    connector between two different-operator toll edges (Core architectural
    decision): it lands on OUT, the same node role a toll edge may start
    from, so a toll arrival at gate A can dwell then cross straight onto
    gate B's toll network with no extra stop. `exit_reentry` (3 min / 0.5 km
    dwell, shared operator) lands on IN instead - the ordinary arrival node -
    so a further per-gate dwell is required before any new toll edge,
    preserving the same-operator no-chaining rule exactly as an ordinary
    approach would.

    Read straight from `gare_master.csv` (via `cluster_gates.read_gates` +
    `type_transfer_edges`) rather than a persisted table - Phase 2c never
    added one, and this is the exact, already-validated computation behind
    `reports/phase2c_clustering.md`, so re-deriving it here (rather than a
    parallel DB-sourced version) can't silently diverge from that report.
    """
    gates, _coordinateless = cluster_gates.read_gates(gare_master_path)
    transfer_edges = cluster_gates.type_transfer_edges(gates)

    boundary_edge_count = 0
    exit_reentry_edge_count = 0
    skipped_count = 0
    for te in transfer_edges:
        if te.a_gare_id not in gate_position or te.b_gare_id not in gate_position:
            # One side is unloaded, coordinate-less, or quarantined in
            # suspect_gates - not a graph node, so the transfer edge can't
            # attach. Skipped, not fabricated against a missing node.
            skipped_count += 1
            continue
        a, b = te.a_gare_id, te.b_gare_id
        if te.transfer_type is cluster_gates.TransferType.BOUNDARY:
            for src_role in (NodeRole.OUT, NodeRole.OUT_TOLL):
                graph.edges.append(Edge(Node(a, src_role), Node(b, NodeRole.OUT), EdgeType.BOUNDARY, 0.0, 0.0))
                graph.edges.append(Edge(Node(b, src_role), Node(a, NodeRole.OUT), EdgeType.BOUNDARY, 0.0, 0.0))
            boundary_edge_count += 4
        else:
            dwell_s = te.dwell_min * 60.0
            dwell_m = te.dwell_km * 1000.0
            for src_role in (NodeRole.OUT, NodeRole.OUT_TOLL):
                graph.edges.append(
                    Edge(Node(a, src_role), Node(b, NodeRole.IN), EdgeType.EXIT_REENTRY, dwell_s, dwell_m)
                )
                graph.edges.append(
                    Edge(Node(b, src_role), Node(a, NodeRole.IN), EdgeType.EXIT_REENTRY, dwell_s, dwell_m)
                )
            exit_reentry_edge_count += 4

    if skipped_count:
        logger.info(
            "%d transfer edges reference a gate absent from this graph; skipped",
            skipped_count,
        )
    return boundary_edge_count, exit_reentry_edge_count


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

    no_toll_free_access_count = 0
    for node in list(graph.node_index):
        gid, role = node.gare_id, node.role
        if gid < 0:
            continue  # origin_node/destination_node just added above
        if role is NodeRole.IN:
            g_lat, g_lon = graph.gate_coords[gid]
            # exclude=toll: the origin hasn't paid to enter the tolled
            # network yet, so its approach to a gate must not be able to
            # ride a tolled section for free ahead of that gate.
            route = _osrm_route(osrm_client, (o_lat, o_lon), (g_lat, g_lon), exclude_toll=True)
            if route is None:
                no_toll_free_access_count += 1
                continue
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
            # exclude=toll: OUT/OUT_TOLL are documented as "off the tolled
            # network, free to finish the journey" - without this, OSRM's
            # plain /route can route the "local finish" straight back onto
            # the paid motorway, letting Dijkstra ride it for free and
            # defeating the whole toll-edge accounting (confirmed empirically:
            # Dijon->Lyon's access edge alone reproduced the tolled route's
            # distance/duration almost exactly, at zero toll).
            route = _osrm_route(osrm_client, (g_lat, g_lon), (d_lat, d_lon), exclude_toll=True)
            if route is None:
                no_toll_free_access_count += 1
                continue
            graph.edges.append(
                Edge(
                    Node(gid, role),
                    destination_node,
                    EdgeType.ACCESS,
                    route["duration"],
                    route["distance"],
                )
            )

    if no_toll_free_access_count:
        logger.info(
            "%d access edges had no toll-free OSRM route and were omitted "
            "(spec: missing edges silently omitted, gap logged)",
            no_toll_free_access_count,
        )

    return origin_node, destination_node


def _osrm_route(
    client: httpx.Client,
    origin: tuple[float, float],
    destination: tuple[float, float],
    exclude_toll: bool = False,
) -> dict | None:
    """Returns None (not an exception) when OSRM reports NoRoute - a toll-free
    route genuinely doesn't exist between some point pairs (e.g. a gate that
    can only be reached via a tolled segment even locally), and the spec's
    "missing edges: silently omitted, gap logged" convention applies here
    the same way it does to the toll-free gate-to-gate matrix in build_graph.
    """
    o_lat, o_lon = origin
    d_lat, d_lon = destination
    params = "overview=false"
    if exclude_toll:
        params += "&exclude=toll"
    resp = client.get(f"/route/v1/car/{o_lon},{o_lat};{d_lon},{d_lat}?{params}")
    data = resp.json()
    if data.get("code") == "NoRoute":
        return None
    resp.raise_for_status()
    if data["code"] != "Ok":
        raise RuntimeError(f"OSRM /route failed for {origin}->{destination}: {data}")
    return data["routes"][0]
