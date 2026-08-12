# Phase 5c-follow-up: A75 geo-only pair — root cause and fix

## Scope

`tests/test_snap_report.py::test_all_5_named_test_pairs_have_prices_and_distinct_routes`
was found failing (Phase 5c) for the Clermont-Ferrand -> Montpellier geo-only pair (A75, the
"free motorway" edge case with no APRR gate): a single run of
`snap_report.verify_geo_only_pair` returned a tolled route of 331,902.5 m / 13,336.0 s and an
`exclude=toll` route of 337,817.7 m / 14,148.3 s (+1.8% distance / +6.1% duration) — not the
"near-identical" result the test's own docstring documents as the expected shape of this edge
case. The plan speculated this was the same root cause as Phase 5b-follow-up-1
(`add_access_edges` excluding a motorway's genuine toll-free lead-in), since both involve
`exclude=toll` producing a worse-than-expected toll-free route.

**That speculation is wrong.** This is a different, narrower, and more fundamental problem:
`osrm-routed`'s MLD algorithm returns non-deterministic results for this specific corridor when
served with more than ~2 worker threads — independent of `tollroute`'s own graph/profile code
entirely, since this test calls raw OSRM `/route` with city-centre coordinates, never touching
`tollroute.graph`.

## Direct verification

Running `verify_geo_only_pair` 10x in a row against the live default OSRM container (`osrm-routed
--algorithm mld --threads 24`, the production default per `osrm/docker-compose.yml`), with no
code change or container restart between calls:

```
run  distinct  tolled_m   toll_free_m
0    False     337817.7   337817.7
1    True      331902.5   337817.7
2    False     331902.5   331902.5
3    True      331902.5   337817.7
4    True      331902.5   337817.7
5    False     331902.5   331902.5
6    False     337817.7   337817.7
7    False     331902.5   331902.5
8    False     337817.7   337817.7
9    True      331902.5   337817.7
```

Note the *tolled* (`exclude=toll` not set, all roads allowed) query itself flips between two
different results (331,902.5 m and 337,817.7 m) run to run — this rules out an `exclude=toll`
profile/tagging bug (Phase 5b-follow-up-1's mechanism) outright, since that query never excludes
anything. The two routes are a genuine near-tie that OSRM's MLD engine breaks inconsistently.

**Isolated to thread count**, by launching independent `osrm-routed` containers against the same
`.osrm` build (`osrm/data/france.osrm`, unmodified — mtimes confirmed unchanged) with only
`--threads` varied, then firing 15 identical queries at each:

| `--threads` | distinct (route, m) pairs seen across 15 runs |
|---|---|
| 1  | `{(331902.5, 331902.5)}` — 15/15 identical |
| 2  | `{(331902.5, 331902.5)}` — 15/15 identical |
| 4  | `{(331902.5, 337817.7), (337817.7, 331902.5), (331902.5, 331902.5)}` |
| 8  | adds `(337817.7, 337817.7)` on top of the above |
| 24 (production default) | same flip pattern as 4/8 |

Determinism holds at `--threads 1` and `--threads 2` in this sample; any thread count `>= 4`
reproduces the flip. This matches a known class of OSRM behaviour: MLD tie-breaking on
near-equal-cost paths is not guaranteed stable across worker threads, because unpacking an
optimal path from tied candidates depends on iteration order of per-thread search state that can
differ between threads even against identical, unmodified static data.

## Why this is "near-identical" after all, not a real divergence

The other 4 named test pairs (genuine APRR toll gates, `verify_fare_pair`) show a real toll
bypass effect of +40% to +75% duration when `exclude=toll` is set
(`reports/phase1b_snapping.md`) — the toll-free route is genuinely, substantially worse, which is
exactly what the exact-equality `distinct` check is meant to catch. The A75 pair's two
observed routes differ by only 1.8% distance / 6.1% duration — an order of magnitude smaller,
comfortably inside the "near-identical" description the test's own docstring already uses. The
previous exact-equality check could never tolerate engine-level tie noise of any size; it wasn't
wrong to expect near-identical routes, just too strict about what counts as identical.

## Fix shipped

`tollroute.etl.snap_report.verify_geo_only_pair` now classifies the pair as distinct only when
distance or duration differ by more than `GEO_ONLY_MATERIAL_DIVERGENCE_REL_TOL` (10%, chosen with
margin above the observed 6.1% noise ceiling and margin below the 40-75% real-divergence floor
seen on the other 4 pairs) using `math.isclose`. `verify_fare_pair` (the other 4 pairs) is
untouched — their real divergence is large enough that exact equality was never the source of
flakiness there, and loosening that check would reduce its sensitivity for no benefit.

**Verified the fix, not just the theory:** re-ran `verify_geo_only_pair` 30x against the live
production (`--threads 24`) container post-fix — `distinct_route` was `False` in all 30 runs (was
flipping ~50% of runs before the fix). `python3 -m pytest tests/test_snap_report.py` re-run 5x
independently — 2 passed each time.

## Filed, not fixed here: production implication

`osrm-routed --threads 24` (the default this project's `docker-compose.yml` uses for the live
national OSRM the API/CLI actually query) can, by the same mechanism, return a different
"fastest"/"cheapest" route for any live query that happens to hit a near-tied corridor
elsewhere in France — not just this one Clermont-Ferrand-Montpellier test pair. That is a
broader potential correctness/consistency question for the production routing service, distinct
from this test-only fix, and is filed as a new item below per this project's
"document, don't fix outside current item" rule.
