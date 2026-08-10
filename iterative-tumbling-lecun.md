# Toll-minimising route service for France — phased plan

## Context

French motorway tolls are substantial (median fare in our data is €28.20 class 1, max €117.40) and there is often a materially cheaper route that costs only a little more time. No consumer tool answers the actual question a driver has: *is the saving worth the detour?*

We hold two datasets — a 57,378-row fare matrix and a 956-row geocoded toll-gate reference — and want a web service that, given origin, destination and vehicle class, returns route options minimising toll cost, subject to the saving justifying the extra distance/time.

`od_pairs.csv` is kept current by an external update process; no vintage gate is needed in the service.

---

## Data (ground truth, already surveyed)

| File | Rows | What it is |
|---|---|---|
| `od_pairs.csv` | 57,378 | Fare matrix: price per vehicle class for entry gate → exit gate |
| `gare_master.csv` | 956 | Deduplicated, geocoded toll gates (953 have lat/lon; 815 distinct physical points) |

Key facts:
- 13 operators, dirty casing (`sanef`/`ASFC`/`escota`/`aliea`). APRR 21,349 rows; ASFC 18,516; Cofiroute 10,936.
- `distance_km` filled for only 39% of rows (APRR/AREA/aliea only).
- 26,265 rows are **cross-route** — not a per-motorway table.
- 5 rows carry time bands (sapn open barriers).
- 8 columns in `gare_master` are empty placeholders, including `concession_boundary`.

---

## Core architectural decision

France uses **closed tolling**: price depends only on the (entry, exit) gate pair, not on the path driven. Toll cost is **not additive over road segments** — naive shortest-path with per-edge prices is wrong.

**Virtual-edge model:** each fare-matrix row becomes one virtual toll edge. Money cost from `od_pairs`; distance/time from OSRM. This restores additivity and makes Dijkstra valid.

Any road in France may be used — the service is not limited to motorways.

**Graph:** nodes = {origin, destination, ~956 gates} ≈ 1,900. Edges = 57k toll edges + toll-free gate-to-gate edges + access edges. All geometry from OSRM; Python never touches a road segment.

**Node-split:** each gate splits into `_in`/`_out` with a dwell edge (3 min, 0.5 km — calibrated in Phase 1c). Co-located gates from different operators get a free boundary transfer edge (no physical stop). Boundary detection is Phase 2c; Phase 1 is APRR-only so this does not apply.

**Vehicle classes:** one graph structure, one `data` array per class. Class selected at query time by swapping the array.

**Guard rails:** `max_gate_hops = 5`. Alternative must add ≥ 10 km AND ≥ 5 min vs fastest route.

**Missing edges:** silently omitted; gap logged in Phase 2d coverage audit.

**Itinerary-dependence threshold:** if Phase 0 finds >5% of cross-route rows are provably itinerary-bound, adopt corridor enumeration before Phase 1. Below that threshold, proceed with virtual-edge model and document the limitation.

---

## Stack

python3 (3.12.3). FastAPI + uvicorn · stdlib `sqlite3` · numpy `.npy` · `scipy.sparse.csgraph.dijkstra` · `scipy.spatial.cKDTree` · httpx · pytest · Docker for OSRM. pandas for ETL only.

Operator alias map: SQLite table, not source code.

Rejected for now: Postgres/PostGIS, Redis, Celery, any ORM, networkx.

**OSRM:** self-hosted, MLD build (`osrm-partition` + `osrm-customize`). Lua profile: fork `car.lua`, add `toll` to `excludable`, tag `toll=yes` ways to that class.

**OSRM failure:** retry once at 500 ms; return `{"osrm_unavailable": true}` if still down.

**Deployment:** local machine through Phase 3 (54 GB RAM, 222 GB free, Docker 29.7.2). Target decided at Phase 4. Internal tool; private network; no auth.

---

## Phase 0 — Itinerary-dependence test

**Objective.** Confirm or refute the foundational assumption before any code is written.

**Protocol.** Pick 10–20 OD pairs where A→C is reachable via two distinct concession paths. Query `od_pairs` for each: count rows, compare prices against toll sums for each path. If >5% are provably itinerary-bound, adopt corridor enumeration. Otherwise proceed.

