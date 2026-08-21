# Sub-route search tree — exploratory findings

Script: `analysis/subroute_search/explore.py` · data: `results.csv`, `diagnostics.json`
Run: 2026-08-14 (re-run after the pricing-data fixes below), 25 OD pairs, 350–450 km, car (class 1), local OSRM France + national gate DB.

## What was tested

Your algorithm, with the options chosen in planning: value-of-time acceptance rule; compared
only against the two routes OSRM gives for free; skip-whole-section **and** partial-section
use; combined across sections by exact DP.

Per OD pair: OSRM `alternatives=3` → snap toll gates to each polyline → group into toll
sections → per section generate `{keep full, skip, enter/exit at intermediate gates}` →
DP over (section, position) minimising `G = toll + VoT × hours` → compare against
`min(fastest as-is, full exclude=toll)`.

## Headline result

| VoT €/h | beats both free options | of which by real sub-route surgery |
|--------:|------------------------:|-----------------------------------:|
| 5       | 1 / 22                  | 0 |
| 10      | 1 / 22                  | 0 |
| 20      | 7 / 22                  | **4** |
| 40      | 4 / 22                  | **2** |

(22, not 25: three pairs are excluded because the fastest route contains a section the
fares table cannot price, so their baseline cost is unknown.)

**The distinction that matters:** several "wins" come from simply picking a *different OSRM
alternative as-is* — no sub-route surgery involved. Across all 88 pair×VoT results the
winning option was: all-skip (= plain toll-free route) 48, alternative 0 as-is 27, a
different alternative as-is 7, **actual sub-route surgery 6**.

So the search tree earns its keep on roughly **1 pair in 5, and only at VoT ≥ 20 €/h**.

### The wins are large when they happen

| pair | VoT | beaten baseline | result |
|---|---:|---|---|
| Perpignan→Bayonne | 40 | fastest €73.10 / 304.6 min | **€18.90 / 360.1 min** — saves €54.20 for +55 min |
| Saint-Étienne→Pau | 40 | toll-free 512.8 min | €10.70 / 464.9 min — 48 min faster for €10.70 |
| Le Mans→Besançon | 20 | toll-free 492.7 min | €24.50 / 407.8 min — 85 min faster for €24.50 |
| Bordeaux→Saint-Étienne | 20 | toll-free 474.1 min | €2.20 / 465.0 min — marginal |

The pattern is consistent and it is the interesting one: the wins are almost all against the
**toll-free** baseline, not the fastest one. OSRM's `exclude=toll` is a blunt instrument — it
abandons the motorway network entirely. Buying back one well-chosen tolled segment recovers
most of the time for a fraction of the full toll. That is a genuine gap in the free options,
and it is what your algorithm exploits.

## Where the algorithm as specified does not work

**Step 1 (short-circuit on a zero-price fastest route) almost never fires.** 1 of 25 pairs
(Toulouse→Toulon). Median toll on the fastest route is €38.45. At 400 km in France, a free
fastest route is the exception.

**Steps 2 and 4 (the 2nd and 3rd fastest routes) are often unavailable.** OSRM returned
1 route for 10 of 25 pairs; median 2, max 4. `alternatives=3` is correct — MLD simply finds
no alternative on most long French routes. Where alternatives did exist they were worth
having: 7 wins came from a non-fastest alternative taken as-is.

**Toll-free connectors cost ~9 minutes of structural overhead.** Rebuilding the *same* route
from toll-free access legs plus tolled section legs takes a median +8.9 min (max +32.1) over
the actual route. The tree therefore starts every candidate at a handicap and cannot
reproduce the original — the original must be kept as an explicit candidate or the algorithm
loses to its own input. Conjecture, untested: this is gate coordinates snapping to slip
roads and the wrong carriageway rather than a real detour.

**The toll-free connector rule is too strict.** Your specification routes between sections
with tolls excluded. Between two sections of the *same* motorway the correct connector is the
motorway itself. Modelled properly, sections should be defined by contiguity along the route
(as done here) rather than by tariff boundaries.

## Cost

