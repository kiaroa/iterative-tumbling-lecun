# Phase 2c — Physical gate clustering and transfer edges

953 geocoded gates collapse to **815 physical points** by exact-coordinate grouping (131 points bundle more than one gare_id). Every co-located (<= 100 m) gate pair is typed as exactly one transfer edge — none applied silently.

**Conjecture flagged:** exact-coordinate collapse trusts the geocoder's identical-coordinate assignment as the co-location signal; the 100 m transfer radius and 'disjoint operators = boundary' rule are fitted to this dataset (ABLIS is the one manually-verified anchor). Phase 2d's coverage audit and Phase 3c's snap-quality curation are where a wrong call surfaces.

## Clustering

| metric | value |
|---|---|
| geocoded gates | 953 |
| physical points | 815 |
| multi-gate physical points | 131 |
| gates without coordinates (deferred to suspect_gates) | 3 |

## Transfer edges

| type | count | dwell |
|---|---|---|
| boundary | 110 | free, zero-time |
| exit_reentry | 71 | 3 min / 0.5 km |
| **total** | **181** | |

## ABLIS cross-operator boundary (manual verification anchor)

gare_id 4 (Ablis) <-> 5 (ABLIS): **boundary**, 0 m apart. gates 0 m apart carry disjoint operator tags (['ASFC'] vs ['Cofiroute']): a genuine concession boundary — free, zero-time, and the only permitted connector between two different-operator toll edges.

## Sample transfer edges per type

### boundary

| a | b | distance (m) | reason |
|---|---|---|---|
| Ablis (4) | ABLIS (5) | 0 | gates 0 m apart carry disjoint operator tags (['ASFC'] vs ['Cofiroute']): a genuine concession boundary — free, zero-time, and the only permitted connector between two different-operator toll edges. |
| Alençon nord (23) | ALENCON NORD (24) | 0 | gates 0 m apart carry disjoint operator tags (['ASFC'] vs ['Cofiroute']): a genuine concession boundary — free, zero-time, and the only permitted connector between two different-operator toll edges. |
| Alençon sud (25) | ALENCON SUD (26) | 0 | gates 0 m apart carry disjoint operator tags (['ASFC'] vs ['Cofiroute']): a genuine concession boundary — free, zero-time, and the only permitted connector between two different-operator toll edges. |
| ALLAINES (27) | JANVILLE (ALLAINES) (363) | 0 | gates 0 m apart carry disjoint operator tags (['APRR', 'ASFC', 'aliea'] vs ['Cofiroute']): a genuine concession boundary — free, zero-time, and the only permitted connector between two different-operator toll edges. |
| Ambérieu (31) | AMBERIEU EN BUGEY (32) | 0 | gates 0 m apart carry disjoint operator tags (['APRR', 'ASFC', 'aliea'] vs ['Cofiroute']): a genuine concession boundary — free, zero-time, and the only permitted connector between two different-operator toll edges. |

### exit_reentry

| a | b | distance (m) | reason |
|---|---|---|---|
| ALLONZIER (29) | ST MARTIN BELLEVUE A41 N (815) | 46 | gates 46 m apart share operator tag(s) (['AREA']): same concession — a 3 min / 0.5 km exit/re-entry dwell, excluded as a toll-edge connector. |
| ANCENIS (40) | ANGERS (43) | 0 | gates 0 m apart share operator tag(s) (['Cofiroute']): same concession — a 3 min / 0.5 km exit/re-entry dwell, excluded as a toll-edge connector. |
| ANCENIS (40) | NANTES (579) | 0 | gates 0 m apart share operator tag(s) (['Cofiroute']): same concession — a 3 min / 0.5 km exit/re-entry dwell, excluded as a toll-edge connector. |
| Andrézieux-Bouthéon nord (41) | Andrézieux-Bouthéon sud (42) | 0 | gates 0 m apart share operator tag(s) (['ASFC']): same concession — a 3 min / 0.5 km exit/re-entry dwell, excluded as a toll-edge connector. |
| ANGERS (43) | NANTES (579) | 0 | gates 0 m apart share operator tag(s) (['Cofiroute']): same concession — a 3 min / 0.5 km exit/re-entry dwell, excluded as a toll-edge connector. |