**Exit criterion.** Written report: pairs tested, count itinerary-bound, percentage, typed classification, go/no-go recommendation.

**ralph-loop:**
```
/ralph-loop "Run the itinerary-dependence SQL test per iterative-tumbling-lecun.md Phase 0. Select 10-20 OD pairs reachable via two distinct concession paths from od_pairs.csv. Count rows per pair, compare prices against toll sums for each path. Output: count tested, count provably itinerary-bound, percentage, typed classification of each pair, go/no-go for virtual-edge model." --completion-promise "PHASE_0_COMPLETE" --max-iterations 3
```

---

## Phase 1a — OSRM setup

**Objective.** Running OSRM instance with toll-excludable profile on the regional extract.

**Deliverables.**
- Regional OSM extract: Bourgogne-Franche-Comté + Auvergne-Rhône-Alpes.
- OSRM in Docker, MLD build (`osrm-partition` + `osrm-customize`).
- Forked `car.lua` with `toll` added to `excludable` and `toll=yes` ways tagged accordingly.
- Smoke test: `/nearest`, `/route`, and `/table` all return valid responses.

**Exit criterion.** `curl` to `/route` for Dijon→Lyon returns a result; same call with `exclude=toll` returns a different (longer) route.

**ralph-loop:**
```
/ralph-loop "Implement Phase 1a of the toll routing service per iterative-tumbling-lecun.md. Download regional OSM extract (Bourgogne-Franche-Comté + Auvergne-Rhône-Alpes). Build OSRM MLD in Docker using a forked car.lua with toll excludable class. Verify /nearest, /route, and /table endpoints respond. Confirm exclude=toll returns a different route than the default for Dijon-Lyon." --completion-promise "PHASE_1A_COMPLETE" --max-iterations 5
```

---

## Phase 1b — Data loader and gate snapping

**Objective.** CSVs to SQLite; gate positions confirmed on OSRM.

**Deliverables.**
- Loader: both CSVs → SQLite, filtered to APRR. Zero-price rows logged explicitly (not silently dropped) before loading.
- Gate snapping report: OSRM `/nearest` for every APRR gate, recording snap distance. Gates >200 m flagged.
- Verify the 5 named test pairs exist in APRR data and have non-zero prices.

**Test pairs (must be confirmed before Phase 1c):**
1. Dijon → Lyon (A6 vs N6/N7)
2. Paris → Lyon (A6 vs N6 — verify OSRM returns a distinct toll-free route)
3. Clermont-Ferrand → Montpellier (A75 is free motorway — edge case)
4–5. Two medium-distance APRR pairs with parallel N-road — select from top fares in `od_pairs`, confirm OSRM toll-free alternative exists.

**Exit criterion.** SQLite populated; gate snapping report produced; all 5 test pairs present in data with prices; any >200 m snaps listed by name.

**ralph-loop:**
```
/ralph-loop "Implement Phase 1b of the toll routing service per iterative-tumbling-lecun.md. Load od_pairs.csv and gare_master.csv to SQLite filtered to APRR. Log zero-price rows explicitly. Run OSRM /nearest for every APRR gate, record snap distances, flag >200m. Confirm the 5 named test pairs exist in data with non-zero prices and that OSRM returns a distinct toll-free route for each." --completion-promise "PHASE_1B_COMPLETE" --max-iterations 4
```

---

## Phase 1c — Overlay graph and CLI

**Objective.** Working Dijkstra over the overlay graph; CLI returns a route.

**Deliverables.**
- Overlay graph builder: directed, APRR toll edges + toll-free gate-to-gate edges + origin/destination access edges. Dwell edge per gate: 3 min, 0.5 km.
- `scipy.sparse.csgraph.dijkstra` with predecessor re-walk to accumulate toll/time/distance separately.
- CLI: `python3 -m tollroute dijon lyon --class 1` returns at least one route with toll cost, duration, distance.

**Exit criterion.** CLI runs without error for all 5 test pairs; at least one route returned per pair; predecessor re-walk produces separate toll/time/distance totals.