Cheap. 1,623 OSRM calls for 25 pairs — median 59 per pair, max 207. Wall clock 0.1–0.4 s per
pair against local OSRM, 4.6 s total. Not the bottleneck; the tree could be several times
wider before latency mattered. Note this is with a section-gate cap of 6 (endpoints + 4
intermediates); lifting it grows candidates quadratically.

## Data-quality problems found (these affect any version of this algorithm)

1. **Unpriceable sections.** 3 of 25 fastest routes, and 7 of 58 alternatives, contain a
   toll section the fares table cannot price. Early runs silently reported these as €0,
   which made unpriceable routes look free and produced fake "savings" of €40+. Now excluded.
2. **Concession boundaries fragment the fare graph.** Grenoble→Perpignan is one continuous
   motorway run of 32 gates, but no fare links Chatuzange (AREA, A49) to Valence sud (ASF,
   A7). Fare-adjacency cannot be used to define sections. Pricing here splits a section at
   such cuts, prices each run, and crosses the cut free — median 2 such free crossings per
   route. Each is a place where a genuinely missing fare would be silently priced at €0.
3. **Duplicate gate records.** Orange nord / ORANGE, Baillargues / Vendargues and similar
   pairs snap as separate gates with no fare between them, creating spurious cuts.
4. Resulting totals look right where checkable: Grenoble→Perpignan €38.10, Perpignan→Bayonne
   €73.10 — plausible for a car, but **not independently verified** against operator tariffs.

## Comparison against the existing engine (`tollroute/pareto.py`)

Added after the first draft, which predicted the overlay-graph engine would dominate the
tree. It does not.

`analysis/subroute_search/compare_engine.py` runs `pareto_sweep` single-step at each VoT over
the same 25 pairs. Cost is recomputed from toll and duration only, so both sides are scored
on the same metric.

**Bare graph search vs the tree:** the tree wins 88 of 88 comparable results. That headline is
misleading on its own — the engine's search must route via a gate, so even its EUR 0 answer is
a worse toll-free route than the direct `exclude=toll` route the tree gets for free.

**Same free baselines given to both** — the fair comparison:

| VoT EUR/h | engine wins | tree wins | tie |
|--------:|------------:|----------:|----:|
| 5  | 0 | 0 | 22 |
| 10 | 0 | 0 | 22 |
| 20 | 0 | 6 | 16 |
| 40 | 0 | 4 | 18 |

The engine never strictly beats the tree, and its graph search beats the two free options only
**2 of 22** times at VoT 20 and 2 of 22 at VoT 40. Both approaches add value in the same small
set of cases.

Where both find something, they find close to the same thing (VoT 20):

| pair | engine | tree |
|---|---|---|
| Perpignan→Bayonne | EUR 19.60 / 366.0 min | EUR 18.90 / 360.1 min |
| Bordeaux→Saint-Étienne | EUR 8.60 / 472.1 min | EUR 2.20 / 465.0 min |
| Le Mans→Besançon | EUR 14.80 / 444.5 min | EUR 24.50 / 407.8 min |
| Saint-Étienne→Pau | EUR 0.00 / 515.8 min | EUR 10.70 / 470.5 min |

**Speed:** engine solve 0.02 s per VoT once the graph is built (~5 s build, done once at boot
in production). Tree: 59 OSRM calls and ~0.2 s per pair, no build. Neither is a constraint.

## Pricing-data fixes applied since the first draft

The first draft said the pricing gaps "cost more accuracy than either search algorithm gains".
Acting on that surfaced a larger problem underneath, now fixed:

- **The gate-to-gate distance matrix was indexed wrong.** `gare_master.csv` had changed to
  produce **818** physical gate clusters, but `data/matrices/*.npy` was still **815x815**.
  Every index past the divergence was shifted. Measured against 21,656 live-OSRM distances,
  the matrix agreed within 10% on **8%** of pairs (median ratio 1.71, p95 8.3). Rebuilding it
  at 818x818 took agreement to **100%**.
- **That broken matrix was the sole evidence behind the gate quarantine.** It caused 46 gates
  to be quarantined, removing **7,728 of 57,141 fare rows (13.5%)** from the engine — 43 of
  those 46 scored `LIKELY_VALID` in `analysis/gate_validation/gate_scores.csv`.
