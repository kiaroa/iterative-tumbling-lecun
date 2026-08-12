# Phase 5b-follow-up-1 — validation against the flagship acceptance criterion

`tollroute.etl.access_anchors` (see `reports/phase5b_followup1_access_anchors.md` for the
precompute run itself) finds a per-gate toll-free "access anchor" for gates whose own
coordinate is not directly `exclude=toll`-reachable, and wires it into `add_access_edges`
(`tollroute/graph.py`) so the origin/destination access legs query the anchor instead,
adding the anchor's short apron distance/duration back on top. This note validates that
mechanism against this item's own "done when" criterion: re-running
`analysis/phase5b_plausibility.py`'s 10 routes should show `fastest` duration materially
closer to `baseline` for Paris→Lyon and Paris→Bordeaux specifically.

## Result: the flagship criterion is not met

Comparing `fastest` vs `baseline` (same live API, before vs after the anchors were
precomputed and wired through), like-for-like:

| Route | dist gap before | dist gap after | dur gap before | dur gap after |
|---|---|---|---|---|
| Paris→Lyon | +4.0% | +2.1% | +15.5% | +14.8% |
| Paris→Bordeaux | +3.5% | +3.5% | +13.4% | +13.4% |

Neither route's duration gap closed materially. The entry gate chosen for each is
unchanged: Paris→Lyon still enters at Nemours (gate 585), not the nearer Fleury-en-Bière
(gates 302/303); Paris→Bordeaux is unaffected entirely (same gate chain, same numbers to
the decimal place).

## Why: Fleury-en-Bière's own coordinate has no anchor, and can't safely get one

Direct re-check against the live OSRM instance confirms gate 302/303's own coordinate is
still not `exclude=toll`-reachable from any of the 6 reference cities (consistent with
`tollroute.etl.access_anchors`'s own docstring). But `find_anchor` also returns `None` for
it: probing its 100 nearest toll-free-tagged `/nearest` candidates, every one that *is*
reachable has a plain (toll-allowed) apron leg of 22-30 km back to the gate; the handful of
candidates with a genuinely short apron (< 100 m) are themselves unreachable — i.e. also
inside the same isolated pocket, not a way out of it.

This corrects the access-anchors precompute script's own docstring, which claimed "several
of [Fleury's] ~20-90 m candidates have plain aprons under 1 km" — that claim conflated
"has a short apron" and "is toll-free-reachable" without checking both together for the
same candidate; direct re-verification here shows no candidate satisfies both. Fleury's
isolation is a genuine multi-kilometre regional gap in the toll-free network near the
barrier, not a last-mile pocket a bounded local search can safely patch: `find_anchor`'s
`APRON_REJECT_DISTANCE_M` (2 km) exists specifically to stop an anchor search from
accepting a multi-kilometre detour as if it were a short apron, because a multi-kilometre
apron would, in practice, ride the tolled motorway itself for most of its length — reopening
the exact Phase 1c free-ride bug `exclude=toll` was introduced to close. Raising that bound
to force an anchor for Fleury would do exactly that, so it wasn't raised.

## What did land

- **A real, verified integration bug fix.** `tollroute/api.py`'s per-request `_graph_copy`
  omitted the new `access_anchors` field entirely, so the live `/route` endpoint dropped
  every anchor found (silently falling back to unanchored behaviour) even though
  `tollroute.cli.run` and all three test-suite `_graph_copy` helpers correctly carried it.
  Caught by `tests/test_api.py::test_route_endpoint_fastest_option_matches_cli`
  (Dijon→Lyon toll mismatched: API returned €14.10, CLI/oracle €12.70) once the
  `access_anchors` table was actually populated — passes now that `api.py`'s copy carries
  the field like the others.
- **67 previously-fully-isolated gates now have a working access anchor** (out of 910
  snapped, non-quarantined gates checked; 256 needed one, 189 remain gapped exactly as
  before — see `reports/phase5b_followup1_access_anchors.md`). One of the 10 Phase 5b
  routes exercises an anchored gate directly: Paris→Lyon's exit gate, Belleville-sur-Saône
  (110), now resolves via a 400 m/31 s anchor apron instead of being a NoRoute gap.
- **No regression to the toll-accounting guarantee** `exclude=toll` exists for: every
  anchor found has an apron under the 2 km safety bound (min 91 m, median 537 m, max
  1990 m — see the precompute report), so no anchor can resurrect the Phase 1c free-ride
  bug. Full test suite: 187 passed, 1 failed (pre-existing, unrelated —
  `tests/test_snap_report.py`'s Phase 5c-follow-up), 3 skipped, 7 xfailed.
- **Golden fixtures re-recorded** (`analysis/record_golden_fixtures.py`) to reflect the
  now-anchored gates' legitimately-changed legs (all 10 fixtures changed once anchors
  were wired in, since `tollroute.api`'s access-edge calculation changed for every route,
  not just the two flagship ones).

## What's left

Fleury-en-Bière-class gates — a genuine multi-kilometre isolated pocket, not a last-mile
one — need a materially different technique than a bounded local-apron search to fix
safely. Filed as a new, more precisely-scoped follow-up (see `IMPLEMENTATION_PLAN.md`,
Phase 5b-follow-up-1-continued) rather than attempted here: candidate directions (relaxing
`exclude=toll` for a short fixed-radius buffer immediately around the gate itself, rather
than searching outward for a reachable point; or treating such a gate's entry as
genuinely requiring a few hundred metres of tolled tarmac, structurally different from
today's "anchor + apron" model) all need their own investigation before implementation,
which is out of scope for this item.
