"""scipy Dijkstra over the Phase 1c overlay graph, with predecessor re-walk.

Phase 1c precedes Phase 4a's generalised-cost function (`G = toll +
km*running_cost_per_km + hours*VoT`, backed by the still-empty `class_config`
table), so the spec does not mandate a specific optimisation metric for this
phase - only that Dijkstra runs over the overlay graph and toll/time/distance
are accumulated separately via a predecessor re-walk.

**Design choice (not spec-mandated, flagged per project convention):** edges
are weighted by `duration_s` (fastest route), matching OSRM's own default.
Weighting by `toll_eur` alone was rejected: every non-toll edge costs €0, so
a toll-weighted Dijkstra would trivially always select an all-toll-free path
regardless of duration, which is a degenerate result rather than a useful
one. Phase 4a's generalised cost supersedes this weighting with a real
toll/time/distance trade-off.
"""

from __future__ import annotations

from collections import ChainMap
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from tollroute.graph import Edge, EdgeType, Graph, Node


class RouteNotFoundError(RuntimeError):
    pass


@dataclass
class Route:
    nodes: list[Node]
    edges: list[Edge]
    toll_eur: float
    duration_s: float
    distance_m: float


@dataclass
class EdgeArrays:
    """The sparsity pattern (row/col indices) plus every per-edge cost
    component `find_route` and `pareto_sweep` need, built in one pass over
    `graph.edges` so a caller running several Dijkstra searches against the
    same graph/vehicle_class (e.g. `response.shape_response`'s fastest +
    10-step VoT sweep + best_value re-sweep) can build it once and reuse it,
    instead of each independently re-walking the graph and rebuilding a
    `dict[(i, j), Edge]` from scratch. Profiling a national-graph request
    (Phase 4c-follow-up) found this per-edge dict/hash rebuild - not the
    Dijkstra runs or COO->CSR conversion themselves - was the dominant cost:
    ~2s of a ~1.8-2.7s warm `/route` response was three redundant rebuilds of
    the same ~900k-edge structure.
    """

    rows: np.ndarray
    cols: np.ndarray
    edge_lookup: Mapping[tuple[int, int], Edge]
    duration_arr: np.ndarray
    toll_arr: np.ndarray
    km_arr: np.ndarray
    hr_arr: np.ndarray


@dataclass
class StaticEdgeArrays:
    """Cache of `EdgeArrays`' components for exactly `graph.edges[:graph.
    static_edge_count]` - the edges present right after `build_graph`
    finishes, before any per-request access edge is added. Built once by
    `finalize_static_edge_arrays`; `build_edge_arrays` concatenates this with
    the handful of per-request access edges instead of re-looping over all
    ~900k static edges every request (Phase 4c-follow-up-3).

    `toll_arr` is precomputed for all 5 vehicle classes (rather than the one
    requested per call) since it's cheap to do once at startup and access
    edges never carry a toll, so no other per-class recomputation is needed
    afterwards.
    """

    rows: np.ndarray
    cols: np.ndarray
    duration_arr: np.ndarray
    km_arr: np.ndarray
    hr_arr: np.ndarray
    toll_arr_by_class: dict[int, np.ndarray]
    edge_lookup: dict[tuple[int, int], Edge]


def _edge_indices(graph: Graph, edge: Edge) -> tuple[int, int]:
    i = edge.from_idx if edge.from_idx >= 0 else graph.node_index[edge.from_node]
    j = edge.to_idx if edge.to_idx >= 0 else graph.node_index[edge.to_node]
    return i, j


