"""Shape the Phase 4a Pareto sweep into a labelled, guard-railed response (Phase 4b).

For a fixed (origin, destination, vehicle_class) the 10-step VoT sweep
(`tollroute/pareto.py`) is deduplicated to a frontier of distinct routes (by
gate chain). Three routes are always labelled:

- ``fastest`` — the true duration-minimal route (`tollroute.routing.find_route`,
  independent of the generalised-cost sweep, so it matches the CLI/Phase 1d
  API exactly rather than whatever the 10 discrete VoT steps happen to find).
- ``cheapest`` — the minimum-toll route among the swept frontier.
- ``best_value`` — the frontier route (or, if none of the 10 sweep steps land
  exactly on it, a fresh single-VoT sweep) minimising generalised cost at
  ``vot_threshold`` (default: the vehicle class's configured VoT).

Any other frontier route is offered as an unlabelled surviving Pareto point
only if it passes two guard rails applied to the frontier, not the search:
``max_gate_hops`` and a minimum-detour floor, then a "worthwhile" filter
(implied EUR/hour saved vs `vot_threshold`).

**Judgement calls, flagged (per IMPLEMENTATION_PLAN.md's Phase 1d-follow-up
part (b) and Phase 4b item):**

- The spec's literal "extra >=10 km AND >=5 min" guard rail was found (Phase
  1d) to reject every real toll-free alternative on a motorway-vs-parallel-
  N-road pair, because such alternatives are reliably slower but never
  longer. Reinterpreted here as OR (``extra_km >= 10`` or ``extra_minutes >=
  5``): either leg alone is enough evidence the route is a meaningfully
  different, non-noise alternative.
- ``max_gate_hops`` counts TOLL edges traversed (successive priced
  gate-to-gate legs) rather than every dwell/access hop, since chained toll
  legs are what could realistically explode combinatorially across many
  concessions.
- ``match_tier``/``match_agreement`` are reported per gate (``gate_detail``),
  not collapsed to one worst-case value per option: `gare_master.csv` (the
  prior geocoding pipeline's output, reused verbatim per the plan's Phase 4b
  note) does not document an authoritative ordering across its A-F/O tiers
  or corroborated/single_source/override/conflicted agreement classes, so
  inventing a "worst of the chain" ranking would be an unverified guess.
- The cache key spec names ``snapped_entry_gate_id``/``snapped_exit_gate_id``,
  which presumes a per-request nearest-gate resolution step that does not
  exist yet (that is Phase 4c's job — `add_access_edges` connects the origin/
  destination to every candidate gate and lets Dijkstra choose, rather than
  fixing a single entry/exit gate up front). `tollroute/api.py` therefore
  keys its cache on the resolved origin/destination instead; see that
  module's docstring for the full reasoning.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

from tollroute.cost import ClassConfig, generalised_cost
from tollroute.graph import EdgeType, Graph, Node
from tollroute.pareto import build_csr_reuse_plan, pareto_sweep
from tollroute.routing import Route, build_edge_arrays, find_route

MAX_GATE_HOPS = 5
MIN_DETOUR_KM = 10.0
MIN_DETOUR_MINUTES = 5.0


def gate_chain(route: Route) -> list[int]:
    chain: list[int] = []
    for node in route.nodes:
        if node.gare_id < 0:
            continue  # synthetic origin/destination access node
        if not chain or chain[-1] != node.gare_id:
            chain.append(node.gare_id)
    return chain


def toll_gate_hops(route: Route) -> int:
    """Number of priced gate-to-gate legs traversed (see module docstring's
    max_gate_hops judgement call)."""
    return sum(1 for e in route.edges if e.edge_type == EdgeType.TOLL)


def same_operator_split(route: Route) -> bool:
    """True when the route's toll edges chain the same operator twice - only
    reachable via a genuine toll-free detour, never the forbidden dwell
    connector (graph.py's four-role node split makes toll -> dwell -> toll
    unrepresentable), per the spec's Core architectural decision."""
    counts: dict[str, int] = {}
    for e in route.edges:
        if e.edge_type == EdgeType.TOLL and e.operator:
            counts[e.operator] = counts.get(e.operator, 0) + 1
    return any(c >= 2 for c in counts.values())


