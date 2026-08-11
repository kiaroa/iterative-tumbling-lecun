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

**Phase 4c-follow-up-4:** each step used to rebuild a fresh `csr_matrix` from
the `(rows, cols)` COO arrays, paying `coo_tocsr`/`sort_indices` (~0.15 s
across a request's ~6 constructions) even though only `data` changes between
steps. `_csr_reuse_plan` below builds the CSR `indices`/`indptr` once per
sweep, plus a `perm` array such that `data[perm]` is already in CSR data
order - letting every subsequent step skip straight to the cheap
`csr_matrix((data, indices, indptr))` constructor form. `perm` is only valid
when `(rows, cols)` has no duplicate pairs (duplicates get summed during COO
conversion, which would silently corrupt a plain permutation); this is
detected once via an `nnz` check, with a fall-back to the original per-step
COO rebuild if any duplicate is found, so a duplicate edge pair can never
change a result, only skip the optimisation.
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


@dataclass
class _CSRReusePlan:
    """Precomputed CSR sparsity pattern for a fixed `(rows, cols)` pair.

    `perm` reorders a COO-order `data` array into CSR data order in one
    fancy-index (`data[perm]`), so building the matrix for a new step is just
    `csr_matrix((data[perm], indices, indptr), shape=...)` - the cheap direct
    constructor, skipping `coo_tocsr`/`sort_indices` entirely.
    """

    indices: np.ndarray
    indptr: np.ndarray
    perm: np.ndarray


def _csr_reuse_plan(rows: np.ndarray, cols: np.ndarray, n: int) -> _CSRReusePlan | None:
    """Builds a `_CSRReusePlan` for `(rows, cols)`, or `None` if any
    duplicate `(row, col)` pair exists (COO->CSR sums duplicates at
    construction time, which would corrupt a plain permutation - detected by
    comparing the tagged matrix's `nnz` against `len(rows)`).
    """
    nnz = len(rows)
    tag = np.arange(nnz, dtype=np.int64)
    tagged = csr_matrix((tag, (rows, cols)), shape=(n, n))
    if tagged.nnz != nnz:
        return None
    return _CSRReusePlan(indices=tagged.indices, indptr=tagged.indptr, perm=tagged.data)

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
    reuse_plan = _csr_reuse_plan(ea.rows, ea.cols, n)

    results: list[GeneralisedRoute] = []
    for vot in vot_sweep_values(vot_min, vot_max, steps):
        vot = float(vot)
        if origin_idx == dest_idx:
            route = routing.Route(
                nodes=[origin], edges=[], toll_eur=0.0, duration_s=0.0, distance_m=0.0
            )
        else:
            data = ea.toll_arr + ea.km_arr * cfg.running_cost_per_km + ea.hr_arr * vot
            if reuse_plan is not None:
                matrix = csr_matrix(
                    (data[reuse_plan.perm], reuse_plan.indices, reuse_plan.indptr), shape=(n, n)
                )
            else:
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