def finalize_static_edge_arrays(graph: Graph) -> None:
    """Populates `graph.static_edge_count`/`static_edge_arrays` from
    `graph.edges` as they stand right now.

    Must only be called once, by `build_graph`, after every static edge
    (toll/toll-free/dwell/boundary/exit_reentry) has been added and before
    this graph is ever passed to `add_access_edges` - anything added after
    this call is treated by `build_edge_arrays` as a per-request access edge,
    so calling it late would wrongly freeze request-specific edges as if
    they were static.
    """
    edge_lookup: dict[tuple[int, int], Edge] = {}
    for edge in graph.edges:
        edge_lookup[_edge_indices(graph, edge)] = edge

    m = len(edge_lookup)
    rows = np.empty(m, dtype=np.int64)
    cols = np.empty(m, dtype=np.int64)
    duration_arr = np.empty(m, dtype=np.float64)
    km_arr = np.empty(m, dtype=np.float64)
    hr_arr = np.empty(m, dtype=np.float64)
    toll_arr_by_class: dict[int, np.ndarray] = {vc: np.zeros(m, dtype=np.float64) for vc in (1, 2, 3, 4, 5)}

    for idx, ((i, j), edge) in enumerate(edge_lookup.items()):
        rows[idx] = i
        cols[idx] = j
        duration_arr[idx] = edge.duration_s
        km_arr[idx] = edge.distance_m / 1000.0
        hr_arr[idx] = edge.duration_s / 3600.0
        if edge.edge_type == EdgeType.TOLL:
            for vc, toll_arr in toll_arr_by_class.items():
                toll_arr[idx] = edge.toll_eur[vc]

    graph.static_edge_count = len(graph.edges)
    graph.static_edge_arrays = StaticEdgeArrays(
        rows=rows,
        cols=cols,
        duration_arr=duration_arr,
        km_arr=km_arr,
        hr_arr=hr_arr,
        toll_arr_by_class=toll_arr_by_class,
        edge_lookup=edge_lookup,
    )


def _build_edge_arrays_full(graph: Graph, vehicle_class: int) -> EdgeArrays:
    """Full per-edge rebuild, used when `graph.static_edge_arrays` hasn't
    been populated (a `Graph` built directly, e.g. via `Graph(...)` in unit
    tests, rather than through `build_graph`).

    Node-index pairs are unique per Edge by construction (see graph.py's
    four-role node split), so no two distinct edges should ever share an
    (i, j) key; "keep last seen" on a colliding key is a defensive fallback,
    not a path this graph is expected to exercise.
    """
    edge_lookup: dict[tuple[int, int], Edge] = {}
    for edge in graph.edges:
        edge_lookup[_edge_indices(graph, edge)] = edge

    m = len(edge_lookup)
    rows = np.empty(m, dtype=np.int64)
    cols = np.empty(m, dtype=np.int64)
    duration_arr = np.empty(m, dtype=np.float64)
    toll_arr = np.zeros(m, dtype=np.float64)
    km_arr = np.empty(m, dtype=np.float64)
    hr_arr = np.empty(m, dtype=np.float64)

    for idx, ((i, j), edge) in enumerate(edge_lookup.items()):
        rows[idx] = i
        cols[idx] = j
        duration_arr[idx] = edge.duration_s
        km_arr[idx] = edge.distance_m / 1000.0
        hr_arr[idx] = edge.duration_s / 3600.0
        if edge.edge_type == EdgeType.TOLL:
            toll_arr[idx] = edge.toll_eur[vehicle_class]

    return EdgeArrays(rows, cols, edge_lookup, duration_arr, toll_arr, km_arr, hr_arr)


def _build_edge_arrays_incremental(
    graph: Graph, sea: StaticEdgeArrays, vehicle_class: int
) -> EdgeArrays:
    """Concatenates `sea` (the cached ~900k-edge static prefix) with arrays
    built only for `graph.edges[graph.static_edge_count:]` - the handful of
    access edges `add_access_edges` added for this request - instead of
    re-looping over every static edge again.
    """
    new_edges = graph.edges[graph.static_edge_count :]
    if not new_edges:
        return EdgeArrays(
            sea.rows,
            sea.cols,
            sea.edge_lookup,
            sea.duration_arr,
            sea.toll_arr_by_class[vehicle_class],
            sea.km_arr,
            sea.hr_arr,
        )

    m = len(new_edges)
    new_rows = np.empty(m, dtype=np.int64)
    new_cols = np.empty(m, dtype=np.int64)
    new_duration = np.empty(m, dtype=np.float64)
    new_toll = np.zeros(m, dtype=np.float64)
    new_km = np.empty(m, dtype=np.float64)
    new_hr = np.empty(m, dtype=np.float64)
    new_edge_lookup: dict[tuple[int, int], Edge] = {}

    for idx, edge in enumerate(new_edges):
        i, j = _edge_indices(graph, edge)
        new_rows[idx] = i
        new_cols[idx] = j
        new_duration[idx] = edge.duration_s
        new_km[idx] = edge.distance_m / 1000.0
        new_hr[idx] = edge.duration_s / 3600.0
        if edge.edge_type == EdgeType.TOLL:
            new_toll[idx] = edge.toll_eur[vehicle_class]
        new_edge_lookup[(i, j)] = edge

    return EdgeArrays(
        rows=np.concatenate([sea.rows, new_rows]),
        cols=np.concatenate([sea.cols, new_cols]),
        edge_lookup=ChainMap(new_edge_lookup, sea.edge_lookup),
        duration_arr=np.concatenate([sea.duration_arr, new_duration]),
        toll_arr=np.concatenate([sea.toll_arr_by_class[vehicle_class], new_toll]),
        km_arr=np.concatenate([sea.km_arr, new_km]),
        hr_arr=np.concatenate([sea.hr_arr, new_hr]),
    )


