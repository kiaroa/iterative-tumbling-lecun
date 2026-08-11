# Phase 2c — Free-flow classification and coordinate-less gate quarantine

Sibling of `phase2c_clustering.md`. Classifies the spec-named free-flow (barrierless) corridors and quarantines the gates that carry no coordinates.

## Free-flow corridors

| corridor | gates in gare_master | od_pairs rows | self-loops | present? | override needed? |
|---|---|---|---|---|---|
| A79 | 2 | 593 | 0 | yes | no |
| A13 | 20 | 260 | 0 | yes | no |
| A14 | 2 | 5 | 5 | yes | no |

- **A79** (gates [263, 264]): present in the fare matrix as conventional gate-to-gate rows; no override needed.
- **A13** (gates [123, 143, 150, 158, 172, 174, 225, 230, 274, 357, 361, 397, 402, 645, 647, 656, 697, 846, 885, 886]): present in the fare matrix as conventional gate-to-gate rows; no override needed.
- **A14** (gates [205, 547]): present; 5 of its fare rows are self-loops (from_gare_id == to_gare_id): a free-flow single-gantry flat fee, not an entry->exit gate pair. The graph builder must treat a self-loop toll edge as a flat-fee section edge, not a zero-length no-op — see the Phase 2c follow-up item.

**Decision:** every free-flow corridor is present in `od_pairs`, so the `freeflow_override` table is created but left **empty** — no flat-fee override is required. A14's self-loop representation is flagged to the graph builder as a follow-up item.

*Checked, not assumed:* blank `distance_km` is not a free-flow signal (61% of all rows omit it, whole operators omit it wholesale); the self-loop pattern is the distinctive marker (all five self-loops in the file are A14/sapn).

## Coordinate-less gates → suspect_gates

| gare_id | name | routes | operators | affected od_pairs |
|---|---|---|---|---|
| 1 | A 20 limite de concession | A89 | ASFC | 24 |
| 210 | CHARMONT (LIM.CONC) | — | APRR | aliea | 194 |
| 243 | Clermont-Ferrand limite de concession | — | ASFC | 36 |

All 3 are 'limite de concession' administrative boundary markers, not physical barriers — quarantined into `suspect_gates` rather than geocoded. **Conjecture flagged:** if a later phase finds a real barrier behind one of these names it should be geocoded and removed from the table.