**ralph-loop:**
```
/ralph-loop "Implement Phase 1c of the toll routing service per iterative-tumbling-lecun.md. Build directed overlay graph for APRR: toll edges from od_pairs, toll-free gate-to-gate edges from OSRM, origin/destination access edges. Dwell edge per gate: 3 min 0.5 km. Run scipy Dijkstra, re-walk predecessor path to accumulate toll/time/distance separately. CLI: python3 -m tollroute <origin> <dest> --class 1. Test against all 5 named pairs." --completion-promise "PHASE_1C_COMPLETE" --max-iterations 6
```

---

## Phase 1d — Validation and FastAPI wrapper

**Objective.** Exit criterion met; API contract locked.

**Deliverables.**
- FastAPI wrapper (~30 lines): one endpoint returning the option set.
- For each of the 5 test pairs: direct tolled route matches `od_pairs` price exactly; at least one cheaper alternative satisfies guard rails (≥10 km AND ≥5 min extra); OSRM motorway distance matches `distance_km` within a few percent.

**Exit criterion.** All 5 pairs pass all checks. If OSRM distance check fails for any pair, the geometry layer is broken — stop and investigate before continuing.

**ralph-loop:**
```
/ralph-loop "Implement Phase 1d of the toll routing service per iterative-tumbling-lecun.md. Add FastAPI wrapper (~30 lines, one endpoint). For all 5 named APRR test pairs: verify direct toll matches od_pairs price exactly, at least one cheaper alternative meets guard rails (>=10km AND >=5min extra), OSRM distance matches distance_km within a few percent. All 5 must pass." --completion-promise "PHASE_1D_COMPLETE" --max-iterations 5
```

---

## Phase 2a — External data investigation

**Objective.** Determine whether a machine-readable authoritative tariff source exists before remediating the CSVs.

**Deliverables.**
- Check data.gouv.fr for French motorway tariff tables: assess vintage, licence, completeness.
- Check ASFA for downloadable tariff tables.
- Written report: source found or not found; if found, whether it supersedes `od_pairs.csv` as primary input; recommended action.

**Exit criterion.** Written report produced. Decision recorded in plan before Phase 2b starts.

**ralph-loop:**
```
/ralph-loop "Implement Phase 2a of the toll routing service per iterative-tumbling-lecun.md. Search data.gouv.fr and ASFA website for machine-readable French motorway tariff tables. Assess vintage, licence, completeness. Write a report: source found/not found, whether it supersedes od_pairs.csv, recommended action." --completion-promise "PHASE_2A_COMPLETE" --max-iterations 3
```

---

## Phase 2b — Zero-price and blank-ID remediation

**Objective.** Eliminate the two data hazards most dangerous to Dijkstra.

**Deliverables.**
- **Zero-price rows (551):** cluster by operator and gate pair. Typed disposition for each cluster: (a) keep as free/open-section edge and flag explicitly, (b) convert to free transfer edge, (c) drop as data error. All decisions as named rules in code; none silently applied.
- **Blank `to_gare_id` rows (326):** re-match via name normalisation + coordinate proximity. Priority: APRR→MONTLUCON concentration. Remaining unresolved rows dropped; drop count logged per operator. All decisions as named rules in code.
- Use data.gouv.fr / operator calculators (Phase 2a findings) to spot-check re-matched gate prices.

**Exit criterion.** Zero-price rows all have a typed disposition in code. Blank `to_gare_id` rows all resolved or explicitly dropped, with per-operator drop count in the log.

**ralph-loop:**
```
/ralph-loop "Implement Phase 2b of the toll routing service per iterative-tumbling-lecun.md. Cluster 551 zero-price rows by operator and gate pair; assign typed disposition (free-section edge / free-transfer edge / drop) as named rules in code. Re-match 326 blank to_gare_id rows via name normalisation and coordinate proximity, prioritising APRR-MONTLUCON; drop unresolved, log per-operator drop count. Spot-check re-matched prices against operator calculators." --completion-promise "PHASE_2B_COMPLETE" --max-iterations 6
```

---

## Phase 2c — Physical gate clustering and transfer edges

**Objective.** Collapse co-located gates into physical points; type all transfer edges.

**Deliverables.**
- Physical-gate clustering: 953 geocoded gates → ~815 points, within ~100 m. Produces `physical_gate_id ↔ gare_id` lookup.
- Transfer edge typing: `boundary` (free, zero-time) = coordinate co-location within ~100 m AND different operator; `exit_reentry` (3 min, 0.5 km dwell). High-traffic cross-operator pairs (ABLIS = ASFC id 4 + Cofiroute id 5) manually verified.
- **Free-flow detection (A79, A13/A14):** check whether affected gates appear in `gare_master`; check if their `od_pairs` rows are structurally different. If absent from fare matrix, add per-corridor flat-fee override table.
- 3 gates without coordinates: geocode or move to `suspect_gates`.

