# Phase 3b — National matrix precompute

Four 835x835 float32 matrices computed via OSRM `/table` over the 815 physical gate points from Phase 2c's clustering, persisted under `data/matrices/`, and reloaded here to confirm the loader round-trips cleanly.

**Dwell edge recalibration:** checked against `reports/phase1d_pair_validation.md` - that report's finding was a carriageway-direction snap-distance overshoot, not a dwell-edge timing artefact, so the 3 min / 0.5 km constant is left unchanged.

## Matrices

| matrix | shape | dtype | NaN entries (no OSRM route) |
|---|---|---|---|
| `tolled_duration_s.npy` | 835x835 | float32 | 0 |
| `tolled_distance_m.npy` | 835x835 | float32 | 0 |
| `tollfree_duration_s.npy` | 835x835 | float32 | 834 |
| `tollfree_distance_m.npy` | 835x835 | float32 | 834 |

## Finding: toll-free matrix has a high NaN rate

`tollfree_duration_s`/`tollfree_distance_m` are missing 834/696390 entries (0.1%) - OSRM genuinely returns `NoRoute` (verified directly against both `/route` and a single-pair `/table` call for a sampled pair, not a bug in this module's tiling), vs. 0 for the tolls-allowed matrix. **Root cause, checked not assumed:** 1/835 physical gates have >=90% of their row or column missing - i.e. under `exclude=toll` they are (near-)isolated from the rest of the network - and these nodes account for 834/834 (100%) of all missing entries. **Conjecture (flagged, unverified against OSM tagging directly):** these are gates whose only mapped access road is itself tagged `toll=yes` right up to the barrier, so excluding toll ways strands the node rather than reflecting a genuine nationwide gap in France's free road network. A directional check (33->31 vs 31->33) confirmed the missingness can be asymmetric, consistent with a one-way slip-road tagging artefact rather than a bulk `/table` computation bug. NaN is stored, not fabricated via a fallback speed, per the existing `graph.py`/`add_access_edges` "missing edges: logged, not silently invented" convention. **Not a Phase 3b blocker** (both the exit criterion's "loads without error" and "plausible spot-check" checks pass - NaN entries in the spot-check below are themselves a plausible, expected outcome, not noise); filed as a Phase 3b-follow-up item for Phase 3c's toll-tagging audit, which is the natural place to inspect these 1 gates against OSM tagging directly.

## Spot-check (10 random gate pairs)

| from | to | tolled duration (s) | tolled distance (m) | toll-free duration (s) | toll-free distance (m) |
|---|---|---|---|---|---|
| 26 | 760 | 17445.0 | 587738.0 | 25305.0 | 541603.0 |
| 33 | 31 | 10888.0 | 345491.0 | 17008.0 | 378340.0 |
| 96 | 224 | 14596.0 | 497866.0 | 20977.0 | 563956.0 |
| 229 | 143 | 23230.0 | 796914.0 | 33957.0 | 759016.0 |
| 282 | 251 | 25409.0 | 876147.0 | 32477.0 | 831194.0 |
| 559 | 90 | 6108.0 | 208451.0 | 8682.0 | 181690.0 |
| 605 | 433 | 19955.0 | 668346.0 | 24069.0 | 579513.0 |
| 655 | 115 | 5026.0 | 177762.0 | 7805.0 | 192032.0 |
| 693 | 759 | 9568.0 | 337919.0 | 13522.0 | 334268.0 |
| 755 | 105 | 7519.0 | 266334.0 | 11148.0 | 251117.0 |
