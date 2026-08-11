"""Pareto sweep over value-of-time (Phase 4a).

For a fixed origin/destination/vehicle class, sweeps VoT logarithmically from
EUR 1/h to EUR 100/h in 10 steps, re-running Dijkstra at each step against the
generalised cost `G = toll + km*running_cost_per_km + hours*VoT`
(`tollroute/cost.py`). The edge sparsity pattern (row/col indices) is built
once per `pareto_sweep` call (`routing.build_edge_arrays`, optionally passed
in via `edge_arrays` so a caller like `response.shape_response` running
several sweeps/searches against the same graph/vehicle_class builds it only
once overall); only the `data` array changes per step, via one vectorised
numpy expression (spec: "same sparsity pattern per step, one vectorised numpy
expression, re-run Dijkstra"). Exit criterion: for a test pair, the swept
routes shift from zero-toll toward motorway as VoT rises.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from tollroute import routing
from tollroute.cost import ClassConfig, generalised_cost
from tollroute.graph import Graph, Node
from tollroute.routing import EdgeArrays

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


def pareto_sweep(
    graph: Graph,
    origin: Node,
    destination: Node,
    vehicle_class: int,
    class_config: dict[int, ClassConfig],
    vot_min: float = DEFAULT_VOT_MIN_EUR_PER_HOUR,
    vot_max: float = DEFAULT_VOT_MAX_EUR_PER_HOUR,
    steps: int = DEFAULT_VOT_STEPS,
    edge_arrays: EdgeArrays | None = None,
) -> list[GeneralisedRoute]:
    """Re-runs Dijkstra once per VoT step against the generalised cost `G`,
    reusing the same sparsity pattern throughout - only the `data` array
    changes, via one vectorised numpy expression per step.

    `edge_arrays` lets a caller about to run several sweeps/searches against
    the same graph/vehicle_class (`response.shape_response`'s fastest +
    10-step sweep + best_value re-sweep) pass in an already-built
    `routing.EdgeArrays` rather than have this rebuild one; omit it for a
    one-off call, which builds it internally as before.
    """
    if vehicle_class not in class_config:
        raise ValueError(f"no class_config entry for vehicle_class {vehicle_class}")
    cfg = class_config[vehicle_class]

    origin_idx = graph.node_index[origin]
    dest_idx = graph.node_index[destination]
    n = len(graph.nodes)

    ea = edge_arrays if edge_arrays is not None else routing.build_edge_arrays(graph, vehicle_class)

    results: list[GeneralisedRoute] = []
    for vot in vot_sweep_values(vot_min, vot_max, steps):
        vot = float(vot)
        if origin_idx == dest_idx:
            route = routing.Route(
                nodes=[origin], edges=[], toll_eur=0.0, duration_s=0.0, distance_m=0.0
            )
        else:
            data = ea.toll_arr + ea.km_arr * cfg.running_cost_per_km + ea.hr_arr * vot
            matrix = csr_matrix((data, (ea.rows, ea.cols)), shape=(n, n))
            _dist, predecessors = dijkstra(
                matrix, directed=True, indices=origin_idx, return_predecessors=True
            )
            route = routing.route_from_predecessors(
                graph, ea.edge_lookup, predecessors, origin, origin_idx, dest_idx, vehicle_class
            )

        g = generalised_cost(
            route.toll_eur, route.distance_m, route.duration_s, cfg.running_cost_per_km, vot
        )
        results.append(GeneralisedRoute(vot_eur_per_hour=vot, route=route, generalised_cost_eur=g))

    return results
