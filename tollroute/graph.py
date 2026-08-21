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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from tollroute import routing_engine as routing_engine_mod
from tollroute.etl import cluster_gates

if TYPE_CHECKING:
    from tollroute.routing import StaticEdgeArrays

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
    # Cached `graph.node_index[from_node]`/`[to_node]`, resolved once by
    # `Graph.add_edge` at construction time (Phase 4c-follow-up-2) so
    # `routing.build_edge_arrays` never needs to re-hash the frozen `Node`
    # dataclass on every request. -1 for edges built directly via `Edge(...)`
    # outside `Graph.add_edge` (e.g. response-shaping unit tests that never
    # reach `build_edge_arrays`).
    from_idx: int = -1
    to_idx: int = -1


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    node_index: dict[Node, int] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    # gare_id -> (lat, lon), snap coordinates used to build this graph; kept
    # alongside it so add_access_edges can OSRM-route to/from any gate
    # without a second DB round-trip.
    gate_coords: dict[int, tuple[float, float]] = field(default_factory=dict)
    # Phase 5b-follow-up-1 (direction split: Phase 5b-follow-up-1-continued):
    # gare_id -> (anchor_lat, anchor_lon, apron_distance_m, apron_duration_s), for gates
    # whose own coordinate isn't directly toll-free reachable in that direction (it's the
    # physical barrier, sitting on tolled tarmac by definition - see
    # tollroute.etl.access_anchors' docstring for the investigation). Separate dicts
    # because reachability on a divided/oneway motorway is directional - a gate's entry
    # anchor (used for origin->gate IN-node legs) and exit anchor (used for gate->
    # destination OUT/OUT_TOLL-node legs) are not interchangeable and were verified to
    # often differ. Only gates that needed one for that direction have an entry;
    # `add_access_edges` uses the raw `gate_coords` entry unchanged for every other gate.
    access_anchors_entry: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)
    access_anchors_exit: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)
    # Phase 5b-follow-up-2-continued: gare_ids priced as a free-flow single-gantry
    # self-loop toll edge (OUT -> IN_TOLL of the same gate; A14's 5 dataset rows,
    # plus any freeflow.seed_*-inserted structure like Millau). Unlike an ordinary
    # two-endpoint gate, a self-loop gate's OUT node has no genuine physical
    # toll-free lane around the gantry - it is the exact same point as IN_TOLL, just
    # not yet paid. `add_access_edges` uses this set to withhold the OUT-node exit
    # access edge (destination-bound) for these gates, since granting one lets a
    # route "arrive" at the gate and leave again without ever crossing the TOLL
    # edge, defeating the fee - see that function's docstring for the investigation.
    freeflow_selfloop_gate_ids: set[int] = field(default_factory=set)
    # Phase 4c-follow-up-3: cache of routing.build_edge_arrays's numpy arrays
    # for exactly `edges[:static_edge_count]` - the edges present right after
    # `build_graph` finishes, before any per-request access edge is added.
    # Populated once by `routing.finalize_static_edge_arrays` (called at the
    # end of `build_graph`, below) so a per-request `build_edge_arrays` call
    # only has to build arrays for the handful of new access edges and
    # concatenate them onto this cached prefix, instead of re-looping over
    # all ~900k static edges every request. `None` for a `Graph` built
    # directly (e.g. via `Graph(...)` in unit tests) rather than through
    # `build_graph` - `build_edge_arrays` falls back to a full rebuild in
    # that case.
    static_edge_count: int = 0
    static_edge_arrays: "StaticEdgeArrays | None" = None

    def add_node(self, node: Node) -> int:
        if node not in self.node_index:
            self.node_index[node] = len(self.nodes)
            self.nodes.append(node)
        return self.node_index[node]

    def add_edge(
        self,
        from_node: Node,
        to_node: Node,
        edge_type: EdgeType,
        duration_s: float,
        distance_m: float,
        operator: str | None = None,
        toll_eur: dict[int, float] | None = None,
    ) -> Edge:
        """Builds and appends an `Edge`, resolving `from_idx`/`to_idx` from
        `node_index` once here rather than leaving every later Dijkstra
        request to re-resolve them (see `Edge.from_idx`/`to_idx`). Both nodes
        must already be registered via `add_node`.
        """
        edge = Edge(
            from_node=from_node,
            to_node=to_node,
            edge_type=edge_type,
            duration_s=duration_s,
            distance_m=distance_m,
            operator=operator,
            toll_eur=toll_eur,
            from_idx=self.node_index[from_node],
            to_idx=self.node_index[to_node],
        )
        self.edges.append(edge)
        return edge