def build_edge_arrays(graph: Graph, vehicle_class: int) -> EdgeArrays:
    """Builds the sparsity pattern plus every per-edge cost component
    `find_route`/`pareto_sweep` need.

    Dispatches to `_build_edge_arrays_incremental` when `graph.
    static_edge_arrays` has been populated (i.e. `graph` came from
    `build_graph`, whose static ~900k edges never change between requests -
    see `StaticEdgeArrays`'s docstring), falling back to a full rebuild
    otherwise (e.g. a `Graph` built directly via `Graph(...)` in unit tests).
    """
    sea = graph.static_edge_arrays
    if sea is not None:
        return _build_edge_arrays_incremental(graph, sea, vehicle_class)
    return _build_edge_arrays_full(graph, vehicle_class)


def route_from_predecessors(
    graph: Graph,
    edge_lookup: Mapping[tuple[int, int], Edge],
    predecessors,
    origin: Node,
    origin_idx: int,
    dest_idx: int,
    vehicle_class: int,
) -> Route:
    """Re-walks a scipy `dijkstra(..., return_predecessors=True)` predecessor
    array from `dest_idx` back to `origin_idx`, accumulating toll/duration/
    distance from each edge on the path.

    Public (not `find_route`-private) because Phase 4a's Pareto VoT sweep
    (`tollroute/pareto.py`) re-runs Dijkstra against a generalised-cost
    weighting rather than `duration_s`, but needs the exact same walk-back
    and toll/time/distance accumulation this function already does - sharing
    it means the two weightings can never silently diverge in how a route's
    totals are computed.
    """
    if predecessors[dest_idx] < 0:
        raise RouteNotFoundError(f"no path from {origin} to {graph.nodes[dest_idx]}")

    path_indices = [dest_idx]
    current = dest_idx
    while current != origin_idx:
        prev = predecessors[current]
        if prev < 0:
            raise RouteNotFoundError(f"no path from {origin} to {graph.nodes[dest_idx]}")
        path_indices.append(prev)
        current = prev
    path_indices.reverse()

    nodes = [graph.nodes[i] for i in path_indices]
    edges: list[Edge] = []
    toll_eur = 0.0
    duration_s = 0.0
    distance_m = 0.0
    for i, j in zip(path_indices, path_indices[1:]):
        edge = edge_lookup[(i, j)]
        edges.append(edge)
        duration_s += edge.duration_s
        distance_m += edge.distance_m
        if edge.edge_type == EdgeType.TOLL:
            toll_eur += edge.toll_eur[vehicle_class]

    return Route(nodes=nodes, edges=edges, toll_eur=toll_eur, duration_s=duration_s, distance_m=distance_m)


def find_route(
    graph: Graph,
    origin: Node,
    destination: Node,
    vehicle_class: int,
    edge_arrays: EdgeArrays | None = None,
) -> Route:
    """Shortest (by duration) path from origin to destination, with toll,
    duration and distance accumulated separately from the predecessor chain.

    `edge_arrays` lets a caller that's about to run several Dijkstra searches
    against the same graph/vehicle_class (`response.shape_response`) pass in
    an already-built `EdgeArrays` rather than have this rebuild one; omit it
    for a one-off call, which builds it internally as before.
    """
    if vehicle_class not in (1, 2, 3, 4, 5):
        raise ValueError(f"vehicle_class must be 1-5, got {vehicle_class}")

    ea = edge_arrays if edge_arrays is not None else build_edge_arrays(graph, vehicle_class)
    origin_idx = graph.node_index[origin]
    dest_idx = graph.node_index[destination]

    if origin_idx == dest_idx:
        return Route(nodes=[origin], edges=[], toll_eur=0.0, duration_s=0.0, distance_m=0.0)

    n = len(graph.nodes)
    matrix = csr_matrix((ea.duration_arr, (ea.rows, ea.cols)), shape=(n, n))
    _dist, predecessors = dijkstra(
        matrix, directed=True, indices=origin_idx, return_predecessors=True
    )

    return route_from_predecessors(
        graph, ea.edge_lookup, predecessors, origin, origin_idx, dest_idx, vehicle_class
    )
