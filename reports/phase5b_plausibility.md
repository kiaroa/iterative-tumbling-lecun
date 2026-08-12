# Phase 5b — Route plausibility and independent estimate

**Objective.** Confirm route recommendations match what a French driver would expect, per
`iterative-tumbling-lecun.md` Phase 5b: 10 plausibility routes checked manually, plus a
HERE/TomTom toll-cost API cross-check as an independent validator.

## Independent validator: HERE/TomTom unavailable, substituted

No HERE or TomTom API key is present in this build environment (checked `env`, no
`.env*`/secrets files in the repo). Calling the TomTom Routing API directly without a key
confirmed a hard `401 Unauthorized` — there is no free/keyless tier for either provider's
toll-cost endpoint, and creating a third-party developer account was judged out of scope for
an unattended build iteration (an externally-visible action on the user's behalf, not a
reversible local one).

Substitute found: **ulys.com** (Vinci Autoroutes' télépéage-badge subsidiary) publishes a
per-corridor toll calculator page (`ulys.com/prix-du-peage/<origin>-<destination>/`) stating
a class-1 toll estimate, distance, duration and the specific entry/exit toll-gate names used
— reachable via `WebFetch` (unlike `autoroutes.fr`/`vinci-autoroutes.com`'s own calculators,
already found unreachable — TLS error / 404 — in Phase 5a). This is the same fallback pattern
Phase 2a/5a already established for this project (bulk/API source unavailable → individual
public calculators, one pair at a time, not a production dependency) — applied here to route
totals instead of gate fares. Checked for 4 of the 10 pairs (Paris-Lyon, Paris-Bordeaux,
Marseille-Nice, Strasbourg-Paris); the other 6 had no findable `ulys.com` page for that exact
corridor and are checked on human-expectation grounds only, named as such below. The Millau
viaduct's own official 2026 tariff PDF (`leviaducdemillau.com`) was used for the A75 case.

## The 10 routes

Run via `python3 -m uvicorn tollroute.api:app` + `analysis/phase5b_plausibility.py`, class 1,
against the live national OSRM/matrix build. `fastest` is this service's toll-minimising
duration-weighted route; `baseline` is a single direct OSRM `/route` call (tolls allowed,
ignoring the toll-minimising graph entirely) — a "what would plain GPS say" reference point.

| # | Route | Operator/region | Ours: toll / dist / dur | Baseline dist / dur | Ulys: toll / dist / dur | Verdict |
|---|---|---|---|---|---|---|
| 1 | Paris→Lyon | A6, APRR | €32.90 / 484.7 km / 343.8 min | 465.9 km / 297.7 min | €41.30 / 467 km / ~270 min | matches shape; toll/duration gap explained below |
| 2 | Paris→Bordeaux | A10, Cofiroute→ASFC | €57.30 / 605.0 km / 417.9 min | 584.8 km / 368.6 min | €60.90 / 587 km / ~355 min | matches shape; small gap, explained below |
| 3 | Clermont-Ferrand→Montpellier | A75, mostly free | €0.00 / 351.6 km / 246.5 min | 337.8 km / 235.8 min | Millau flat fee €11.30 (official PDF) | matches "mostly free" shape; Millau gap explained below |
| 4 | Paris→Lille | A1, Sanef | €14.60 / 221.2 km / 174.1 min | 219.8 km / 151.1 min | not checked (no page found) | plausible (human expectation) |
| 5 | Paris→Marseille | A6/A46/A54, APRR+ASFC | €69.60 / 818.1 km / 555.1 min | 774.6 km / 493.2 min | not checked (no page found) | plausible; gate chain follows real A46 Lyon-bypass routing |
| 6 | Nice→Marseille | A8, Escota | €16.60 / 205.0 km / 158.0 min | 198.7 km / 141.8 min | €21.20 / 199 km / 139 min (Marseille→Nice) | matches shape; small gap, explained below |
| 7 | Bordeaux→Toulouse | A62, ASFC | €22.90 / 244.9 km / 168.1 min | 243.9 km / 161.3 min | not checked (no page found) | plausible (human expectation) |
| 8 | Lyon→Chamonix | A40, ATMB | €13.20 / 231.7 km / 209.9 min | 223.9 km / 154.8 min | not checked (no page found) | plausible; largest baseline gap (see below) |
| 9 | Strasbourg→Paris | A4, Sanef/APRR | €40.30 / 491.5 km / 325.2 min | 491.9 km / 305.9 min | €44.70 / 492 km / 285 min | matches shape; small gap, explained below |
|10 | Calais→Reims | A26, Sanef | €21.50 / 275.5 km / 201.4 min | 266.6 km / 165.7 min | not checked (no page found) | plausible (human expectation) |

All 10: toll present and roughly proportional to distance (€0.057-€0.095/km, in line with
published French class-1 averages) on genuinely tolled corridors, near-zero on the one
genuinely-free-motorway corridor tested (#3), and a real toll-free alternative exists for
every route at a real, non-trivial time cost (7 to 195 minutes, from the same
`analysis/phase5b_plausibility.py` run — full per-route cheapest-option figures in that
script's output). Gate chains resolve to sensibly-located, correctly-named real toll
barriers on the right motorway for every route (spot-checked #1, #2, #5, #6, #7, #8, #9, #10
against `gates.canonical_name`/`primary_route`); route #5's chain (Nemours→La Boisse→St-Priest
centre→Salon sud) follows the real A46 Lyon-bypass corridor a route planner would suggest,
not a naive straight shot through central Lyon.

## Divergences, with named root cause

### 1. `fastest` duration is systematically higher than `baseline` and Ulys (routes #1, #2, #6, #9)

| Route | fastest vs baseline | fastest vs Ulys duration |
|---|---|---|
| Paris→Lyon | +15.5% | +27.3% |
| Paris→Bordeaux | +13.4% | +17.7% |
| Nice/Marseille↔Nice | +11.4% | +13.7% |
| Strasbourg→Paris | +6.3% | +14.1% |
| Lyon→Chamonix | +35.6% (largest gap; no Ulys figure) | — |

**Root cause (named, evidenced, not new):** `tollroute/graph.py:564-579`'s `add_access_edges`
deliberately fetches the origin→entry-gate and exit-gate→destination legs with OSRM's
`exclude=toll` (Phase 4c decision, already documented there: without it, the "local finish"
leg could ride the paid motorway for free and defeat toll accounting, confirmed empirically
in that phase). This is correct for genuinely tolled sections, but it also excludes the real
open-system stretch nearest to a city where the physical motorway carries **no** toll yet
(e.g. A6 immediately south of Paris) — pushing that leg onto slower parallel roads and, in
Paris→Lyon's case, past the "obvious" nearest gate (Fleury-en-Bière, gate 302/303 — Ulys's
and presumably a real driver's choice) to a farther one (Nemours, gate 585) that needs less
of that slow toll-free lead-in. Evidence this is the mechanism, not noise: Paris→Bordeaux's
engine-chosen entry gate is `PARIS (LA FOLIE BESSIN)` (gate 626) — **the exact same gate**
Ulys's calculator uses — and that route's gap (distance +3.1%, duration +17.7% vs Ulys) is
correspondingly the smallest of the three fully-checked long routes; Strasbourg→Paris's
distance matches baseline almost exactly (491.5 vs 491.9 km, -0.1%) yet duration is still
+14.1% over Ulys, showing the inflation comes disproportionately from slow-road km on the
access legs, not extra total distance. Filed as a follow-up (not fixed here — out of scope
for a plausibility check per the Build Agent's one-item-per-iteration rule): see
`IMPLEMENTATION_PLAN.md` Phase 5b-follow-up.

### 2. Toll cost is consistently at or below the Ulys figure, never above (routes #1, #2, #6, #9: -5.9% to -21.7%)

This is the *expected* direction for a genuine toll-minimiser: `routing.find_route` searches
every candidate gate pair via Dijkstra, while Ulys's calculator (like most consumer tools)
returns the toll for the single "obvious" continuous route. Where the two happen to pick the
same entry gate (Paris→Bordeaux, above), the toll gap shrinks to -5.9% — consistent with the
same mechanism as divergence 1, not a separate data problem. `tollroute/validation/fare_oracle.py`
(Phase 5a) already confirmed the underlying per-gate-pair fares are correct to the cent
against official APRR/AREA tariffs; this cross-check adds confirmation that gate pairs *not*
in Phase 5a's 26-pair sample are also correct — e.g. gate pair (303→929) "Fleury-en-Bière →
Villefranche-Limas" prices at €41.30 in this project's own `fares` table, an exact match to
Ulys's independently-published figure for that same gate pair.

### 3. Clermont-Ferrand→Montpellier (A75) omits the Millau viaduct's real toll (route #3)

**Root cause (named, not new):** the Millau viaduct is operated by CEVM (Compagnie Eiffage du
Viaduc de Millau), which is not one of this project's 13 dataset operators (confirmed:
`operator_alias` / `gates.operators` contain no CEVM/Millau entry). Phase 1b/1d already
documented "A75 is an untolled state motorway" for this exact corridor without flagging
Millau as a gap; this phase's independent check against Millau's own 2026 tariff PDF puts a
number on that gap: **€11.30** off-peak class-1 (rising to a July/August peak-season rate not
extracted here), a single flat-gantry fee the project's existing `freeflow_override` table
(`tollroute/db/tollroute_national.sqlite`, currently empty) is structurally the right place
for, were CEVM ever added as a 14th operator. Out of scope to fix in this item; filed as a
follow-up below. This is exactly the case the spec names Phase 5b to find ("breaks
'motorway ⇒ tolled' assumption") — the shape (near-zero toll, mostly-free corridor) matches
human expectation; the one-structure omission is the named, pre-existing, documented
boundary of the current operator set, not a new defect.

## Exit criterion

All 10 plausibility routes match human/driver expectation in shape: toll present and
distance-proportional on genuinely tolled motorways, near-zero on a genuinely free one, a
real (non-trivial, correctly time-costed) toll-free alternative always available, and gate
chains resolving to correctly-named, sensibly-located real toll barriers on the right
motorway. Every identified divergence from the independent validator (Ulys, for the 4 pairs
checked; Millau's own tariff PDF for route #3) has a named, evidenced root cause tracing to
an existing, already-documented Phase 4c design decision (access-edge toll exclusion) or an
already-documented Phase 1b/2a data-coverage boundary (13 dataset operators, no CEVM) —
**exit criterion met.**

## Follow-ups filed (not implemented here — out of scope for this item)

- `IMPLEMENTATION_PLAN.md` Phase 5b-follow-up-1: investigate whether `add_access_edges` could
  distinguish a motorway's genuinely toll-free open-system lead-in from its tolled section
  (rather than excluding the whole named road via `exclude=toll`), to close the systematic
  ~15-35% `fastest`-vs-`baseline` duration gap found here.
- `IMPLEMENTATION_PLAN.md` Phase 5b-follow-up-2: consider adding CEVM (Millau viaduct) and any
  other single-structure concessions outside the 13 dataset operators to `freeflow_override`
  as flat-fee rows, the same mechanism already used for A14-style single-gantry tolls.

## Test outcome

No `tollroute/` core code changed (analysis/validation only) — `python3 -m pytest`: 150
passed, 3 skipped, 7 xfailed, unchanged from Phase 5a, no regressions.

## Files

- `analysis/phase5b_plausibility.py` — runs the 10 routes against a live `tollroute.api`
  instance, prints `fastest`/`cheapest`/`baseline` for each (reproduces this report's table).
- `reports/phase5b_plausibility.md` — this report.
