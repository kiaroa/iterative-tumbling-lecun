# Phase 5b-follow-up-2: Millau viaduct (CEVM) — findings and honest result

## Scope

Add the Millau viaduct (A75, operated by CEVM — Compagnie Eiffage du Viaduc de Millau) to
`freeflow_override` as a single-structure concession, since it sits on a corridor this
project already treats as untolled (Phase 1b/1d/5b) but isn't one of the 13 dataset
operators and so never appears in `gare_master.csv`/`od_pairs.csv`.

## Fee sourcing

- **Class 1: €11.30**, 2026 off-peak/"normale" rate. Corroborated by two independent reads:
  Phase 5b's original plausibility report (citing the operator's own published tariff PDF)
  and this item's own web search of a third-party summary quoting the same figure. **Not**
  flagged `is_conjecture`.
- **Classes 2–5**: could not be corroborated directly. `leviaducdemillau.com`'s tariff
  PDF/page returns HTTP 403 in this build environment (the same access pattern Phase 2a/5a
  already hit against autoroutes.fr/vinci-autoroutes.com), and two independent third-party
  summaries quoted mutually inconsistent full-class grids that reconcile with neither each
  other nor the corroborated class-1 figure. Instead interpolated from APRR's own verified
  (Phase 5a fare-oracle-checked, exact-to-the-cent) class-N/class-1 price ratios applied to
  the sourced class-1 figure, flagged `is_conjecture=1` — the same convention
  `cost.seed_class_config` already uses for its own indicative figures.

## Attempt 1 (reverted): two synthetic gates joined by a priced edge

The first implementation modelled Millau as two synthetic gates ~13 km apart (guessed
"interchange" coordinates at the north/south approaches) joined by a priced `TOLL` edge in
both directions, reasoning the crossing needed "real endpoints" unlike A14's single-gantry
self-loop pattern.

Two problems, both direct-verified rather than assumed:

1. **Sibling-duplicate bug (real, and fixed before reverting):** the generic
   structure-to-structure connectivity pass gave each structure gate a free `TOLL_FREE` edge
   to *every* other gate in the graph, including its own sibling end — an exact-cost
   duplicate of the priced `TOLL` edge for the same OD pair, which would always dominate it.
   Fixed by excluding a structure's sibling gate from its own connectivity pass.
2. **Guessed coordinates were off the actual viaduct (found after the fix, and the reason
   this attempt was abandoned):** the two guessed "interchange" coordinates turned out not to
   sit on the motorway span itself — a direct OSRM route between them cut through Millau's
   town streets, never touching the viaduct in either toll mode. The "fastest"
   Clermont-Ferrand→Montpellier route used the synthetic gate purely as a same-cost
   pass-through waypoint via ordinary access edges, never the priced edge.

An investigation into *why* `exclude=toll` didn't separate the two coordinates onto different
routes led to a claim — recorded in this report's first version — that this build's OSM
extract simply doesn't tag the viaduct `toll=yes` at all. **That claim was itself never
checked against the viaduct's actual OSM way, only inferred from the guessed coordinates'
routing behaviour, and turned out to be wrong** (see "Revised design" below). The real problem
with attempt 1 was the coordinates, not OSRM's tagging.

## Attempt 2 (shipped): one real self-loop gate at the verified barrier coordinate

Checked directly against the live OSM extract this build's OSRM instance is served from
(`osrm/data/france.osm.pbf`): the viaduct's own ways (e.g. way 4296812, "Viaduc de Millau")
**are** tagged `toll=yes`, and the real barrier sits at two `barrier=toll_booth` nodes (OSM
nodes 2032423306/2032423307, one per carriageway) at ~(44.13414, 3.02556). A direct OSRM
query confirms this coordinate is a genuine mandatory chokepoint: `/route` with
`exclude=toll` returns `NoRoute` both from Clermont-Ferrand to it and from it to Montpellier —
exactly the semantics `tollroute.graph.build_graph`'s existing A14-style self-loop handling
already relies on for a real single-gantry gate (A14's 5 dataset self-loop fares, e.g. gate
547 "PEAGE DE MONTESSON").

`tollroute.etl.freeflow.seed_millau_override` seeds Millau as one ordinary self-loop
gate/fares row at this real barrier coordinate — the same shape as A14's rows — so
`build_graph`'s existing self-loop handling (`graph.py:360-384`) wires it up with **no new
graph.py code at all**: a zero-distance/zero-duration `TOLL` edge `OUT(900001) →
IN_TOLL(900001)` carrying the sourced/interpolated fees. `tollroute.etl.access_anchors.run()`
was re-run after seeding (required per that module's own docstring, since the gate's own
coordinate is `exclude=toll`-unreachable) and found both a 45.2 m entry anchor and a 468 m
exit anchor for gate 900001, so it participates in `add_access_edges` like any other
anchored gate.

## New finding this iteration: the self-loop edge is Pareto-dominated when a gate has no
## real neighbours in `fares`

Re-recording the golden fixture against this design still shows Clermont-Ferrand→Montpellier's
`fastest` option as toll-free (`toll_eur: 0.0`, gate chain `[900001]`) — the flagship
acceptance criterion is **still not met**, for a third, different, and more fundamental reason
than either of the first two investigations found.

