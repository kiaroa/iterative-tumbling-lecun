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
from tollroute.pareto import pareto_sweep
from tollroute.routing import Route, find_route

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
        f"SELECT gare_id, match_tier, match_agreement FROM gates WHERE gare_id IN ({placeholders})",
        gare_ids,
    ).fetchall()
    by_id = {gid: (tier, agreement) for gid, tier, agreement in rows}
    return [
        {
            "gare_id": gid,
            "match_tier": by_id.get(gid, (None, None))[0],
            "match_agreement": by_id.get(gid, (None, None))[1],
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

    def as_dict(self) -> dict:
        return {
            "labels": list(self.labels),
            "toll_eur": self.toll_eur,
            "duration_s": self.duration_s,
            "distance_m": self.distance_m,
            "gates": list(self.gates),
            "saving_vs_fastest_eur": self.saving_vs_fastest_eur,
            "extra_minutes": self.extra_minutes,
            "extra_km": self.extra_km,
            "eur_per_hour_saved": self.eur_per_hour_saved,
            "same_operator_split": self.same_operator_split,
            "gate_detail": list(self.gate_detail),
        }


def _build_option(
    route: Route, fastest: Route, labels: set[str], conn: sqlite3.Connection
) -> RouteOption:
    chain = gate_chain(route)
    extra_km, extra_minutes, saving, eur_per_hour_saved = _detour_metrics(route, fastest)
    return RouteOption(
        labels=tuple(sorted(labels)),
        toll_eur=route.toll_eur,
        duration_s=route.duration_s,
        distance_m=route.distance_m,
        gates=tuple(chain),
        saving_vs_fastest_eur=saving,
        extra_minutes=extra_minutes,
        extra_km=extra_km,
        eur_per_hour_saved=eur_per_hour_saved,
        same_operator_split=same_operator_split(route),
        gate_detail=tuple(gate_match_detail(conn, chain)),
    )


_LABEL_PRIORITY = {"fastest": 0, "cheapest": 1, "best_value": 2}


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

    fastest_route = find_route(graph, origin, destination, vehicle_class)

    swept = [r.route for r in pareto_sweep(graph, origin, destination, vehicle_class, class_config)]
    frontier = dedupe_by_gate_chain(swept)

    cheapest_route = min(frontier, key=lambda r: r.toll_eur)

    best_value_route = min(
        pareto_sweep(
            graph, origin, destination, vehicle_class, class_config,
            vot_min=vot, vot_max=vot, steps=1,
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
    register(cheapest_route, "cheapest")
    register(best_value_route, "best_value")

    for route in frontier:
        key = tuple(gate_chain(route))
        if key in labels_by_key:
            continue
        if toll_gate_hops(route) > MAX_GATE_HOPS:
            continue
        extra_km, extra_minutes, _saving, eur_per_hour_saved = _detour_metrics(route, fastest_route)
        if not _meets_detour_floor(extra_km, extra_minutes):
            continue
        if not _is_worthwhile(eur_per_hour_saved, vot):
            continue
        register(route, None)

    options = [
        _build_option(route, fastest_route, labels_by_key[key], conn)
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
