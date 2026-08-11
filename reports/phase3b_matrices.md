# Phase 3b — National matrix precompute

Four 815x815 float32 matrices computed via OSRM `/table` over the 815 physical gate points from Phase 2c's clustering, persisted under `data/matrices/`, and reloaded here to confirm the loader round-trips cleanly.

**Dwell edge recalibration:** checked against `reports/phase1d_pair_validation.md` - that report's finding was a carriageway-direction snap-distance overshoot, not a dwell-edge timing artefact, so the 3 min / 0.5 km constant is left unchanged.

## Matrices

| matrix | shape | dtype | NaN entries (no OSRM route) |
|---|---|---|---|
| `tolled_duration_s.npy` | 815x815 | float32 | 0 |
| `tolled_distance_m.npy` | 815x815 | float32 | 0 |
| `tollfree_duration_s.npy` | 815x815 | float32 | 315841 |
| `tollfree_distance_m.npy` | 815x815 | float32 | 315841 |

## Finding: toll-free matrix has a high NaN rate

`tollfree_duration_s`/`tollfree_distance_m` are missing 315841/663410 entries (47.6%) - OSRM genuinely returns `NoRoute` (verified directly against both `/route` and a single-pair `/table` call for a sampled pair, not a bug in this module's tiling), vs. 0 for the tolls-allowed matrix. **Root cause, checked not assumed:** 333/815 physical gates have >=90% of their row or column missing - i.e. under `exclude=toll` they are (near-)isolated from the rest of the network - and these nodes account for 315841/315841 (100%) of all missing entries. **Conjecture (flagged, unverified against OSM tagging directly):** these are gates whose only mapped access road is itself tagged `toll=yes` right up to the barrier, so excluding toll ways strands the node rather than reflecting a genuine nationwide gap in France's free road network. A directional check (33->31 vs 31->33) confirmed the missingness can be asymmetric, consistent with a one-way slip-road tagging artefact rather than a bulk `/table` computation bug. NaN is stored, not fabricated via a fallback speed, per the existing `graph.py`/`add_access_edges` "missing edges: logged, not silently invented" convention. **Not a Phase 3b blocker** (both the exit criterion's "loads without error" and "plausible spot-check" checks pass - NaN entries in the spot-check below are themselves a plausible, expected outcome, not noise); filed as a Phase 3b-follow-up item for Phase 3c's toll-tagging audit, which is the natural place to inspect these 333 gates against OSM tagging directly.

## Spot-check (10 random gate pairs)

| from | to | tolled duration (s) | tolled distance (m) | toll-free duration (s) | toll-free distance (m) |
|---|---|---|---|---|---|
| 26 | 760 | 22449.1 | 621999.0 | 28717.2 | 560400.1 |
| 33 | 31 | 777.5 | 18774.9 | nan | nan |
| 96 | 224 | 24116.4 | 634947.4 | 32549.7 | 678330.6 |
| 229 | 143 | 24585.4 | 620117.8 | nan | nan |
| 282 | 251 | 21520.6 | 587079.3 | nan | nan |
| 559 | 90 | 20680.5 | 535178.5 | 27990.2 | 448545.3 |
| 605 | 433 | 22484.1 | 619183.1 | 24027.5 | 551410.1 |
| 655 | 115 | 24267.1 | 669468.2 | 36194.5 | 689246.0 |
| 693 | 759 | 36564.4 | 982531.2 | nan | nan |
| 755 | 105 | 17403.5 | 491323.2 | nan | nan |
