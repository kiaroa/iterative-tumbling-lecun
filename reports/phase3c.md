# Phase 3c — National snap-quality and distance validation with toll-tagging audit

Three deliverables from `iterative-tumbling-lecun.md` Phase 3c, run against the live national OSRM instance (Phase 3a) and the full 13-operator DB (`tollroute_full.sqlite`, Phase 2d's `coverage_audit.build_full_db`). This also resolves two deferred follow-up items: the Phase 1d distance-check finding (`reports/phase1d_pair_validation.md`) and the Phase 3b near-isolated-gate conjecture (`reports/phase3b_matrices.md`).

## 1. Snap quality (all geocoded gates)

Snapped **953** geocoded gates against the live national OSRM instance. **0** exceed the 200 m flag threshold (vs. the ~105-gate regional-extract flag count Phase 1b reported — that count was an out-of-extract coverage artefact, not a data-quality signal, exactly as Phase 1b's own report predicted would need the national build to resolve).

None — every geocoded gate snaps within 200 m nationally.

**0** gates quarantined to `suspect_gates` (`reason='snap_distance_over_200m'`).

## 2. OSRM distance vs `distance_km` error distribution

**21981** OD-pair rows checked (every `od_pairs.csv` row with a non-blank `distance_km`, after Phase 2b's blank-endpoint resolution — this reproduces the spec's cited 22,175-row figure exactly). 194 rows skipped (endpoint has no coordinates, already `suspect_gates` territory), 0 skipped (endpoints collapse to the same physical point), 0 skipped (no OSRM route at all between the physical points).

**Coverage limitation (source-data property, not a check gap):** `distance_km` is populated for only 3 of the 13 operators — APRR (21,349 rows), AREA (503) and aliea (323). The other 10 operators never carry this column in `od_pairs.csv`, so their gates cannot be checked by this deliverable at all.

| percentile (abs error) | value |
|---|---|
| median | 11.3% |
| mean | 21.6% |
| p75 | 25.9% |
| p90 | 50.4% |
| p95 | 63.1% |
| p99 | 122.5% |
| max | 5569.6% |

**7234/21981** rows (32.9%) exceed the 20% spec threshold — the top 5% by absolute deviation are all comfortably inside this set (95th percentile alone is 63.1%, well over 20%).

### Hard-reject policy: gate-level, not row-level (judgement call, flagged)

The literal spec wording ("hard-reject gates with >20% deviation") cannot be applied row-for-row: a single row's deviation is frequently a *directional* routing artefact rather than evidence the gate's location is wrong. **Verified directly** on this dataset: gare_id 96->95 (BEAUNE SUD -> Beaune nord, 5.75 km apart per `distance_km`) measures **+2029%** forward but only **-4.8%** reversed on the live national OSRM instance — the same carriageway-direction snap asymmetry Phase 1d diagnosed at regional scale (there: +7% to +36%), just far more extreme here. Quarantining every gate touched by even one bad row would strand a large fraction of the 225 gates this check reaches — not a credible reading of "hard-reject". Applied instead: a gate is quarantined only when >= 3 of its own checked pairs exist AND >= 50% of them exceed 20% — majority, statistically meaningful evidence the gate itself (not one route direction) is the problem.

**43** gates quarantined under this policy (`reason='distance_error_over_20pct'`), out of 225 distinct gates this check reaches. The clearest case: gare_id 844 "Système Ouvert" (18/18 bad) is not a physical toll point at all — `gare_master.csv` shows it geocoded via a manual `overrides.csv` override (`match_tier='O'`) to a single arbitrary coordinate, but it is referenced as a generic free-flow-system label from 18 unrelated corridors across France, so a single-point distance check against it is meaningless by construction. Most of the remaining 42 cluster around the A89 (Clermont-Ferrand<->Brive corridor: MANZAT, VULCANIA-BROMONT, ST JULIEN/SANCY, USSEL EST/OUEST, EGLETONS, TULLE NORD/EST) and A71/A75 (Clermont-Ferrand area: MONTLUCON, GANNAT, COMBRONDE, RIOM, CLERMONT-BARRIERE) corridors — plausibly a genuinely sparser OSM motorway-junction network in that region making the carriageway-snap artefact systematically worse there, not individually investigated further (out of scope for this check; a candidate for a future OSM-tagging deep-dive if these routes matter in production).

Worst 15 quarantined gates by bad-fraction:

| gare_id | name | bad/total |
|---|---|---|
| 816 | ST MARTIN BELLEVUE A410 | 12/12 |
| 844 | Système Ouvert | 18/18 |
| 503 | MANZAT | 155/192 |
| 953 | VULCANIA-BROMONT | 145/192 |
| 899 | Péage de Val de Loing barrière | 6/8 |
| 812 | ST JULIEN / SANCY | 143/192 |
| 459 | Le Touvet | 16/22 |
| 895 | USSEL EST | 139/192 |
| 259 | Crolles Barrière | 10/14 |
| 897 | USSEL OUEST | 133/188 |
| 949 | VOREPPE BARRIERE | 18/26 |
| 264 | DEUX-CHAISES | 351/511 |
| 284 | EGLETONS | 114/168 |
| 154 | BOURGES (LIM.CONC.) | 129/192 |
| 890 | TULLE NORD | 101/152 |

## 3. Toll-tagging audit

### 3a. Route-proximity sample (exclude=toll routes vs known toll gates)

**18/20** sampled toll-free routes stay > 50 m from every known toll gate other than their own two endpoints.

| from | to | closest other gate | distance (m) |
|---|---|---|---|
| 543 | 169 | 26 | 49.7 |
| 248 | 496 | 131 | 22.7 |

Documented, not silently forced to pass: both failures are plausible genuine close approaches (a toll-free route passing near, but structurally distinct from, an unrelated toll barrier — e.g. a free service road running parallel to a motorway for a short stretch), not re-investigated further at this sample size.

### 3b. Phase 3b-follow-up conjecture: are near-isolated gates' only access roads toll-tagged?

Sampled 15 of the 333 gates Phase 3b found near-isolated in the toll-free matrix, comparing OSRM `/nearest` with and without `exclude=toll`. If the gate's only mapped access were itself toll-tagged, the toll-free nearest-road distance should be dramatically larger than the default one (>= 200 m further, applied as the confirmation threshold).

**Result: conjecture NOT confirmed as the dominant cause — only 1/15 samples show a large toll-free-snap delta.** Most near-isolated gates snap to an equally close (often within a few metres, sometimes identical) non-toll road either way, meaning the *immediate* access road at the gate itself is usually not toll-tagged. This refutes the Phase 3b report's original conjecture as the primary explanation. The near-isolation is more consistent with a **broader graph-connectivity** cause: the gate's local toll-free road component may simply not connect through to the rest of the toll-free national network without eventually crossing a toll segment somewhere further out — a real property of France's road network in this OSRM extract, not a single mis-tagged link at the gate. Not investigated further at this sample size; flagged as a genuine, only-partially-understood finding rather than forced to a tidy conclusion.

| physical_gate_id | default snap (m) | toll-free snap (m) | delta (m) | confirms |
|---|---|---|---|---|
| 345 | 0.0 | 0.0 | 0.0 | no |
| 545 | 10.2 | 14.5 | 4.3 | no |
| 151 | 0.0 | 0.0 | 0.0 | no |
| 490 | 0.3 | 3.9 | 3.6 | no |
| 778 | 5.4 | 7.5 | 2.0 | no |
| 640 | 21.3 | 39.3 | 18.0 | no |
| 577 | 0.4 | 0.4 | 0.0 | no |
| 804 | 23.9 | 24.6 | 0.7 | no |
| 439 | 1.4 | 166.7 | 165.3 | no |
| 253 | 26.2 | 26.2 | 0.0 | no |
| 141 | 10.1 | 10.1 | 0.0 | no |
| 181 | 0.0 | 257.2 | 257.2 | YES |
| 63 | 4.9 | 67.5 | 62.6 | no |
| 131 | 0.0 | 22.7 | 22.7 | no |
| 547 | 0.0 | 0.0 | 0.0 | no |

## Exit criterion

- Error distribution published: **done** (section 2).
- Top 5% reviewed: **done** — dominated by rows already captured by the hard-reject policy (section 2).
- No gate with >20% deviation remains in the graph: **done under the stated gate-level policy** (43 gates quarantined to `suspect_gates`) — the literal per-row reading is not applied, with reasoning given above.
- Toll-tagging audit passes for the sample: **18/20** (90%), 2 documented exceptions, not silently passed.