- **Quarantine is now two-signal and row-level.** A gate needs both the distance rule and an
  independent `LIKELY_INVALID` verdict; individual fare rows are rejected on their own using a
  symmetric `min(forward, reverse)` test with per-operator normalisation. Usable fare rows went
  from **49,413 to 52,143**, with 4,980 rows now rejected individually instead of 7,728
  rejected by association.
- **`distance_error` now validates its own source** against live OSRM and refuses to quarantine
  anything if it fails, so this class of silent corruption cannot recur.
- **APRR/AREA open-system charges are no longer lost.** 18 fare rows are filed against a
  pseudo-gate named "Système Ouvert", which stands for a set of barrier-free entry points, not
  a place. Measured against live OSRM: the paired gates lie 112-397 km from that pseudo-gate's
  coordinate against a stated `distance_km` of 7-61 km; no common reference point exists
  (2 of 153 gate pairs, correlation +0.23); and it is neither the nearest gate (2/18) nor the
  nearest barrier gate (1/18). What the distances *do* behave like is real tariff distance -
  EUR/km clusters per operator at APRR 0.0968 and AREA 0.1280. These are therefore flat
  per-passage charges belonging to the paired gate, and are now stored as self-loops, the
  encoding `graph.py` already applies to A14's gantries. Free-flow self-loop gates in the graph
  went from 3 to 21.

**Known gap this leaves:** the sub-route tree loads those 21 self-loop entries but never
charges them, because `chain_prices` only reads forward `i < j` gate pairs. The engine prices
them; the tree does not. Charging them correctly means deciding when a flat barrier charge is
already covered by a closed-system through-fare, which is not resolved here.

## Two pricing bugs found by checking one known route

A known toll-optimised Calais->Amboise route (A16 -> A28 -> N154 -> N10, EUR 9.30) was used as
a ground-truth check. It found two defects in this harness, both since fixed:

1. **Hop-chaining beat the through fare.** `chain_prices` returned the cheapest *sum of fare
   links* across a section, pricing A16 Boulogne Est -> Abbeville Nord at EUR 7.70
   (1.10 + 1.70 + 3.10 + 1.80) against the EUR 9.30 through fare that exists for that exact
   span - a EUR 1.60 under-price. In a closed system you pay the through fare; the sum of hops
   is only payable if you physically leave and re-enter at each junction. A published through
   fare now always wins; chaining remains the fallback where no through fare exists.

2. **Toll sections invented beside free roads.** Snapping proves proximity, not use. An
   `exclude=toll` Abbeville -> Amboise route snaps ROUEN LES ESSARTS (35.5 m) and INCARVILLE
   (215.9 m) from the free road that parallels the A13, and was billed EUR 2.40 for a
   motorway it cannot legally have used. `drop_untolled_sections` now probes: two points on
   the *driven line*, 2 km outside the section, routed with tolls excluded; if that line
   nearly coincides with the driven line, the road was reachable without paying and the
   section is dropped. Anchoring the probe on the line rather than on the two gates is what
   makes it work - gate coordinates sit on tolled tarmac, so a gate-to-gate toll-free route
   always detours around them and always looks divergent (measured 2.42 km even for a section
   the route drove toll-free). With line anchoring, genuine sections measure 2.42 / 6.98 /
   35.39 km or have no toll-free route at all; the phantom measures 0.00 km.

### Duplicate gate records lose whole motorway tolls

Checking the *tolled* Calais->Amboise route (A26 -> A1 -> A10) found the sub-route tree
charging EUR 32.60 where the fare data supports EUR 42.60. Both sections were wrong, for the
same reason: a section endpoint lands on one record of a multi-record interchange, and that
record carries no relevant fares, so the span was crossed as an unpriced boundary at EUR 0.

| snapped gate | its fares | co-located record | its fares |
|---|--:|---|--:|
| 393 `LA FOLIE-B/PARIS` | 192 | 0 m -> 626 `PARIS (LA FOLIE BESSIN)` | 400 |
| 34 `AMBOISE CH.RENAULT` | 192 | 386 m -> 217 `CHATEAU-RENAULT` | 321 |
| 727 `SAINT-OMER` | - | 451 m -> 177 `CALAIS (péage de Setques)` | - |