**Exit criterion.** Clustering complete with typed transfer edges. Free-flow roads classified. `suspect_gates` table populated with all unresolvable entries.

**ralph-loop:**
```
/ralph-loop "Implement Phase 2c of the toll routing service per iterative-tumbling-lecun.md. Cluster 953 geocoded gates to ~815 physical points within ~100m. Type transfer edges: boundary (co-location + different operator, free) vs exit_reentry (3min 0.5km). Manually verify ABLIS cross-operator boundary. Detect free-flow roads (A79, A13/A14): check gare_master and od_pairs; add per-corridor flat-fee override table if absent. Geocode or suspect_gates the 3 coordinate-less gates." --completion-promise "PHASE_2C_COMPLETE" --max-iterations 6
```

---

## Phase 2d — Operator normalisation and coverage audit

**Objective.** Clean operator names; quantify routing coverage per operator.

**Deliverables.**
- Operator normalisation: casefold + alias map in SQLite. *Conjecture: ASFC = ASF; `aliea` may be mis-cased.*
- **Per-operator coverage audit:** distinct gates N vs row count vs dense N(N−1). Operators materially below dense are correctness hazards — logged as known-bad regions.
- **Asymmetric pricing (426 rows, 0.7%):** keep as-is (directed graph handles it). Flag pairs where ratio exceeds 2× as likely data errors.
- Gate snapping failures >200 m after curation: moved to `suspect_gates` table, excluded from graph, logged with affected OD pair count.

**Exit criterion.** Alias map in SQLite. Per-operator coverage report written. Asymmetric outliers flagged. Build script runs clean from CSVs to SQLite with zero unresolved gate references.

**ralph-loop:**
```
/ralph-loop "Implement Phase 2d of the toll routing service per iterative-tumbling-lecun.md. Build operator alias map in SQLite (casefold + hand aliases). Run per-operator coverage audit: distinct gates vs row count vs dense N(N-1); log operators materially below dense. Flag asymmetric pairs where ratio >2x as likely errors. Move gates with snap >200m to suspect_gates with affected OD pair count. Build script must run clean from CSVs to SQLite with zero unresolved gate references." --completion-promise "PHASE_2D_COMPLETE" --max-iterations 5
```

---

## Phase 3a — National OSRM build

**Objective.** OSRM running on the full France extract.

**Deliverables.**
- Geofabrik France extract (~4 GB PBF) downloaded.
- OSRM MLD build in Docker using the same forked `car.lua` as Phase 1a.
- Smoke test: `/nearest`, `/route`, `/table` respond for points outside the Phase 1 regional extract.

**Exit criterion.** OSRM responds correctly to a route request between two points in northern and southern France.

**ralph-loop:**
```
/ralph-loop "Implement Phase 3a of the toll routing service per iterative-tumbling-lecun.md. Download Geofabrik France PBF. Build OSRM MLD in Docker using same forked car.lua as Phase 1a. Smoke test: /nearest, /route, /table all respond for points across France (not just the Phase 1 regional extract)." --completion-promise "PHASE_3A_COMPLETE" --max-iterations 4
```

---

## Phase 3b — Matrix precompute

**Objective.** 815×815 duration and distance matrices persisted and loadable at boot.

**Deliverables.**
- Two 815×815 matrices (duration + distance): tolls-allowed and `exclude=toll`. Computed via OSRM `/table`. Persisted as `.npy` float32 (~10 MB total).
- Matrix loader: reads `.npy` at service boot, fails fast if files are absent or corrupt.
- Dwell edge calibration: if Phase 1d revealed exit/re-entry artefacts, adjust the 3 min / 0.5 km constant before proceeding.

**Exit criterion.** Both matrices load without error; spot-check 10 random gate pairs for plausible durations and distances.