def _gate_rows(conn: sqlite3.Connection) -> list[tuple[int, float, float]]:
    # Excludes suspect_gates (Phase 2d/3c quarantine) so the graph never
    # routes through a gate flagged with a bad snap or >20% distance error.
    return conn.execute(
        "SELECT gare_id, snap_lat, snap_lon FROM gates "
        "WHERE snap_lat IS NOT NULL AND snap_lon IS NOT NULL "
        "AND gare_id NOT IN (SELECT gare_id FROM suspect_gates) "
        "ORDER BY gare_id"
    ).fetchall()


def _access_anchor_rows(
    conn: sqlite3.Connection,
) -> tuple[dict[int, tuple[float, float, float, float]], dict[int, tuple[float, float, float, float]]]:
    """Phase 5b-follow-up-1's precomputed anchors (tollroute.etl.access_anchors),
    keyed by gare_id, split into (entry, exit) dicts per Phase 5b-follow-up-1-continued's
    directional fix. Empty for a DB the precompute script hasn't been run against yet
    (e.g. most unit-test fixture DBs) - `access_anchors` not existing at all is a normal,
    expected state, not an error, so it's caught specifically here rather than let a bare
    `except Exception` hide an unrelated real failure.
    """
    try:
        rows = conn.execute(
            "SELECT gare_id, direction, anchor_lat, anchor_lon, apron_distance_m, apron_duration_s "
            "FROM access_anchors"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        return {}, {}
    entry: dict[int, tuple[float, float, float, float]] = {}
    exit_: dict[int, tuple[float, float, float, float]] = {}
    for gare_id, direction, a_lat, a_lon, dist_m, dur_s in rows:
        (entry if direction == "entry" else exit_)[gare_id] = (a_lat, a_lon, dist_m, dur_s)
    return entry, exit_


# Tile dimension; kept here because access_anchors.py imports it by this name.
# routing_engine.TABLE_MAX_DIMENSION is the authoritative copy post-migration.
OSRM_TABLE_MAX_DIMENSION = 100


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

    access_anchors_entry, access_anchors_exit = _access_anchor_rows(conn)
    graph = Graph(
        gate_coords={gid: (lat, lon) for gid, (lat, lon) in zip(gare_ids, coords)},
        access_anchors_entry=access_anchors_entry,
        access_anchors_exit=access_anchors_exit,
    )

    for gid in gare_ids:
        in_node = Node(gid, NodeRole.IN)
        out_node = Node(gid, NodeRole.OUT)
        in_toll_node = Node(gid, NodeRole.IN_TOLL)
        out_toll_node = Node(gid, NodeRole.OUT_TOLL)
        for node in (in_node, out_node, in_toll_node, out_toll_node):
            graph.add_node(node)
        graph.add_edge(in_node, out_node, EdgeType.DWELL, DWELL_DURATION_S, DWELL_DISTANCE_M)
        graph.add_edge(
            in_toll_node, out_toll_node, EdgeType.DWELL, DWELL_DURATION_S, DWELL_DISTANCE_M
        )
    dwell_edge_count = 2 * n

    # Row-level quarantine (`tollroute.validation.distance_error.quarantine_fare_rows`).
    # Guarded on the column existing so a database built before the column was added still
    # loads - the migration lives in that module, not here.
    fares_columns = {row[1] for row in conn.execute("PRAGMA table_info(fares)")}
    quarantine_clause = " AND quarantined = 0" if "quarantined" in fares_columns else ""
    fare_rows = conn.execute(
        "SELECT from_gare_id, to_gare_id, operator, class1, class2, class3, class4, class5, "
        "distance_km FROM fares WHERE from_gare_id IS NOT NULL AND to_gare_id IS NOT NULL"
        + quarantine_clause
    ).fetchall()
    quarantined_row_count = 0
    if quarantine_clause:
        quarantined_row_count = conn.execute(
            "SELECT COUNT(*) FROM fares WHERE quarantined = 1"
        ).fetchone()[0]

    # The three reasons a fare row can reference an unusable gate used to be counted as one
    # number, which is what hid a mis-targeted gate quarantine costing 13.5% of the fare
    # table. They are attributed separately now.
    suspect_gate_ids = {
        row[0] for row in conn.execute("SELECT gare_id FROM suspect_gates")
    }
    coordinateless_gate_ids = {
        row[0]
        for row in conn.execute(
            "SELECT gare_id FROM gates WHERE snap_lat IS NULL OR snap_lon IS NULL"
        )
    }

    toll_edge_count = 0
    no_coords_count = 0
    quarantined_gate_count = 0
    unclustered_count = 0
    no_osrm_route_count = 0
    freeflow_selfloop_count = 0
    zero_price_dropped_count = 0
    for from_id, to_id, operator, c1, c2, c3, c4, c5, distance_km in fare_rows:
        if from_id not in gate_position or to_id not in gate_position:
            # References a gate with no lat/lon, a quarantined suspect_gates
            # entry, or (defensively) one absent from gare_master.csv's own
            # clustering - can't be matrixed, so there's no OSRM-derived
            # distance/time to attach. The edge is logged as skipped, not
            # dropped silently.
            endpoints = (from_id, to_id)
            if any(gid in coordinateless_gate_ids for gid in endpoints):
                no_coords_count += 1
            elif any(gid in suspect_gate_ids for gid in endpoints):
                quarantined_gate_count += 1
            else:
                unclustered_count += 1
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
            graph.add_edge(
                Node(from_id, NodeRole.OUT),
                Node(to_id, NodeRole.IN_TOLL),
                EdgeType.TOLL,
                0.0,
                0.0,
                operator=operator,
                toll_eur={1: c1, 2: c2, 3: c3, 4: c4, 5: c5},
            )
            graph.freeflow_selfloop_gate_ids.add(from_id)
            freeflow_selfloop_count += 1
            toll_edge_count += 1
            continue

        # Drop zero-price fare rows for long-distance pairs. A zero fare over
        # tens of km has no structural evidence of being a genuine free section
        # and acts as a wormhole: Dijkstra exploits it to traverse a long
        # tolled section for nothing. Short zero-price hops (<=8 km, the same
        # proximity threshold used by remediate_zero_price.py) are kept as
        # plausible free short connectors / adjacent-interchange bypasses.
        if c1 == 0 and c2 == 0 and c3 == 0 and c4 == 0 and c5 == 0:
            if (distance_km or 999.0) > 8.0:
                zero_price_dropped_count += 1
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

        graph.add_edge(
            Node(from_id, NodeRole.OUT),
            Node(to_id, NodeRole.IN_TOLL),
            EdgeType.TOLL,
            duration_s,
            distance_m,
            operator=operator,
            toll_eur={1: c1, 2: c2, 3: c3, 4: c4, 5: c5},
        )
        toll_edge_count += 1

    if no_coords_count:
        logger.warning(
            "%d fare rows reference a gate with no coordinates; skipped as toll edges",
            no_coords_count,
        )
    if quarantined_gate_count:
        logger.warning(
            "%d fare rows reference a quarantined (suspect_gates) gate; skipped as toll edges",
            quarantined_gate_count,
        )
    if unclustered_count:
        logger.warning(
            "%d fare rows reference an unclustered gate; skipped as toll edges",
            unclustered_count,
        )
    if quarantined_row_count:
        logger.info(
            "%d fare rows individually quarantined on distance error; excluded by query",
            quarantined_row_count,
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
    if zero_price_dropped_count:
        logger.warning(
            "%d zero-price fare rows (distance_km > 8 km) dropped; they have no "
            "structural evidence of being a genuine free section and act as routing "
            "wormholes. Run tollroute.etl.remediate_zero_price for full disposition.",
            zero_price_dropped_count,
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
                graph.add_edge(
                    Node(from_id, source_role),
                    in_node,
                    EdgeType.TOLL_FREE,
                    float(duration_s),
                    float(distance_m),
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

    # Imported lazily - routing.py imports Edge/EdgeType/Graph/Node from this
    # module at its own module level, so a module-level import here would be
    # circular (same reasoning as the matrices_mod import above). Must run
    # after every static edge (toll/toll-free/dwell/boundary/exit_reentry) is
    # added and before this graph is ever handed to add_access_edges.
    from tollroute import routing as routing_mod

    routing_mod.finalize_static_edge_arrays(graph)

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
                graph.add_edge(Node(a, src_role), Node(b, NodeRole.OUT), EdgeType.BOUNDARY, 0.0, 0.0)
                graph.add_edge(Node(b, src_role), Node(a, NodeRole.OUT), EdgeType.BOUNDARY, 0.0, 0.0)
            boundary_edge_count += 4
        else:
            dwell_s = te.dwell_min * 60.0
            dwell_m = te.dwell_km * 1000.0
            for src_role in (NodeRole.OUT, NodeRole.OUT_TOLL):
                graph.add_edge(
                    Node(a, src_role), Node(b, NodeRole.IN), EdgeType.EXIT_REENTRY, dwell_s, dwell_m
                )
                graph.add_edge(
                    Node(b, src_role), Node(a, NodeRole.IN), EdgeType.EXIT_REENTRY, dwell_s, dwell_m
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
    engine: routing_engine_mod.RoutingEngine,
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
    Destination is reachable from every gate's OUT_TOLL node only (the node
    reached after arriving at a gate via a priced toll edge then dwelling).
    OUT is never given an exit access edge: physically, a driver who arrives
    at a gate plaza via the free-road network (ACCESS→IN→DWELL→OUT) cannot
    exit via the free-road network without first taking a toll section — the
    plaza is a one-way motorway entry/exit, not a throughway. Granting OUT an
    exit edge produces phantom €0 "pass-through" routes (origin→gate→DWELL→
    destination at zero cost) that have no physical basis.

    **Phase 4c:** fetches those legs via two batched table calls
    (`tollroute.routing_engine.RoutingEngine.one_to_many_table`/`many_to_one_table`,
    each internally tiled to <=100-wide requests) rather than one `/route` call
    per gate per direction - replaces what was up to ~1,600 sequential HTTP
    round trips (measured ~19.5 s warm against the national 815-gate DB, see
    IMPLEMENTATION_PLAN.md's Phase 4c entry) with ~18, which is what gets a
    warm request under the spec's ~300 ms budget. OUT and OUT_TOLL share the
    same physical gate coordinate, so the exit-side table is queried once per
    gate id (not once per role) and its result reused for both roles.

    **Phase 5b-follow-up-1 (direction split: Phase 5b-follow-up-1-continued):** a gate
    with a `graph.access_anchors_entry`/`access_anchors_exit` entry is queried at its
    precomputed anchor coordinate instead of its own (the gate's own coordinate is the
    physical barrier, on tolled tarmac by definition, and for some barriers that's an
    unreachable pocket in the `exclude=toll` graph even though a real driver gets there
    fine - see `tollroute.etl.access_anchors`), with the anchor's short "apron" leg added
    back onto whatever duration/distance OSRM returns. Entry and exit use separate anchors
    because reachability on a divided/oneway motorway is directional - reusing one shared
    anchor for both was verified to silently break entry access edges for most gates.

    **Phase 5b-follow-up-2-continued:** a gate in `graph.freeflow_selfloop_gate_ids`
    (A14-style single-gantry self-loop, incl. Millau) only gets its exit access edge on
    OUT_TOLL, never OUT. Direct-verified against the Millau case: granting OUT an exit
    edge too let Clermont-Ferrand->Montpellier's route go origin -> ACCESS -> gate's IN
    -> DWELL -> gate's OUT -> ACCESS -> destination, "visiting" the gate and leaving
    again without ever taking the TOLL edge to IN_TOLL, at toll_eur=0.00 - a free ride
    an ordinary two-endpoint gate's OUT node doesn't allow, because there the toll-free
    OSRM route into OUT is a genuine physical bypass lane, not the untolled near side of
    the exact same point the toll is charged at.
    """
    origin_node = Node(-1, NodeRole.IN)
    destination_node = Node(-2, NodeRole.OUT)
    graph.add_node(origin_node)
    graph.add_node(destination_node)

    entry_gids = sorted({n.gare_id for n in graph.node_index if n.gare_id >= 0 and n.role is NodeRole.IN})
    exit_gids = sorted(
        {n.gare_id for n in graph.node_index if n.gare_id >= 0 and n.role in (NodeRole.OUT, NodeRole.OUT_TOLL)}
    )
    # Phase 5b-follow-up-1: query a gate's precomputed anchor instead of its own
    # coordinate when one exists (see `tollroute.etl.access_anchors` - the gate's own
    # coordinate is the physical barrier, on tolled tarmac by definition, and for some
    # barriers that makes it an unreachable pocket in the exclude=toll graph even
    # though a real driver gets there fine). The anchor's apron_distance_m/duration_s
    # is added back onto whatever leg OSRM returns, below. Entry and exit each look up
    # their own anchor dict (Phase 5b-follow-up-1-continued: a shared anchor is not
    # direction-safe on a divided/oneway motorway).
    def _entry_query_coord(gid: int) -> tuple[float, float]:
        anchor = graph.access_anchors_entry.get(gid)
        return (anchor[0], anchor[1]) if anchor is not None else graph.gate_coords[gid]

    def _exit_query_coord(gid: int) -> tuple[float, float]:
        anchor = graph.access_anchors_exit.get(gid)
        return (anchor[0], anchor[1]) if anchor is not None else graph.gate_coords[gid]

    entry_coords = [_entry_query_coord(gid) for gid in entry_gids]
    exit_coords = [_exit_query_coord(gid) for gid in exit_gids]

    # exclude=toll on both sides: the origin hasn't paid to enter the tolled
    # network yet (its approach must not ride a tolled section for free ahead
    # of the gate), and OUT/OUT_TOLL are documented as "off the tolled
    # network, free to finish the journey" - without this, OSRM's plain
    # /route can route the "local finish" straight back onto the paid
    # motorway, letting Dijkstra ride it for free and defeating the whole
    # toll-edge accounting (confirmed empirically: Dijon->Lyon's access edge
    # alone reproduced the tolled route's distance/duration almost exactly,
    # at zero toll).
    # Phase 4c-follow-up-4: the two table batches are independent of each
    # other (one origin->gates, one gates->destination), so fire them
    # concurrently rather than paying their wall-clock sequentially.
    # Each call internally tiles its own <=100-wide blocks concurrently.
    with ThreadPoolExecutor(max_workers=2) as pool:
        entry_future = pool.submit(
            engine.one_to_many_table, origin, entry_coords, exclude_toll=True
        )
        exit_future = pool.submit(
            engine.many_to_one_table, exit_coords, destination, exclude_toll=True
        )
        entry_legs = entry_future.result()
        exit_legs = exit_future.result()

    def _with_apron(
        anchors: dict[int, tuple[float, float, float, float]], gid: int, duration: float, distance: float
    ) -> tuple[float, float]:
        anchor = anchors.get(gid)
        if anchor is None:
            return duration, distance
        _, _, apron_distance_m, apron_duration_s = anchor
        return duration + apron_duration_s, distance + apron_distance_m

    no_toll_free_access_count = 0
    for gid, leg in zip(entry_gids, entry_legs):
        if leg is None:
            no_toll_free_access_count += 1
            continue
        duration, distance = _with_apron(graph.access_anchors_entry, gid, *leg)
        graph.add_edge(origin_node, Node(gid, NodeRole.IN), EdgeType.ACCESS, duration, distance)

    for gid, leg in zip(exit_gids, exit_legs):
        if leg is None:
            no_toll_free_access_count += 1
            continue
        duration, distance = _with_apron(graph.access_anchors_exit, gid, *leg)
        for role in (NodeRole.OUT_TOLL,):
            node = Node(gid, role)
            if node not in graph.node_index:
                continue
            graph.add_edge(node, destination_node, EdgeType.ACCESS, duration, distance)

    if no_toll_free_access_count:
        logger.info(
            "%d access edges had no toll-free OSRM route and were omitted "
            "(spec: missing edges silently omitted, gap logged)",
            no_toll_free_access_count,
        )

    return origin_node, destination_node