The A10 leg priced at EUR 14.40 by chaining across five cuts; the correct records price
`PARIS (LA FOLIE BESSIN) -> CHATEAU-RENAULT` at **EUR 22.40**. The A26/A1 leg went from
EUR 18.20 to EUR 20.20 once the entry resolved to the barrier record.

Two changes:

- **`build_aliases`** groups records within 500 m that share a route tag (or have one blank),
  and fare lookup takes the best-priced alias pair. 382 of 956 gates have at least one alias.
  The route condition is what stops it merging the genuinely separate carriageway barriers
  50-100 m apart that `cluster_gates` warns about.
- **A cut at either end of a span now makes it unpriceable, not free.** An interior cut is a
  real concession boundary; a cut at the entry or exit just means the fare is missing, and
  EUR 0 there loses real money silently. This is the rule that was hiding the EUR 8.00 of A10.

Honest consequence: sections that cannot be priced are now *reported* rather than
under-charged. Across the 25-pair sample, routes with at least one unpriceable section rose
from 3 to 8, and the comparable-pair count fell from 22 to 17. That is the same data quality
as before, stated accurately instead of silently discounted.

**A third defect is a model limit, not a bug.** The engine's reconstruction of the EUR 9.30
route costs 391.4 min against the real 374.0 - a 17.4 min handicap from routing every access
leg with `exclude=toll`. That flips the decision: break-even against the engine's own EUR 5.10
option is 11.7 EUR/h if timed correctly but 61.5 EUR/h as modelled, so the route is never
selected at any value of time. Relaxing the constraint is **not** the fix - the tolls-allowed
version of that same access leg uses EUR 30.30 of motorway, which the toll-free access rule
exists to stop being ridden for free. Closing the gap needs free stretches of tolled motorway
to be representable, which is the open-system / free-flow work still outstanding.

**A regression found the same way:** `build_national.run` deletes and recreates the DB but
never regenerated `access_anchors`, so a rebuild silently emptied it (497 rows -> 0). Without
an anchor, `Calais -> Boulogne Est` under `exclude=toll` returns `NoRoute` - the barrier sits
on tolled tarmac - making the whole A16 corridor unusable as an entry point. The step is now
part of the pipeline (538 anchors).

Test suite: **49 failures before, 24 after, zero regressions.** The remaining 24 are pinned
expectations that predate this work (they assert 953 gates / 815 clusters / 3 coordinate-less
against a `gare_master.csv` that now has 956 / 818 / 0) plus golden fixtures recorded against
the old gate set.

## Verdict

The core idea is sound but the value is narrower than the specification assumes, and it sits
in a different place than expected.

- The parts of your algorithm that do the least work are steps 1, 2 and 4 (zero-price
  short-circuit, 2nd/3rd fastest). Step 1 fires 4% of the time; alternatives are missing 40%
  of the time.
- The part that pays is partial use of a *single* toll section as a middle option between
  "pay the full motorway toll" and "avoid all tolls". Skipping whole sections adds little,
  because skipping every section is just the toll-free route you already had.
- It only beats the free options for drivers valuing time at ≥ 20 €/h. Below that the plain
  toll-free route wins outright.
- The existing overlay-graph engine does not beat it, and on its own finds a better-than-free
  answer even less often (2/22 vs 7/22 at VoT 20). The tree is not redundant.

The real finding across both approaches: **for 400 km French routes, a genuinely useful
toll/time compromise exists in only about a third of cases, and neither method finds one more
often than that.** The rest of the time the answer is simply "take the motorway" or "take the
free route". That is a property of the French network, not of either algorithm.

n=25 with 4–7 winning cases is a thin base; the direction is clear, the hit rate is not
precise.

**Recommendation:** keep the partial-section search — it is cheap, needs no graph build, and
matches or beats the existing engine. Drop the zero-price short-circuit and demote the
multi-alternative expansion to a free extra candidate rather than a search stage.

The remaining pricing gaps (unpriceable sections, concession-boundary cuts, duplicate gate
records, open-system barriers, free-flow sections, ambiguous fare rows) are still open and are
still worth more than either search algorithm — 3 of 25 fastest routes still cannot be fully
priced. What has changed is that the largest one is now fixed, and the distance check that
guards the rest can no longer silently run on a broken source.