**ralph-loop:**
```
/ralph-loop "Implement Phase 3b of the toll routing service per iterative-tumbling-lecun.md. Compute two 815x815 matrices (tolled + toll-free) for duration and distance via OSRM /table. Persist as .npy float32. Add matrix loader that reads .npy at boot and fails fast if absent or corrupt. Spot-check 10 random gate pairs. Recalibrate dwell edge if Phase 1d found artefacts." --completion-promise "PHASE_3B_COMPLETE" --max-iterations 5
```

---

## Phase 3c — Snap quality and distance validation

**Objective.** Confirm the geometry layer is trustworthy at national scale.

**Deliverables.**
- Snap-quality check: all 815 gates, flag >200 m snaps for manual curation; move unresolvable to `suspect_gates`.
- OSRM distance vs `distance_km` error distribution across all 22,175 rows: publish full distribution; flag top 5% absolute deviation for manual snap review; hard-reject gates with >20% deviation.
- Toll-tagging audit: sample of `exclude=toll` routes — assert path passes nowhere near a known toll plaza.

**Exit criterion.** Error distribution published; top 5% reviewed; no gate with >20% deviation remains in the graph; toll-tagging audit passes for the sample.

**ralph-loop:**
```
/ralph-loop "Implement Phase 3c of the toll routing service per iterative-tumbling-lecun.md. Run snap-quality check for all 815 gates; flag >200m, move unresolvable to suspect_gates. Compute OSRM distance vs distance_km error distribution across all 22175 rows; publish distribution; flag top 5% absolute deviation; hard-reject >20% deviation from graph. Run toll-tagging audit on a sample of exclude=toll routes." --completion-promise "PHASE_3C_COMPLETE" --max-iterations 5
```

---

## Phase 4a — Generalised cost and vehicle classes

**Objective.** Parameterised cost function with per-class config; Pareto sweep working.

**Deliverables.**
- `G = toll + (km × running_cost_per_km) + (hours × value_of_time)` implemented. Defaults in SQLite config table per class. *Indicative defaults (conjecture — replace with DGITM/EU figures before public launch): class 1 ~€0.15/km, ~€12/h; class 4 HGV ~€0.30/km, ~€50/h.*
- One `data` array per vehicle class loaded into memory at boot. Class swapped at query time.
- Pareto sweep: logarithmic VoT from €1/h to €100/h, 10 steps. Same sparsity pattern per step, one vectorised numpy expression, re-run Dijkstra. Ten runs on 1,900 nodes is single-digit milliseconds.

**Exit criterion.** For a test pair, sweeping VoT from €1 to €100 produces a range of `best_value` routes that shift from zero-toll toward motorway as VoT rises.

**ralph-loop:**
```
/ralph-loop "Implement Phase 4a of the toll routing service per iterative-tumbling-lecun.md. Implement G = toll + km*running_cost_per_km + hours*VoT. Store defaults per class in SQLite config table (class 1: ~0.15/km, ~12/h; class 4: ~0.30/km, ~50/h — mark as conjecture). Load one data array per class at boot; swap at query time. Implement Pareto sweep: log VoT from 1 to 100 EUR/h, 10 steps, same sparsity pattern, vectorised numpy, re-run Dijkstra each step." --completion-promise "PHASE_4A_COMPLETE" --max-iterations 6
```

---

## Phase 4b — Response shape, guard rails, and cache

**Objective.** API returns a structured, filtered, cached Pareto frontier.

**Deliverables.**
- Response: options labelled `fastest`, `cheapest`, `best_value`, plus surviving Pareto points. Each carries `saving_vs_fastest_eur`, `extra_minutes`, `extra_km`, `eur_per_hour_saved`.
- Worthwhile filter: config-table default VoT threshold per class, overridable per request. Applied on top of frontier, not in the search.
- Guard rails enforced: `max_gate_hops = 5`; minimum detour ≥10 km AND ≥5 min.
- `match_tier` (direct / rematched / suspect) and `match_agreement` (snap distance ÷ 200 m threshold) on each option.
- Cache: `functools.lru_cache` keyed on `(snapped_entry_gate_id, snapped_exit_gate_id, class, VoT_bucket)`.

**Exit criterion.** Lille→Marseille class 1 returns 3–5 distinct options with correct labels; `best_value` shifts as VoT varies; guard rails visibly filter artefacts.

