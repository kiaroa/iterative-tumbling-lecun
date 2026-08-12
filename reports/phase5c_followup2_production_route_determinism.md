# Phase 5c-follow-up-2: does `tollroute.api`'s `/route` flip under production concurrency?

## Scope

Phase 5c-follow-up (`reports/phase5c_followup_a75_osrm_nondeterminism.md`) proved that raw
`osrm-routed /route` calls are non-deterministic on near-tied corridors once server concurrency
exceeds ~2 threads, and that production serves at the host's full core count (no `--threads` flag
in `osrm/docker-compose.yml`, defaulting to `hardware_concurrency()` - confirmed 24 on this host
via `nproc`). That report deliberately left open whether `tollroute.api`'s own `/route` endpoint -
which layers `tollroute.graph`'s Dijkstra over a mix of live and precomputed OSRM data, not a raw
`/route` call - is exposed to the same effect, or only the raw-OSRM-only test pair is. This item
answers that question by direct measurement, then makes the (a)/(b) decision the plan item asks
for.

## What in the `/route` path is actually live per request

Reading `tollroute/graph.py` and `tollroute/api.py` end to end: only two OSRM interactions happen
per request, both inside `api.cached_shape`:

1. **`osrm_client.baseline_route`** - one raw `/route` call, tolls allowed, used only as an
   availability canary and a `baseline` display field (module docstring: "a client can display for
   comparison"). Exactly the same call shape as Phase 5c-follow-up's failing test.
2. **`graph.add_access_edges`** - two `/table` batches (origin->every gate's IN node,
   every gate's OUT/OUT_TOLL node->destination), tiled to <=100-wide blocks.

Everything else that decides *which* route wins - every toll and toll-free gate-to-gate leg - comes
from Phase 3b's precomputed `.npy` matrices, loaded once at graph-build time and never touched
again per request (`build_graph`'s docstring: "re-fetching an 815x815 table live on every service
boot would be far slower than reading a 10 MB `.npy` file"). Those numbers are frozen; only the
handful of access-edge legs and the baseline call are live OSRM output per request.

## Direct measurement

Wrote a probe (`/tmp/nondeterminism_probe/probe.py`, not committed - throwaway) that drives the
exact production code path - `graph.build_graph` once, then per call: `osrm_client.baseline_route`
+ `graph.add_access_edges` + `response.shape_response` - against the live production OSRM container
(`osrm-osrm-routed-1`, `--algorithm mld`, default thread count = 24 cores), bypassing
`api.cached_shape`'s `lru_cache` so every call is a genuine fresh (cache-miss) request, not a
cache hit.

Two corridors, repeated calls with no code/data/container change in between:

- **Clermont-Ferrand -> Montpellier** (the A75 pair, the one corridor already proven to have a
  near-tied raw-OSRM route): 45 total repeat requests across two runs (15 + 30).
- **Dijon -> Lyon** (an ordinary corridor with a large genuine toll-bypass gap, Phase 1b pair 1):
  15 repeat requests, as a non-adversarial control.

Results:

| corridor | distinct `baseline` values | distinct `options` (fastest/cheapest/best_value, gates, tolls) values |
|---|---|---|
| Clermont-Ferrand -> Montpellier | **2** (331,902.5 m/13,336.0 s and 337,817.7 m/14,148.3 s) | **1** |
| Dijon -> Lyon | 1 | 1 |

`baseline` reproduces exactly the same two-way flip Phase 5c-follow-up already characterised - it
is the same call, doing the same thing, and behaves identically inside the API path. `options` -
the actual toll-minimising recommendation this service exists to produce - was byte-identical
across every one of the 60 total repeat requests on both corridors, including all 45 on the one
corridor already known to be adversarial. This is consistent with the code reading above: the
access-edge legs from `/table` evidently don't shift enough (if at all) on this corridor to move
which gate chain Dijkstra prefers, and the real toll/toll-free weights that do the deciding are
frozen, not live.

## (a) Established: can `tollroute.api`'s `/route` responses flip?

**Only the `baseline` field, not the routing recommendation.** `fastest`/`cheapest`/`best_value`
(and their gates, tolls, distances, durations) were fully deterministic across every repeat request
measured, including on the one corridor already proven adversarial for raw OSRM. `baseline` - an
explicitly-labelled comparison/reference figure, not the recommendation itself - does flip, by the
same <=1.8% distance / <=6.1% duration margin already characterised as engine tie-noise, not a real
route difference.

This is also narrower in practice than "any repeat client request can see this": `cached_shape` is
wrapped in `@lru_cache(maxsize=512)` keyed on exact origin/destination/class/VoT
(`tollroute/api.py`). A real client re-querying the same trip against a *running* server process
gets the same cached dict, `baseline` included, every time - the flip is only reachable via a cache
miss (a distinct-enough query, cache eviction past 512 entries, or a service restart), not on every
duplicate request.

## (b) Decision

**No infrastructure change** (`osrm/docker-compose.yml`'s thread count is left at the default).
Reasoning, weighing the three options the plan item named:

- **Pin a lower thread count** (verified deterministic at `--threads<=2` in the prior report) would
  remove even the narrow residual `baseline`-only risk, but at a service-wide throughput cost that
  has not been load-tested, for a field that is cosmetic (a labelled comparison figure, not the
  recommendation) and already reduced by the ~300 ms warm-request budget's own `lru_cache`. Per the
  plan's own steer against "a reflexive threads=1 change," an unmeasured fleet-wide throughput cut
  isn't justified by what this measurement found.
- **Switching algorithm (e.g. CH)** is a materially larger change (CH has different update/rebuild
  characteristics than MLD) to fix a problem confirmed confined to one non-recommendation display
  field - disproportionate to the finding.
- **A request-level consistency mechanism** (e.g. retrying `baseline_route` until two calls agree,
  or dropping it to a cached/derived value) would only mask the same engine noise, not remove it,
  and adds latency/complexity to the one call in this path deliberately chosen for being "the
  cheapest possible OSRM call" (module docstring) - working against its own purpose as a fast
  availability canary.

Given the routing recommendation itself is verified deterministic and the sole affected field is
explicitly a reference/comparison value already dampened by the existing cache, this is accepted,
documented behaviour rather than a defect. Flagged directly at the `baseline_route` call site
(`tollroute/osrm_client.py`) so a future reader hits this finding without re-deriving it, rather
than duplicating the writeup there.

## Verification

- `PYTHONPATH=/workspace python3 /tmp/nondeterminism_probe/probe.py 15` - 15 repeat live requests
  each for the A75 pair and Dijon->Lyon.
- `PYTHONPATH=/workspace python3 /tmp/nondeterminism_probe/probe.py 30` (probe2.py, A75 only) - 30
  further repeat live requests on the adversarial corridor.
- All 60 requests ran against the live, unmodified production container (`osrm-osrm-routed-1`,
  untouched/not restarted during this investigation) - no container or `--threads` variation was
  needed this time, since the question was about the already-running production configuration, not
  a sweep across configurations (that sweep was already done in the prior report).
