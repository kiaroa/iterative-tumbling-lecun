# Phase 0 — Itinerary-dependence test

Blocking-gate analysis per `iterative-tumbling-lecun.md` Phase 0. Pure data analysis over `od_pairs.csv`; no service code, no OSRM.

## Method

The spec's protocol: pick 10-20 OD pairs reachable via two distinct concession paths, compare prices against toll sums for each path. This run does that exhaustively rather than on a small hand-picked sample, then tabulates a representative 10-20 pair subset (below) in the spec's requested format.

**Why exhaustive, and why this specific test:** an earlier iteration of this analysis picked geographically near-collinear intermediate gates and found the *direct* fare is usually cheaper than a 2-hop decomposition (consistent with degressive per-km tariffs) - a real phenomenon, but **harmless** to a cost-minimising Dijkstra, which would simply never select the pricier decomposition. The test that actually matters for correctness is the opposite direction: does a same-operator multi-hop chain of `od_pairs` edges ever cost *less* than the true direct through-fare? If so, Dijkstra - built exactly as IMPLEMENTATION_PLAN.md's Phase 1c item specifies ("APRR toll edges from od_pairs" as directly usable graph edges) - would silently select that cheaper chain and return a toll price lower than any real driver could achieve, because each `od_pairs` row represents one continuous single-entry/single-exit journey; chaining two such rows through an intermediate gate B implies a genuine toll-plaza exit and re-entry at B, which is not free and is not what the summed fare represents.

This test is exact and exhaustive, not a proxy: for every operator, every direct `od_pairs` edge (A→C) is compared against the true graph shortest path A→C over *all* of that operator's edges (pure-Python Dijkstra - `scipy` is specified by the stack but is **not installed and not installable in this environment** — no `pip`/`ensurepip` and no network access; flagging this as a Phase 1b/1c blocker in its own right, filed as a new plan item). An edge is **undercut** if the shortest path beats the direct price by more than max(€0.05, 0.5%) - a tolerance chosen only to absorb float/rounding noise, not to forgive genuine mispricing.

## Results

**Same-operator direct edges checked (exhaustive):** 56480

**Undercut by a cheaper same-operator multi-hop chain:** 48849 (86.5%)

**Threshold:** >5% itinerary-bound triggers corridor enumeration.

**Go/no-go:** NO-GO: adopt corridor enumeration (or equivalent graph fix, see below)

### Per-operator breakdown

| Operator | Direct edges | Undercut | % |
|---|---|---|---|
| APRR | 21017 | 18254 | 86.9% |
| ASFC | 18036 | 16142 | 89.5% |
| Cofiroute | 10934 | 9812 | 89.7% |
| sanef | 2728 | 2256 | 82.7% |
| escota | 2215 | 1924 | 86.9% |
| AREA | 503 | 280 | 55.7% |
| aliea | 363 | 15 | 4.1% |
| sapn | 310 | 18 | 5.8% |
| SFTRF | 191 | 120 | 62.8% |
| Landes | 111 | 0 | 0.0% |
| ALIS | 42 | 28 | 66.7% |
| Alicorne | 20 | 0 | 0.0% |
| ATMB | 10 | 0 | 0.0% |

## Representative pair sample (spec-requested format)

16 pairs: worst undercuts spread across operators, plus a few consistent (non-undercut) pairs for contrast.