def gate_match_detail(conn: sqlite3.Connection, gare_ids: list[int]) -> list[dict]:
    """Per-gate match_tier/match_agreement, passed through verbatim from the
    `gates` table (sourced from gare_master.csv's prior geocoding pipeline -
    see module docstring for why this is not aggregated to one value)."""
    if not gare_ids:
        return []
    placeholders = ",".join("?" for _ in gare_ids)
    rows = conn.execute(
        f"SELECT gare_id, match_tier, match_agreement, canonical_name, all_routes FROM gates WHERE gare_id IN ({placeholders})",
        gare_ids,
    ).fetchall()
    by_id = {gid: (tier, agreement, name, routes) for gid, tier, agreement, name, routes in rows}
    return [
        {
            "gare_id": gid,
            "name": by_id.get(gid, (None, None, None, None))[2],
            "routes": by_id.get(gid, (None, None, None, None))[3],
            "match_tier": by_id.get(gid, (None, None, None, None))[0],
            "match_agreement": by_id.get(gid, (None, None, None, None))[1],
        }
        for gid in gare_ids
    ]


def dedupe_by_gate_chain(routes: list[Route]) -> list[Route]:
    seen: set[tuple[int, ...]] = set()
    unique: list[Route] = []
    for route in routes:
        key = tuple(gate_chain(route))
        if key in seen:
            continue
        seen.add(key)
        unique.append(route)
    return unique


def _detour_metrics(route: Route, fastest: Route) -> tuple[float, float, float, float | None]:
    extra_km = (route.distance_m - fastest.distance_m) / 1000.0
    extra_minutes = (route.duration_s - fastest.duration_s) / 60.0
    saving_vs_fastest_eur = fastest.toll_eur - route.toll_eur
    if extra_minutes > 1e-9:
        eur_per_hour_saved = saving_vs_fastest_eur / (extra_minutes / 60.0)
    elif saving_vs_fastest_eur > 0:
        eur_per_hour_saved = math.inf
    else:
        eur_per_hour_saved = None
    return extra_km, extra_minutes, saving_vs_fastest_eur, eur_per_hour_saved


def _meets_detour_floor(extra_km: float, extra_minutes: float) -> bool:
    return extra_km >= MIN_DETOUR_KM or extra_minutes >= MIN_DETOUR_MINUTES


def _is_worthwhile(eur_per_hour_saved: float | None, vot_threshold: float) -> bool:
    if eur_per_hour_saved is None:
        return False
    return eur_per_hour_saved >= vot_threshold


@dataclass(frozen=True)
class RouteOption:
    labels: tuple[str, ...]
    toll_eur: float
    duration_s: float
    distance_m: float
    gates: tuple[int, ...]
    saving_vs_fastest_eur: float
    extra_minutes: float
    extra_km: float
    eur_per_hour_saved: float | None
    same_operator_split: bool
    gate_detail: tuple[dict, ...]
    toll_segments: tuple[float, ...] = ()
    toll_gates_detail: tuple[dict, ...] = ()
    toll_leg_indices: tuple[int, ...] = ()
    # Gate IDs that are endpoints of TOLL edges only (subset of `gates`).
    # Used by api.py to build geometry waypoints: gates visited only via
    # TOLL_FREE edges are on N-roads, not motorway toll booths, so using their
    # coordinates as OSRM waypoints would route the motorway between them and
    # show unpriced toll sections on the map.
    priced_gates: tuple[int, ...] = ()

    def as_dict(self) -> dict:
        return {
            "labels": list(self.labels),
            "toll_eur": self.toll_eur,
            "duration_s": self.duration_s,
            "distance_m": self.distance_m,
            "gates": list(self.gates),
            "priced_gates": list(self.priced_gates),
            "saving_vs_fastest_eur": self.saving_vs_fastest_eur,
            "extra_minutes": self.extra_minutes,
            "extra_km": self.extra_km,
            "eur_per_hour_saved": self.eur_per_hour_saved,
            "same_operator_split": self.same_operator_split,
            "gate_detail": list(self.gate_detail),
            "toll_segments": list(self.toll_segments),
            "toll_gates_detail": list(self.toll_gates_detail),
            "toll_leg_indices": list(self.toll_leg_indices),
        }


