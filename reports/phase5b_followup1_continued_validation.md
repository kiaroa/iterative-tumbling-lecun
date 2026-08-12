# Phase 5b-follow-up-1-continued — flagship-criterion validation

**Fix shipped this iteration:** `tollroute.etl.access_anchors` rewritten to (1) actually walk
backward along the real plain route's geometry from a reference city to the gate (its own
docstring always claimed this; the shipped Phase 5b-follow-up-1 code instead radiated outward
from an undirected `/nearest`, which picks wrong-carriageway candidates on divided motorways -
verified directly: Fleury-en-Bière's nearest `/nearest` candidate had a 30 km apron via that
method, vs ~350-600 m via the route-geometry walk) and (2) validate reachability separately
per direction (entry: reference->gate; exit: gate->reference) rather than reusing one
exit-direction-only check for both, which was found to silently break entry access edges for
7 of 8 randomly-sampled anchors from the original 67-anchor precompute.

## Anchor coverage, before vs after

| | Phase 5b-follow-up-1 (single, exit-direction-only) | This iteration (direction-split) |
|---|---|---|
| Anchors found | 67 / 256 needed (exit only; entry unvalidated) | entry 240/242, exit 255/255 |
| Fleury-en-Bière (302/303) | no anchor (gapped) | entry 508.5 m apron, exit 601.6 m apron |

## `analysis/phase5b_plausibility.py`'s 10 routes: `fastest` vs `baseline` duration gap

Re-ran against a live `tollroute.api` instance after recomputing anchors. Paris->Lyon and
Paris->Bordeaux are this item's own flagship pair (spec: this item's "done when").

| Route | Gap before (Phase 5b-follow-up-1, from its own validation report) | Gap after (this iteration) |
|---|---|---|
| Paris -> Lyon | 14.8% | **11.5%** |
| Paris -> Bordeaux | 13.4% | 13.4% (unchanged) |

**Flagship acceptance criterion met**: Paris->Lyon's gap (11.5%) is now materially closer to -
and in fact better than - Paris->Bordeaux's ~13% benchmark the criterion named. Paris->Lyon's
`fastest` route no longer needs Fleury-en-Bière specifically to clear the bar: Dijkstra now
picks Nemours (gare_id 585, also on the A6, ~17 km further south) over Fleury even though
Fleury has a working anchor in both directions - a real routing outcome once the true
toll-free-reachable cost of *both* candidates is available, not a sign the fix didn't work.
Paris->Bordeaux's gap is unchanged because its own entry gate/corridor wasn't affected by this
fix (not investigated further here - out of this item's scope).

## Full 10-route gap table (this iteration, for reference)

| Route | fastest (min) | baseline (min) | gap |
|---|---|---|---|
| Paris -> Lyon | 331.8 | 297.7 | 11.5% |
| Paris -> Bordeaux | 417.9 | 368.6 | 13.4% |
| Clermont-Ferrand -> Montpellier | 246.5 | 222.3 | 10.9% |
| Paris -> Lille | 174.1 | 151.1 | 15.2% |
| Paris -> Marseille | 555.1 | 493.2 | 12.6% |
| Nice -> Marseille | 154.1 | 141.8 | 8.7% |
| Bordeaux -> Toulouse | 168.1 | 161.3 | 4.2% |
| Lyon -> Chamonix | 202.3 | 154.8 | 30.7% |
| Strasbourg -> Paris | 325.2 | 305.9 | 6.3% |
| Calais -> Reims | 197.0 | 165.7 | 18.9% |

Raw script output: captured this iteration, not committed (regenerable via
`analysis/phase5b_plausibility.py` against a running `tollroute.api` instance).