| Operator | From | To | Direct € (cl.1) | Graph shortest path € | Diff | Hops via | Classification |
|---|---|---|---|---|---|---|---|
| sanef | MONT-CHOISY | DORMANS | 5.60 | 1.30 | -€4.30 | REIMS SUD | itinerary-bound (graph undercuts direct by 76.8%) |
| sanef | DORMANS | MONT-CHOISY | 5.60 | 1.30 | -€4.30 | REIMS SUD | itinerary-bound (graph undercuts direct by 76.8%) |
| sanef | CHARMONT-SOUS-BARBUISE | DORMANS | 13.20 | 3.60 | -€9.60 | VATRY → REIMS SUD | itinerary-bound (graph undercuts direct by 72.7%) |
| escota | Puget-Ville | Pertuis | 14.30 | 4.10 | -€10.20 | Aix (A51) | itinerary-bound (graph undercuts direct by 71.3%) |
| escota | Pertuis | Puget-Ville | 14.30 | 4.10 | -€10.20 | Aix (A51) | itinerary-bound (graph undercuts direct by 71.3%) |
| escota | Puget-Ville | St-Paul-lez-Durance | 16.90 | 6.60 | -€10.30 | Aix (A51) → Pertuis | itinerary-bound (graph undercuts direct by 60.9%) |
| APRR | LA COTIERE | MACON SUD | 25.60 | 10.20 | -€15.40 | PEROUGES → MACON NORD | itinerary-bound (graph undercuts direct by 60.2%) |
| APRR | MACON SUD | LA COTIERE | 25.60 | 10.20 | -€15.40 | MACON NORD → PEROUGES | itinerary-bound (graph undercuts direct by 60.2%) |
| APRR | BELLEVILLE S/SAONE | LA COTIERE | 27.20 | 12.10 | -€15.10 | MACON NORD → PEROUGES | itinerary-bound (graph undercuts direct by 55.5%) |
| Cofiroute | COURTENAY | GONDREVILLE LA FRANCHE NORD | 8.00 | 4.40 | -€3.60 | SAVIGNY SUR CLAIRIS | itinerary-bound (graph undercuts direct by 45.0%) |
| Cofiroute | GONDREVILLE LA FRANCHE NORD | COURTENAY | 8.00 | 4.40 | -€3.60 | SAVIGNY SUR CLAIRIS | itinerary-bound (graph undercuts direct by 45.0%) |
| ALIS | Barriere de peage du Roumois A13 | Alençon | 34.80 | 19.30 | -€15.50 | Brionne → Bernay → Orbec → Sées | itinerary-bound (graph undercuts direct by 44.5%) |
| ALIS | Alençon | Barriere de peage du Roumois A13 | 34.80 | 19.30 | -€15.50 | Sées → Orbec → Bernay → Brionne | itinerary-bound (graph undercuts direct by 44.5%) |
| ASFC | Manzat | Péage de Viry | 99.20 | 99.20 | €0.00 | (direct edge is already the graph optimum) | consistent |
| ASFC | Péage de Viry | Manzat | 99.20 | 99.20 | €0.00 | (direct edge is already the graph optimum) | consistent |
| ASFC | Eloise | Manzat | 94.80 | 94.80 | €0.00 | (direct edge is already the graph optimum) | consistent |

## Interpretation

48849 of 56480 same-operator direct edges (86.5%) are far above the spec's 5% threshold. **Mechanical result: NO-GO: adopt corridor enumeration (or equivalent graph fix, see below).**

**Root cause:** `od_pairs.csv` prices are per-journey fares (usually cheaper per km for longer through-journeys - degressive tariffs), not per-segment tolls that sum additively. Treating every row as a freely chainable graph edge, as IMPLEMENTATION_PLAN.md's current Phase 1c item literally specifies, lets Dijkstra "discover" fake cheap routes by hopping through intermediate gates that a real driver would have to physically exit and re-enter to achieve - at a cost the model does not charge. The scale here (86.5% overall, >55% in every operator with more than a handful of gates) rules out corner-case rounding noise; this is systematic.

**Two candidate fixes, for human sign-off before Phase 1c is scoped (this is not a decision this analysis makes unilaterally):**

1. **Spec's stated fallback - corridor enumeration.** Generate K plausible corridors from OSRM geometry, price each by decomposing into the correct sequence of *physically adjacent* concession legs (never arbitrary chaining), rank by generalised cost. Matches `iterative-tumbling-lecun.md`'s own stated mitigation; larger scope change, touches most of the remaining plan.
2. **Constrain the virtual-edge graph (conjecture, not spec-authorised) - forbid same-operator toll-edge chaining.** Within one operator's network, only ever use the single direct `od_pairs` edge for entry/exit gate pair A→C; never combine two same-operator toll edges through an intermediate gate. Cross-operator boundary edges (Phase 2c) are unaffected and still combine normally, since crossing operators genuinely requires a real network handoff. This keeps the Dijkstra architecture and is a smaller change, but needs verifying that it does not also suppress *legitimate* same-operator route choices (e.g. genuine alternative physical carriageways within one operator's network) - not yet checked here.

Do not proceed with Phase 1c's overlay graph as currently scoped until one of these (or another fix) is chosen; the finding is filed as a new blocking item in IMPLEMENTATION_PLAN.md ahead of the existing Phase 1c items.