def _build_option(
    route: Route, fastest: Route, labels: set[str], conn: sqlite3.Connection, vehicle_class: int
) -> RouteOption:
    chain = gate_chain(route)
    extra_km, extra_minutes, saving, eur_per_hour_saved = _detour_metrics(route, fastest)
    toll_segments = tuple(
        e.toll_eur.get(vehicle_class, 0) for e in route.edges
        if e.toll_eur is not None and isinstance(e.toll_eur, dict) and e.toll_eur.get(vehicle_class, 0) > 0
    )

    gate_details = gate_match_detail(conn, chain)
    gate_detail_by_id = {g["gare_id"]: g for g in gate_details}

    toll_gates_detail = []
    toll_leg_indices_list: list[int] = []
    chain_pos = 0  # tracks position in gate chain as we walk edges

    for edge in route.edges:
        if edge.toll_eur is None or not isinstance(edge.toll_eur, dict):
            continue
        cost = edge.toll_eur.get(vehicle_class, 0)
        if cost <= 0:
            continue
        from_id = edge.from_node.gare_id
        to_id = edge.to_node.gare_id
        from_g = gate_detail_by_id.get(from_id, {})
        to_g = gate_detail_by_id.get(to_id, {})
        roads = "|".join(filter(None, [from_g.get("routes", ""), to_g.get("routes", "")]))
        toll_gates_detail.append({
            "from_gare_id": from_id,
            "to_gare_id": to_id,
            "from_name": from_g.get("name", f"Gate {from_id}"),
            "to_name": to_g.get("name", f"Gate {to_id}"),
            "routes": roads,
            "toll_eur": cost,
        })
        # Find to_id in chain starting from current position; leg k reaches chain[k]
        for k in range(chain_pos, len(chain)):
            if chain[k] == to_id:
                toll_leg_indices_list.append(k)
                chain_pos = k + 1
                break

    # Derive priced_gates: ordered unique gate IDs that are TOLL-edge endpoints.
    # Excludes gates visited only via TOLL_FREE edges (N-road routing), which
    # must not be used as geometry waypoints (see RouteOption.priced_gates docstring).
    priced_gate_ids_seen: set[int] = set()
    priced_gate_ids: list[int] = []
    for tg in toll_gates_detail:
        for gid in (tg["from_gare_id"], tg["to_gare_id"]):
            if gid not in priced_gate_ids_seen:
                priced_gate_ids.append(gid)
                priced_gate_ids_seen.add(gid)

    return RouteOption(
        labels=tuple(sorted(labels)),
        toll_eur=route.toll_eur,
        duration_s=route.duration_s,
        distance_m=route.distance_m,
        gates=tuple(chain),
        priced_gates=tuple(priced_gate_ids),
        saving_vs_fastest_eur=saving,
        extra_minutes=extra_minutes,
        extra_km=extra_km,
        eur_per_hour_saved=eur_per_hour_saved,
        same_operator_split=same_operator_split(route),
        gate_detail=tuple(gate_details),
        toll_segments=toll_segments,
        toll_gates_detail=tuple(toll_gates_detail),
        toll_leg_indices=tuple(toll_leg_indices_list),
    )


_LABEL_PRIORITY = {"fastest": 0, "cheapest": 1, "toll_optimised": 2, "best_value": 2, "toll_free_route": 3}