**ralph-loop:**
```
/ralph-loop "Implement Phase 4b of the toll routing service per iterative-tumbling-lecun.md. Structure response with fastest/cheapest/best_value labels plus Pareto points. Each option: saving_vs_fastest_eur, extra_minutes, extra_km, eur_per_hour_saved, match_tier, match_agreement. Worthwhile filter from config per class, overridable per request. Enforce max_gate_hops=5 and min detour >=10km AND >=5min. Cache keyed on (snapped_entry_gate_id, snapped_exit_gate_id, class, VoT_bucket)." --completion-promise "PHASE_4B_COMPLETE" --max-iterations 6
```

---

## Phase 4c — Per-request OSRM calls and lazy geometry

**Objective.** Per-request routing is non-blocking and resilient.

**Deliverables.**
- Per-request: two OSRM `/table` calls (origin→815 gates, 815→origin) + one baseline `/route`. Input: lat/lon coordinates.
- OSRM failure: retry once at 500 ms; return `{"osrm_unavailable": true}` if still down.
- Lazy `/geometry/{route_id}` endpoint: TTL ~60 s, keyed on Dijkstra result. Client calls it only for the selected option. Must not block the main response.

**Exit criterion.** Main response returns under ~300 ms warm. `/geometry/{route_id}` returns valid GeoJSON for a selected route. `osrm_unavailable` error returned correctly when OSRM is mocked down.

**ralph-loop:**
```
/ralph-loop "Implement Phase 4c of the toll routing service per iterative-tumbling-lecun.md. Per-request: two OSRM /table calls (origin<->815 gates) + baseline /route. Input: lat/lon. OSRM failure: retry once at 500ms, return osrm_unavailable:true if still down. Add lazy /geometry/{route_id} endpoint: TTL 60s, keyed on Dijkstra result, client calls for selected option only, must not block main response." --completion-promise "PHASE_4C_COMPLETE" --max-iterations 5
```

---

## Phase 5a — Distance regression and fare oracle

**Objective.** Confirm prices are right against external ground truth.

**Deliverables.**
- Distance cross-check kept as a regression pytest (22,175 rows, from Phase 3c) — reruns after any gate or OSRM change.
- Fare oracle: ~20–30 OD pairs spanning operators and classes, checked against data.gouv.fr/ASFA (if found in Phase 2a) or individual operator calculators. Agreement within a stated tolerance; any disagreement traced to a named root cause.

**Exit criterion.** Fare oracle passes for every operator tested; tolerance stated explicitly; disagreements documented with root cause.

**ralph-loop:**
```
/ralph-loop "Implement Phase 5a of the toll routing service per iterative-tumbling-lecun.md. Convert Phase 3c distance cross-check to a regression pytest (22175 rows). Run fare oracle: 20-30 OD pairs across operators and classes against data.gouv.fr/ASFA or operator calculators. State agreement tolerance explicitly. Document any disagreements with named root cause." --completion-promise "PHASE_5A_COMPLETE" --max-iterations 5
```

---

## Phase 5b — Route plausibility and independent estimate

**Objective.** Confirm route recommendations match what a French driver would expect.

**Deliverables.**
- 10 plausibility routes checked manually:
  - Paris → Lyon (A6 vs free N7/N6)
  - Paris → Bordeaux (A10 vs genuinely competitive free N10)
  - Clermont-Ferrand → Montpellier via A75 (free motorway with one tolled structure — Millau; breaks "motorway ⇒ tolled" assumption)
  - 7 further routes spanning operators and regions.
- HERE or TomTom toll-cost API on the same 10 routes as an independent validator (not a production dependency).

**Exit criterion.** All 10 plausibility routes match human expectation; HERE/TomTom results compared and any divergence explained.

**ralph-loop:**
```
/ralph-loop "Implement Phase 5b of the toll routing service per iterative-tumbling-lecun.md. Run 10 route plausibility checks including Paris-Lyon, Paris-Bordeaux, Clermont-Ferrand-Montpellier via A75. Check against HERE or TomTom toll-cost API as independent validator. All 10 must match human expectation; document any divergence from HERE/TomTom with named root cause." --completion-promise "PHASE_5B_COMPLETE" --max-iterations 5
```

---

## Phase 5c — Golden-file test suite

**Objective.** Regressions cannot silently change prices or routes.

