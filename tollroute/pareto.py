"""Pareto sweep over value-of-time (Phase 4a).

For a fixed origin/destination/vehicle class, sweeps VoT logarithmically from
EUR 1/h to EUR 100/h in 10 steps, re-running Dijkstra at each step against the
generalised cost `G = toll + km*running_cost_per_km + hours*VoT`
(`tollroute/cost.py`). The edge sparsity pattern (row/col indices) is built
once; only the `data` array changes per step, via one vectorised numpy
expression, so all 10 runs over the ~1,900-node overlay graph are
single-digit milliseconds (spec: "same sparsity pattern per step, one
vectorised numpy expression, re-run Dijkstra"). Exit criterion: for a test
pair, the swept routes shift from zero-toll toward motorway as VoT rises.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from tollroute import routing
from tollroute.cost import ClassConfig, generalised_cost
from tollroute.graph import Edge, EdgeType, Graph, Node

DEFAULT_VOT_MIN_EUR_PER_HOUR = 1.0
DEFAULT_VOT_MAX_EUR_PER_HOUR = 100.0
DEFAULT_VOT_STEPS = 10


@dataclass
class GeneralisedRoute:
    vot_eur_per_hour: float
    route: routing.Route
    generalised_cost_eur: float


def vot_sweep_values(
    vot_min: float = DEFAULT_VOT_MIN_EUR_PER_HOUR,
    vot_max: float = DEFAULT_VOT_MAX_EUR_PER_HOUR,
    steps: int = DEFAULT_VOT_STEPS,
) -> np.ndarray:
    """Logarithmic VoT steps from `vot_min` to `vot_max` EUR/h (spec: "log
    VoT from 1 to 100 EUR/h, 10 steps").
    """
    return np.logspace(np.log10(vot_min), np.log10(vot_max), steps)


def _build_cost_components(
    graph: Graph, vehicle_class: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[tuple[int, int], Edge]]:
    """The sparsity pattern (row/col indices) plus the per-edge toll/km/hour
    components needed to compute `G` at any VoT without rebuilding the edge
    list - only the `data` array changes per Pareto step.

    Mirrors `routing._build_sparse`'s (i, j) uniqueness handling: node-index
    pairs are unique per Edge by construction (graph.py's four-role node
    split), so "keep last seen" on a colliding key is a defensive fallback,
    not a path this graph is expected to exercise.
    """
    edge_lookup: dict[tuple[int, int], Edge] = {}
    for edge in graph.edges:
        i = graph.node_index[edge.from_node]
        j = graph.node_index[edge.to_node]
        edge_lookup[(i, j)] = edge

    m = len(edge_lookup)
    rows = np.empty(m, dtype=np.int64)
    cols = np.empty(m, dtype=np.int64)
    toll_arr = np.zeros(m, dtype=np.float64)
    km_arr = np.empty(m, dtype=np.float64)
    hr_arr = np.empty(m, dtype=np.float64)

    for idx, ((i, j), edge) in enumerate(edge_lookup.items()):
        rows[idx] = i
        cols[idx] = j
        km_arr[idx] = edge.distance_m / 1000.0
        hr_arr[idx] = edge.duration_s / 3600.0
        if edge.edge_type == EdgeType.TOLL:
            toll_arr[idx] = edge.toll_eur[vehicle_class]

    return rows, cols, toll_arr, km_arr, hr_arr, edge_lookup


def pareto_sweep(
    graph: Graph,
    origin: Node,
    destination: Node,
    vehicle_class: int,
    class_config: dict[int, ClassConfig],
    vot_min: float = DEFAULT_VOT_MIN_EUR_PER_HOUR,
    vot_max: float = DEFAULT_VOT_MAX_EUR_PER_HOUR,
    steps: int = DEFAULT_VOT_STEPS,
) -> list[GeneralisedRoute]:
    """Re-runs Dijkstra once per VoT step against the generalised cost `G`,
    reusing the same sparsity pattern throughout - only the `data` array
    changes, via one vectorised numpy expression per step.
    """
    if vehicle_class not in class_config:
        raise ValueError(f"no class_config entry for vehicle_class {vehicle_class}")
    cfg = class_config[vehicle_class]

    origin_idx = graph.node_index[origin]
    dest_idx = graph.node_index[destination]
    n = len(graph.nodes)

    rows, cols, toll_arr, km_arr, hr_arr, edge_lookup = _build_cost_components(graph, vehicle_class)

    results: list[GeneralisedRoute] = []
    for vot in vot_sweep_values(vot_min, vot_max, steps):
        vot = float(vot)
        if origin_idx == dest_idx:
            route = routing.Route(
                nodes=[origin], edges=[], toll_eur=0.0, duration_s=0.0, distance_m=0.0
            )
        else:
            data = toll_arr + km_arr * cfg.running_cost_per_km + hr_arr * vot
            matrix = csr_matrix((data, (rows, cols)), shape=(n, n))
            _dist, predecessors = dijkstra(
                matrix, directed=True, indices=origin_idx, return_predecessors=True
            )
            route = routing.route_from_predecessors(
                graph, edge_lookup, predecessors, origin, origin_idx, dest_idx, vehicle_class
            )

        g = generalised_cost(
            route.toll_eur, route.distance_m, route.duration_s, cfg.running_cost_per_km, vot
        )
        results.append(GeneralisedRoute(vot_eur_per_hour=vot, route=route, generalised_cost_eur=g))

    return results