def shape_response(
    graph: Graph,
    origin: Node,
    destination: Node,
    vehicle_class: int,
    class_config: dict[int, ClassConfig],
    conn: sqlite3.Connection,
    vot_threshold: float | None = None,
) -> dict:
    """Build the full Phase 4b response: labelled options, guard rails, worthwhile filter.

    `vot_threshold` is the per-request override for `best_value` selection
    and the "worthwhile" filter; defaults to the vehicle class's configured
    `value_of_time_eur_per_hour` (Phase 4a's `class_config`) when omitted,
    per spec ("config-table default VoT threshold per class, overridable per
    request").
    """
    if vehicle_class not in class_config:
        raise ValueError(f"no class_config entry for vehicle_class {vehicle_class}")
    cfg = class_config[vehicle_class]
    vot = vot_threshold if vot_threshold is not None else cfg.value_of_time_eur_per_hour

    # Built once and reused for the fastest search plus both sweeps below
    # (Phase 4c-follow-up): each independently rebuilding this ~900k-edge
    # sparsity pattern/cost-component structure - not the Dijkstra runs
    # themselves - was measured as the dominant cost of a national warm
    # `/route` response.
    edge_arrays = build_edge_arrays(graph, vehicle_class)

    # Likewise built once and reused for both pareto_sweep calls below
    # (Phase 4c-follow-up-5): both sweeps share edge_arrays' `(rows, cols)`
    # and the same node count, so they'd otherwise each rebuild an identical
    # CSR reuse plan for no reason.
    reuse_plan = build_csr_reuse_plan(edge_arrays.rows, edge_arrays.cols, len(graph.nodes))

    fastest_route = find_route(graph, origin, destination, vehicle_class, edge_arrays=edge_arrays)

    swept = [
        r.route
        for r in pareto_sweep(
            graph, origin, destination, vehicle_class, class_config,
            edge_arrays=edge_arrays, reuse_plan=reuse_plan,
        )
    ]
    frontier = dedupe_by_gate_chain(swept)

    # Partition: routes with a positive toll price vs €0 alternatives.
    # "cheapest" always means the minimum *positive* toll cost route; €0 routes
    # (all TOLL_FREE edges, genuine N-road alternatives) are offered separately
    # as "toll_free_route" subject to the normal detour guard rail. Without this
    # split, a toll-free N-road alternative wins the "cheapest" label and its
    # gate coordinates (which lie on the motorway) are used as OSRM waypoints,
    # producing a displayed route on the motorway with €0 price — a mismatch
    # that suggests the motorway is free when it isn't.
    priced_frontier = [r for r in frontier if r.toll_eur > 0]
    tollfree_frontier = [r for r in frontier if r.toll_eur == 0]

    cheapest_route = min(priced_frontier, key=lambda r: r.toll_eur) if priced_frontier else None

    best_value_route = min(
        pareto_sweep(
            graph, origin, destination, vehicle_class, class_config,
            vot_min=vot, vot_max=vot, steps=1, edge_arrays=edge_arrays, reuse_plan=reuse_plan,
        ),
        key=lambda r: generalised_cost(
            r.route.toll_eur, r.route.distance_m, r.route.duration_s, cfg.running_cost_per_km, vot
        ),
    ).route

    labels_by_key: dict[tuple[int, ...], set[str]] = {}
    routes_by_key: dict[tuple[int, ...], Route] = {}

    def register(route: Route, label: str | None) -> None:
        key = tuple(gate_chain(route))
        routes_by_key.setdefault(key, route)
        labels_by_key.setdefault(key, set())
        if label:
            labels_by_key[key].add(label)

    register(fastest_route, "fastest")
    # toll_optimised: the route minimising generalised cost at the user's VoT.
    # Also label it "cheapest" if it has the lowest raw (positive) toll cost on
    # the priced frontier.
    register(best_value_route, "toll_optimised")
    if cheapest_route is not None:
        if tuple(gate_chain(cheapest_route)) == tuple(gate_chain(best_value_route)):
            labels_by_key[tuple(gate_chain(cheapest_route))].add("cheapest")
        else:
            # cheapest and toll_optimised diverge; keep cheapest only if it's
            # meaningfully different from both fastest and toll_optimised.
            cheapest_key = tuple(gate_chain(cheapest_route))
            if cheapest_key != tuple(gate_chain(fastest_route)):
                register(cheapest_route, "cheapest")

    # Genuinely toll-free routes (all TOLL_FREE edges, €0): offer with a
    # descriptive label subject to the normal detour guard rail. They are only
    # useful to show when they represent a meaningfully different routing choice
    # (e.g. a scenic N-road alternative, not marginal noise).
    for tf_route in tollfree_frontier:
        tf_key = tuple(gate_chain(tf_route))
        if tf_key in routes_by_key:
            continue  # already registered as fastest or toll_optimised
        extra_km, extra_minutes, _, _ = _detour_metrics(tf_route, fastest_route)
        if _meets_detour_floor(extra_km, extra_minutes):
            register(tf_route, "toll_free_route")

    # Unlabelled Pareto points are dropped — they are intermediate options
    # whose access-leg geometry often doesn't match Dijkstra's toll-free
    # routing assumptions, producing misleading displayed prices.

    options = [
        _build_option(route, fastest_route, labels_by_key[key], conn, vehicle_class)
        for key, route in routes_by_key.items()
    ]
    options.sort(
        key=lambda o: (
            min((_LABEL_PRIORITY.get(label, 3) for label in o.labels), default=3),
            o.toll_eur,
            o.duration_s,
        )
    )

    return {
        "vehicle_class": vehicle_class,
        "vot_eur_per_hour": vot,
        "options": [o.as_dict() for o in options],
    }