Direct-traced against the live built graph (not inferred): gate 900001's three relevant edges
are

```
IN(900001)      -> OUT(900001)      DWELL  180.0 s / 500.0 m   (free)
OUT(900001)     -> IN_TOLL(900001)  TOLL     0.0 s /   0.0 m   (priced: 11.30 EUR class 1)
IN_TOLL(900001) -> OUT_TOLL(900001) DWELL  180.0 s / 500.0 m   (free)
```

`add_access_edges` connects an arbitrary origin to `IN(gid)` and an arbitrary destination from
*both* `OUT(gid)` and `OUT_TOLL(gid)` for every gate, not just gates reached via a real `fares`
row from another gate. For a self-loop-only gate (checked: neither Millau's 900001 nor A14's
547/205 appear as `from_gare_id`/`to_gare_id` in any *other* `fares` row), that means a route
can always reach `OUT(gid)` via the free `IN → OUT` dwell and exit straight to the destination
from there — paying nothing and taking 180 s / 500 m less than the alternative that continues
`OUT → IN_TOLL → (pay) → OUT_TOLL → destination`. The toll-paying path costs strictly more
money **and** strictly more time for the same destination access leg, so it is Pareto-dominated
and can never be selected by any of this service's three route objectives (`fastest`,
`cheapest`, `best_value`) — not a tuning or threshold issue, a structural one.

This is not Millau-specific: it applies to *any* self-loop gate that has no other `fares` row
connecting it to a different real gate, which today includes A14's own dataset gates 547 and
205. It has gone unnoticed until now because no existing golden/plausibility route happens to
pass near Montesson or Poissy — Millau is simply the first case this project has actually
tried to route a fastest/cheapest search through end-to-end.

**Fixed, same iteration, as Phase 5b-follow-up-2-continued**: `Graph` gained a
`freeflow_selfloop_gate_ids` set (populated in `build_graph` whenever a self-loop `TOLL` edge
is added), and `add_access_edges` now grants a gate in that set only its `OUT_TOLL` exit
access edge, withholding the plain `OUT` one — closing exactly the escape hatch described
above, without touching any *other* gate's `OUT` semantics (an ordinary two-endpoint gate's
`OUT` access edge is a genuine physical bypass lane, not the unpaid near side of the same
point the toll is charged at, so it's left untouched). A second, independent bug had to be
fixed alongside it: `api.py`'s per-request `_graph_copy` didn't carry the new field over
(the same class of bug as Phase 5b-follow-up-1's `access_anchors` omission), so the fix passed
its own direct unit test yet never fired through the real `/route` endpoint until the golden
fixtures were re-recorded and still showed `toll_eur: 0.0` — caught and fixed, plus a new
generic regression test (`tests/test_api.py::test_graph_copy_preserves_every_graph_dataclass_field`,
iterating `dataclasses.fields` so it doesn't need hand-updating for the next field either).
Re-recording the golden fixture confirms the flagship criterion is now genuinely met:
Clermont-Ferrand→Montpellier's `fastest` option is `toll_eur: 11.3`, gate chain `[900001]`,
duration 14766.4 s / distance 341118.2 m (the `cheapest` and `best_value` options correctly
route around Millau instead, at `toll_eur: 0.0` via gates 555/654, exactly the tradeoff a
toll-minimiser should offer).

## What shipped and is verified

- `freeflow_override` schema extended (`operator`, `structure_a/b_lat/lon`, `is_conjecture`
  columns — the `structure_a/b_lat/lon` columns are unused by the shipped self-loop design but
  left in place rather than churned again, in case a future structure genuinely needs a
  two-endpoint model) and the national DB rebuilt against it (`CREATE TABLE IF NOT EXISTS`
  doesn't retrofit an already-existing table, so this required a full rebuild via
  `python3 -m tollroute.etl.build_national`, the project's own documented way to apply a
  schema change).
- `tollroute.etl.freeflow.seed_millau_override` idempotently seeds the gate/fares/
  `freeflow_override` rows (`tests/test_freeflow.py`, 2 tests, offline).
- `build_graph`'s pre-existing A14 self-loop mechanism wires the priced edge correctly, with
  no new graph.py code — regression-tested directly
  (`tests/test_graph.py::test_millau_seed_becomes_priced_selfloop_edge_via_existing_a14_mechanism`,
  offline, alongside the pre-existing A14-pattern test it's modelled on).
- `access_anchors.run()` re-run against the rebuilt DB; gate 900001 has both a working entry
  and exit anchor.
- All 10 Phase 5c golden fixtures re-recorded (the new gate is now visible to
  `add_access_edges`'s entry/exit gid collection for every route, not just Millau's own).
- `tests/test_build_national.py`'s ground-truth fare count updated (+1, for the one new
  self-loop fares row — the only other test in the suite affected by this seed).

**Test outcome:** `python3 -m pytest` — 194 passed, 3 skipped, 7 xfailed. (The previously-noted
`tests/test_snap_report.py` failure from Phase 5c-follow-up was re-checked this iteration and
found to be flaky rather than deterministic — it fails or passes on different runs against the
same live OSRM instance with no code change in between; still filed and still unrelated to this
item, not fixed here.)