**Deliverables.**
- pytest golden-file suite covering all fare oracle pairs and plausibility routes.
- Tests fail if any price or route option changes without an explicit golden-file update.

**Exit criterion.** All golden-file tests pass on a clean run; suite is rerunnable without network access (OSRM and oracle responses are fixtures).

**ralph-loop:**
```
/ralph-loop "Implement Phase 5c of the toll routing service per iterative-tumbling-lecun.md. Build pytest golden-file suite covering all Phase 5a fare oracle pairs and Phase 5b plausibility routes. Tests must fail if any price or route option changes without explicit golden update. Suite must run without network access using recorded OSRM and oracle fixtures." --completion-promise "PHASE_5C_COMPLETE" --max-iterations 4
```

---

## Phase 6a — Observability and ops

**Objective.** The service can be debugged and rebuilt by anyone.

**Deliverables.**
- Structured logging of the full gate chain per response (essential for "why this route" debugging).
- `/health` endpoint: asserts OSRM reachability and matrix load. Does not check data freshness (external process owns that).
- Documented one-command pipeline rebuild: OSM → OSRM → matrices.

**Exit criterion.** A single request log contains the full gate chain. `/health` returns 200 when OSRM is up, 503 when mocked down. Rebuild command runs end to end from a fresh checkout.

**ralph-loop:**
```
/ralph-loop "Implement Phase 6a of the toll routing service per iterative-tumbling-lecun.md. Add structured logging of gate chain per response. Add /health endpoint checking OSRM reachability and matrix load (not data freshness). Document one-command pipeline rebuild from OSM to matrices." --completion-promise "PHASE_6A_COMPLETE" --max-iterations 4
```

---

## Phase 6b — Geocoding wrapper

**Objective.** Accept free-text addresses as well as coordinates.

**Deliverables.**
- Optional geocoding wrapper: resolve free-text address to lat/lon before passing to the routing core. Routing core is unchanged.
- `match_tier` and `match_agreement` verified present on every response.

**Exit criterion.** `curl` with a city name returns the same result as `curl` with the corresponding coordinates.

**ralph-loop:**
```
/ralph-loop "Implement Phase 6b of the toll routing service per iterative-tumbling-lecun.md. Add optional geocoding wrapper: resolve free-text address to lat/lon before routing. Routing core unchanged. Verify match_tier and match_agreement are present on every response." --completion-promise "PHASE_6B_COMPLETE" --max-iterations 3
```

---

## Highest-risk unknowns, ranked

1. **Itinerary-dependent pricing.** Phase 0 resolves this. If >5% of cross-route rows are itinerary-bound, adopt corridor enumeration.
2. **OSM toll tagging.** Untagged tolled sections produce silent €0 routes. Phase 3c toll-tagging audit is the mitigation.
3. **Fare-matrix provenance.** Phase 2a investigates. A machine-readable authoritative source would de-risk the entire data layer.
4. **Gate snapping to wrong carriageways.** Detectable — snap-distance report converts silent errors into a work list.
5. **Free-flow tolling (A79, A13/A14).** Phase 2c detects; per-corridor override table is the mitigation.
6. **Exit/re-entry artefacts.** Guard rails reduce them; Phase 5b validation distinguishes genuine from artefact.

---

## Where the design could fail outright

If Phase 0 finds >5% itinerary-bound rows, the virtual-edge model is structurally wrong. Fallback: candidate corridor enumeration (generate K plausible corridors from OSRM, price each by decomposing into per-concession legs, rank). Slower and less complete, but robust to path-dependence. Do not build speculatively.

---

## Verification sequence (end to end)

1. `pytest` — golden-file fare and route regressions (Phase 5c).
2. `python3 -m tollroute <origin> <dest> --class N` — CLI returns option set with trade-off statement.
3. `curl` FastAPI for Lille→Marseille class 1 — 3–5 distinct options under ~300 ms warm.
4. Vary `--value-of-time` — confirm `best_value` shifts from zero-toll toward motorway as VoT rises.
5. Re-run 22,175-row distance cross-check after any gate coordinate or OSRM change.

---

## Critical files

- `od_pairs.csv` — fare matrix (kept current by external process)
- `gare_master.csv` — gate reference
- `CLAUDE.md` — python3, UK English, grill-me format rules
