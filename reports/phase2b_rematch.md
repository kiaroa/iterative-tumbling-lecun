# Phase 2b — Blank-endpoint row re-match

326 blank gare_id endpoints found across `od_pairs.csv` (163 blank `to_gare_id` + 163 blank `from_gare_id`), spanning 2 operators. Every endpoint below carries exactly one of four named resolutions, assigned by `tollroute.etl.rematch_blank_ids.resolve_endpoint` — none applied silently.

**Conjecture flagged:** the coordinate-proximity tolerance (25% relative / 5 km absolute, see module docstring) is pattern-fitted, not sourced from an authoritative document, and is unexercised by this dataset's single name collision (identical coordinates on both candidates).

## Overall tally

| resolution | count |
|---|---|
| matched | 326 |
| drop | 0 |
| **total** | **326** |

## Per-operator tally (drop counts)

| operator | matched | drop | total |
|---|---|---|---|
| APRR | 324 | 0 | 324 |
| aliea | 2 | 0 | 2 |

## Rule usage

| rule | count |
|---|---|
| canonical_name_exact_match | 326 |

## Named rules (priority order)

1. `canonical_name_exact_match` — exactly one gate's normalised `canonical_name` equals the blank endpoint's recorded name.
2. `alias_name_match` — no `canonical_name` match, but exactly one gate lists the name in its `all_names` alias list.
3. `coordinate_proximity_disambiguation` — among name-matched candidates, the one whose haversine distance from the row's known endpoint is a materially closer fit to the row's `distance_km`.
4. `operator_tag_disambiguation` — among name-matched candidates, the one whose `gare_master.operators` tags include the row's operator, when unique.
5. `default_unresolved` — none of the above broke the tie: dropped.

## Price plausibility spot-check (matched rows only)

Phase 2a found no bulk, machine-readable French motorway tariff source and two direct `WebFetch` attempts against `autoroutes.fr` failed on a TLS certificate error in this environment — the same constraint applies here, so re-matched prices are spot-checked by class1 EUR/km rate plausibility rather than against a live operator calculator.

326 matched rows with a class1 price and distance: rate ranges 8.02-14.58 c/km (mean 11.87 c/km), a tight, positive, outlier-free cluster with no zero or negative rates — consistent with genuine tariffs rather than a mismatch artefact (a wrong gare_id match would typically produce a wildly wrong distance and hence an outlier rate). **Conjecture:** general knowledge suggests typical French autoroute class-1 tariffs run roughly 8-15 c/km; this is not a verified source for this specific spot-check, but the observed range sits inside it.

## Sample endpoints per resolution

### matched

| operator | endpoint | name | matched gare_id | rule | reason |
|---|---|---|---|---|---|
| APRR | to_gare_id | MONTLUCON | 551 | canonical_name_exact_match | 'MONTLUCON' matches gare_id 551's canonical_name exactly and no other gate's canonical_name matches: the strongest available name signal. |
| APRR | to_gare_id | MONTLUCON | 551 | canonical_name_exact_match | 'MONTLUCON' matches gare_id 551's canonical_name exactly and no other gate's canonical_name matches: the strongest available name signal. |
| APRR | to_gare_id | MONTLUCON | 551 | canonical_name_exact_match | 'MONTLUCON' matches gare_id 551's canonical_name exactly and no other gate's canonical_name matches: the strongest available name signal. |
| APRR | to_gare_id | MONTLUCON | 551 | canonical_name_exact_match | 'MONTLUCON' matches gare_id 551's canonical_name exactly and no other gate's canonical_name matches: the strongest available name signal. |
| APRR | to_gare_id | MONTLUCON | 551 | canonical_name_exact_match | 'MONTLUCON' matches gare_id 551's canonical_name exactly and no other gate's canonical_name matches: the strongest available name signal. |

### drop

None.

