# Phase 2b — Zero-price row disposition

551 zero-price (`class1 == 0`) rows found across `od_pairs.csv`, spanning 6 operators. Every row below carries exactly one of three named dispositions, assigned by `tollroute.etl.remediate_zero_price.classify_zero_price_row` — none applied silently.

**Conjecture flagged:** the 8 km proximity threshold and the 'bifurcation' structural-name keyword are pattern-fitted to this dataset, not sourced from an authoritative document (see module docstring). Phase 2d's coverage audit and Phase 3c's national distance-error validation are where a wrong call here would surface and get corrected.

## Overall tally

| disposition | count |
|---|---|
| free_transfer | 6 |
| free_section | 307 |
| drop | 238 |
| **total** | **551** |

## Per-operator tally

| operator | free_section | free_transfer | drop | total |
|---|---|---|---|---|
| APRR | 4 | 4 | 0 | 8 |
| ASFC | 276 | 0 | 188 | 464 |
| Alicorne | 2 | 0 | 4 | 6 |
| Cofiroute | 0 | 2 | 0 | 2 |
| Landes | 7 | 0 | 38 | 45 |
| escota | 18 | 0 | 8 | 26 |

## Named rules (priority order)

1. `operator_boundary_short_hop` -> `free_transfer` — endpoints carry different `gare_master.operators` tags AND are <= 8 km apart (haversine).
2. `structural_node_name` -> `free_section` — either endpoint name contains 'bifurcation' (a motorway fork/merge node, never a priced barrier), any distance.
3. `short_physical_hop` -> `free_section` — gates <= 8 km apart (haversine, or od_pairs.csv `distance_km` where coordinates are unavailable).
4. `default_no_signal` -> `drop` — none of the above fired.

## Sample rows per disposition

### free_transfer

| operator | from | to | distance (km) | rule | reason |
|---|---|---|---|---|---|
| APRR | FEILLENS (300) | MACON CENTRE (493) | 2.41 | operator_boundary_short_hop | endpoints carry different gare_master operator tags (['APRR', 'ASFC', 'Cofiroute', 'aliea'] vs ['APRR', 'ASFC']) and are 2.41 km apart (<= 8 km): treated as a genuine cross-network free hand-off. |
| APRR | MACON CENTRE (493) | FEILLENS (300) | 2.41 | operator_boundary_short_hop | endpoints carry different gare_master operator tags (['APRR', 'ASFC'] vs ['APRR', 'ASFC', 'Cofiroute', 'aliea']) and are 2.41 km apart (<= 8 km): treated as a genuine cross-network free hand-off. |
| APRR | MACON CENTRE (493) | REPLONGES (683) | 5.20 | operator_boundary_short_hop | endpoints carry different gare_master operator tags (['APRR', 'ASFC'] vs ['APRR', 'ASFC', 'Cofiroute', 'aliea']) and are 5.20 km apart (<= 8 km): treated as a genuine cross-network free hand-off. |
| APRR | REPLONGES (683) | MACON CENTRE (493) | 5.20 | operator_boundary_short_hop | endpoints carry different gare_master operator tags (['APRR', 'ASFC', 'Cofiroute', 'aliea'] vs ['APRR', 'ASFC']) and are 5.20 km apart (<= 8 km): treated as a genuine cross-network free hand-off. |
| Cofiroute | SAINT HILAIRE LES ANDRESIS (718) | SAVIGNY SUR CLAIRIS (755) | 4.73 | operator_boundary_short_hop | endpoints carry different gare_master operator tags (['Cofiroute'] vs ['ASFC', 'Cofiroute']) and are 4.73 km apart (<= 8 km): treated as a genuine cross-network free hand-off. |

### free_section

| operator | from | to | distance (km) | rule | reason |
|---|---|---|---|---|---|
| APRR | BALAN (76) | PEROUGES (637) | 6.25 | short_physical_hop | gates are 6.25 km apart (<= 8 km): consistent with an adjacent-junction or dense local-interchange free connector rather than a discounted long-distance journey. |
| APRR | FEILLENS (300) | REPLONGES (683) | 3.13 | short_physical_hop | gates are 3.13 km apart (<= 8 km): consistent with an adjacent-junction or dense local-interchange free connector rather than a discounted long-distance journey. |
| APRR | PEROUGES (637) | BALAN (76) | 6.25 | short_physical_hop | gates are 6.25 km apart (<= 8 km): consistent with an adjacent-junction or dense local-interchange free connector rather than a discounted long-distance journey. |
| APRR | REPLONGES (683) | FEILLENS (300) | 3.13 | short_physical_hop | gates are 3.13 km apart (<= 8 km): consistent with an adjacent-junction or dense local-interchange free connector rather than a discounted long-distance journey. |
| ASFC | Aire-sur-Adour nord (12) | Aire-sur-Adour sud (13) | 5.36 | short_physical_hop | gates are 5.36 km apart (<= 8 km): consistent with an adjacent-junction or dense local-interchange free connector rather than a discounted long-distance journey. |

### drop

| operator | from | to | distance (km) | rule | reason |
|---|---|---|---|---|---|
| ASFC | Ambarès/St-Loubes (30) | Blaye (136) | 225.91 | default_no_signal | no structural-node name, operator-boundary, or short-physical-hop signal fired; no positive evidence the zero price is real rather than missing/unrecorded data, so the row is excluded from the graph rather than trusted as a free edge. |
| ASFC | Ambarès/St-Loubes (30) | Libourne/St-Antoine (477) | 18.68 | default_no_signal | no structural-node name, operator-boundary, or short-physical-hop signal fired; no positive evidence the zero price is real rather than missing/unrecorded data, so the row is excluded from the graph rather than trusted as a free edge. |
| ASFC | Ambes (33) | Blaye (136) | 223.91 | default_no_signal | no structural-node name, operator-boundary, or short-physical-hop signal fired; no positive evidence the zero price is real rather than missing/unrecorded data, so the row is excluded from the graph rather than trusted as a free edge. |
| ASFC | Ambes (33) | Libourne/St-Antoine (477) | 16.73 | default_no_signal | no structural-node name, operator-boundary, or short-physical-hop signal fired; no positive evidence the zero price is real rather than missing/unrecorded data, so the row is excluded from the graph rather than trusted as a free edge. |
| ASFC | Bd d’Estienne d’Orves (87) | Gatignolle (329) | 52.67 | default_no_signal | no structural-node name, operator-boundary, or short-physical-hop signal fired; no positive evidence the zero price is real rather than missing/unrecorded data, so the row is excluded from the graph rather than trusted as a free edge. |

