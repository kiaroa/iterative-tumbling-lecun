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

from dataclasses import dataclass

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


def _build_sparse(graph: Graph) -> tuple[csr_matrix, dict[tuple[int, int], Edge]]:
    """Adjacency matrix weighted by duration_s, plus the Edge used for each
    (i, j) pair so the predecessor re-walk can read back toll/distance.

    Node-index pairs are unique per Edge by construction (see graph.py's
    four-role node split), so no two distinct edges should ever share an
    (i, j) key; the "keep cheaper duration" tie-break below is a defensive
    fallback, not a path this graph is expected to exercise.
    """
    n = len(graph.nodes)
    best_edge: dict[tuple[int, int], Edge] = {}
    for edge in graph.edges:
        i = graph.node_index[edge.from_node]
        j = graph.node_index[edge.to_node]
        key = (i, j)
        current = best_edge.get(key)
        if current is None or edge.duration_s < current.duration_s:
            best_edge[key] = edge

    rows = []
    cols = []
    data = []
    for (i, j), edge in best_edge.items():
        rows.append(i)
        cols.append(j)
        data.append(edge.duration_s)

    matrix = csr_matrix((data, (rows, cols)), shape=(n, n))
    return matrix, best_edge


def find_route(graph: Graph, origin: Node, destination: Node, vehicle_class: int) -> Route:
    """Shortest (by duration) path from origin to destination, with toll,
    duration and distance accumulated separately from the predecessor chain.
    """
    if vehicle_class not in (1, 2, 3, 4, 5):
        raise ValueError(f"vehicle_class must be 1-5, got {vehicle_class}")

    matrix, edge_lookup = _build_sparse(graph)
    origin_idx = graph.node_index[origin]
    dest_idx = graph.node_index[destination]

    if origin_idx == dest_idx:
        return Route(nodes=[origin], edges=[], toll_eur=0.0, duration_s=0.0, distance_m=0.0)

    _dist, predecessors = dijkstra(
        matrix, directed=True, indices=origin_idx, return_predecessors=True
    )

    if predecessors[dest_idx] < 0:
        raise RouteNotFoundError(f"no path from {origin} to {destination}")

    path_indices = [dest_idx]
    current = dest_idx
    while current != origin_idx:
        prev = predecessors[current]
        if prev < 0:
            raise RouteNotFoundError(f"no path from {origin} to {destination}")
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
