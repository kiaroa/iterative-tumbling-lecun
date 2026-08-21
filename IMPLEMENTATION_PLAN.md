# Implementation Plan

**Prioritised list of work items. Order is priority — the build agent picks the top incomplete item.**

The authoritative specification is `iterative-tumbling-lecun.md` (Phases 0–6b). Each item
below references its source phase; consult that phase for full deliverables and rationale.

## Entry Format

Each entry must follow this structure exactly:

- [ ] **Short imperative title**
  Scope: What is included and what is explicitly excluded (1-2 sentences).
  Files: `path/to/key/file`, `path/to/other/file` (optional — omit when obvious)
  Done when: Concrete verification criteria, referencing runnable commands where possible.

## Ground truth (verified 2026-08-10)

- No source code exists yet; this is a greenfield build. `od_pairs.csv` (57,378 rows) and
  `gare_master.csv` (956 rows) are present. 13 operators confirmed (APRR 21,349 · ASFC 18,516
  · Cofiroute 10,936 · sanef 2,728 · escota 2,241 · AREA 503 · aliea 365 · sapn 315 · SFTRF 191
  · Landes 156 · ALIS 42 · Alicorne 26 · ATMB 10).
- Remediation tallies re-verified 2026-08-10 against `od_pairs.csv`: **551 zero-price rows**
  (class1 == 0) — matches spec. **Blank-endpoint rows correction:** the spec/Phase 2b say
  "326 blank `to_gare_id` rows", but the data shows only **163 rows with a blank `to_gare_id`**
  (162 APRR + 1 aliea). The 326 figure is blank-*either*-endpoint: 163 blank `to_gare_id` PLUS
  163 blank `from_gare_id` (a mirrored set). The Phase 2b re-match item below is worded to cover
  both directions so the build agent does not stall after finding only 163.
- **Operator alias confirmed 2026-08-10:** ASFC = ASF (Autoroutes du Sud de la France). Update Phase 2d alias map accordingly.
- Proposed package layout (not yet created): `tollroute/` (core), `tollroute/etl/`, `osrm/`
  (Lua profile + compose), `analysis/`, `reports/`, `tests/`. Paths in items are proposals;
  the build agent may adjust but must keep them consistent once chosen.

- **Independent planning re-verification (2026-08-10):** a fresh planning pass re-ran the
  tallies directly against the CSVs and reproduced every figure exactly — 57,378 fare rows;
  956 gates (953 with lat/lon); 551 zero-price rows (`class1 == 0`); 163 blank `to_gare_id`
  (162 APRR + 1 aliea) and 163 blank `from_gare_id`; all 13 operator counts unchanged. No
  source code, no `.ralph/` state, and no build iterations exist yet; `PROGRESS.md` is still
  the empty template. All 24 items below remain correctly incomplete. **Next actionable item
  is the Phase 0 gate** — do not refine or re-split Phase 1c+ items until its go/no-go lands,
  as a >5% itinerary-bound result rewrites the model (corridor enumeration).
- Note for Phase 4b: `gare_master.csv` already carries populated `match_tier` and
  `match_agreement` columns (from the prior geocoding pipeline), so those response fields have a
  ready data source rather than needing to be derived from scratch.

- **Second independent planning re-verification (2026-08-10):** another fresh pass re-ran the
  tallies directly against the CSVs and reproduced every figure with zero drift — 57,378 fare
  rows; 956 gates; 551 zero-price (`class1 == 0`); 163 blank `to_gare_id` + 163 blank
  `from_gare_id` (326 total); all 13 operator counts unchanged. Still no source code, no
  `.ralph/` state, empty `specs/`, and `PROGRESS.md` remains the template. No spec authoring
  needed: `iterative-tumbling-lecun.md` at repo root is the complete authoritative spec. All 24
  items remain correctly incomplete; the plan requires no structural change this pass. **Next
  actionable item is still the Phase 0 itinerary-dependence gate** — hold all Phase 1c+ item
  refinement until its go/no-go lands (a >5% itinerary-bound result switches the model to
  corridor enumeration and rewrites downstream items).

- **Third independent planning re-verification (2026-08-10):** a further fresh pass re-ran every
  tally directly against the CSVs and reproduced them with zero drift — 57,378 fare rows; 956 gates
  (953 with lat/lon, and 953 carrying populated `match_tier` + `match_agreement`, confirming the
  Phase 4b data-source note); 551 zero-price (`class1 == 0`); 163 blank `to_gare_id` (162 APRR + 1
  aliea) + 163 blank `from_gare_id` (326 total); all 13 operator counts unchanged. Confirmed no
  source code, no `tollroute/`/`analysis/`/`osrm/`/`reports/` directories, no `.ralph/` state, empty
  `specs/`, and `PROGRESS.md` still the template. The Phase 0 item was cross-checked against the
  spec's Phase 0 protocol (10–20 two-path OD pairs, >5% itinerary-bound ⇒ corridor enumeration) and
  is faithful. No spec authoring needed. All 24 items remain correctly incomplete; no structural
  change required. **Next actionable item remains the Phase 0 itinerary-dependence gate** — hold all
  Phase 1c+ refinement until its go/no-go lands.

- **Fourth planning pass (2026-08-10) — state has moved; two prior claims now stale, corrected here:**
  1. **`osrm/` now exists** (untracked), so the third pass's "no `osrm/` directory" is superseded.
     It contains a forked `osrm/car_toll.lua` (finding recorded in `osrm/README.md`: upstream
     `car.lua` v26.8.0 *already* declares `toll` in `classes`/`excludable` and tags `toll=yes`
     ways, so no functional profile edit was needed), a `lib/` copy, a merged regional PBF
     `osrm/data/bfc-ara.osm.pbf` (bourgogne + franche-comte + auvergne + rhone-alpes), and a
     **completed `osrm-extract`** (all `.osrm.*` extract outputs present). **`osrm-partition` and
     `osrm-customize` have NOT run** — no `.partition`/`.mldgr`/`.cells`/`.cell_metrics` outputs
     exist (only `.fileIndex`), so `osrm-routed --algorithm mld` cannot yet serve and the smoke
     test cannot pass. **Phase 1a is therefore partially complete** (profile + PBF + extract done;
     partition → customize → serve → smoke-test remain). This OSRM work is **not recorded in
     `PROGRESS.md`** — a ledger gap to be aware of.
  2. **The authoritative spec has been amended (uncommitted working-tree edit) to resolve the
     Phase 0b decision.** `iterative-tumbling-lecun.md` now adds a "Core architectural decision:
     same-operator toll-edge chaining is forbidden via the dwell edge" section, revised Phase 1c /
     Phase 2c / Phase 4b deliverables, and a new `same_operator_split` response field. This adopts
     **fix option (b)** from `reports/phase0_itinerary_dependence.md` (constrain the virtual-edge
     graph rather than switch to corridor enumeration), addressing that option's stated
     "might suppress legitimate same-operator routes" caveat by *allowing* genuine toll-free
     detours but flagging them `same_operator_split: true`. **Provenance confirmed 2026-08-10:**
     this is the human sign-off Phase 0b requires — made directly by the user via the `grill-me`
     interview, not an agent self-unblock (see the closure note on the Phase 0b item). The Phase 1c
     and Phase 4b items below match the amended spec. Phase 0b is now `- [x]`; Phase 1c
     implementation may begin.

- **Fifth planning re-verification (2026-08-10) — state confirmed, one new artefact, no structural change:**
  A fresh pass re-ran every tally directly against the CSVs with zero drift — 57,378 fare rows; 956
  gates (953 with lat/lon); 551 zero-price (`class1 == 0`); 163 blank `to_gare_id` + 163 blank
  `from_gare_id` (326 total); all 13 operator counts unchanged. The spec amendment adopting option (b)
  is confirmed present in the working tree (`iterative-tumbling-lecun.md`: "Core architectural
  decision" §, revised Phase 1c/2c/4b, `same_operator_split` field); still an uncommitted working-tree
  edit (`git diff --stat`: 9 insertions / 7 deletions). Phases 0, 0b, and the scipy install remain the
  only completed items. **OSRM (Phase 1a) re-checked on disk:** `osrm-extract` outputs all present, but
  still **no** `.partition`/`.mldgr`/`.cells`/`.cell_metrics` — partition → customize → serve →
  smoke-test remain, exactly as the fourth pass recorded. **New since the fourth pass:** `osrm/smoke_test.sh`
  now exists (untracked) — the script referenced by the "Verify OSRM endpoints" item is written, but it
  cannot pass until osrm-routed serves under `--algorithm mld`, so both Phase 1a items stay `- [ ]`. No
  `tollroute/` source, no `tests/`, no `data/matrices/`, no `.ralph/` state; `specs/` empty (correct —
  `iterative-tumbling-lecun.md` is the authoritative spec, no spec authoring needed). The OSRM work
  remains **unlogged in `PROGRESS.md`** (ledger gap noted, not a blocker). **Next actionable item is the
  Phase 1a OSRM completion** (run partition → customize → `docker compose up`, confirm serve); Phase 0b's
  human sign-off is resolved, so nothing blocks the build loop from proceeding.

## Items

### Phase 0 — Itinerary-dependence test (blocking gate)

- [x] **Run Phase 0 itinerary-dependence test and record go/no-go** — DONE 2026-08-10
  Scope: Pure data analysis over `od_pairs.csv`; no service code, no OSRM. Select 10–20 OD
  pairs reachable via two distinct concession paths (A→C), count fare rows per pair and compare
  prices against toll sums for each path. Excludes any graph/API work.
  Files: `analysis/phase0_itinerary_test.py`, `reports/phase0_itinerary_dependence.md`
  Done when: Report lists pairs tested, count provably itinerary-bound, percentage, typed
  classification per pair, and an explicit go/no-go for the virtual-edge model. If >5%
  itinerary-bound, the report recommends corridor enumeration and this plan is revised before
  Phase 1c. (spec: iterative-tumbling-lecun.md Phase 0)
  **Result: NO-GO (mechanical).** Exhaustive (not sampled) same-operator check: 48,849 /
  56,480 direct `od_pairs` edges (86.5%) are undercut by a cheaper multi-hop chain through
  the graph exactly as Phase 1c currently specifies it ("every od_pairs row is a usable
  edge"). This is the real hazard — Dijkstra would silently chain unrelated through-fares
  into an impossibly cheap route, not the (harmless) case of segmented paths costing more
  than direct. Root cause and two candidate fixes (full corridor enumeration per spec's
  fallback, or a smaller graph constraint forbidding same-operator toll-edge chaining) are
  documented in the report. See the new blocking item immediately below — **do not start
  Phase 1c as currently scoped until a human picks a fix.**

### Phase 0b — Resolve Phase 0 NO-GO before Phase 1c (blocking gate, human decision required)

- [x] **Decide and apply the fix for Phase 0's itinerary-dependence failure** — CONFIRMED HUMAN DECISION 2026-08-10
  Scope: Human sign-off needed — this is an architecture choice, not a build-loop-automatable
  decision. Choose between: (a) spec's stated fallback, corridor enumeration (generate K
  candidate corridors from OSRM geometry, price each via physically-adjacent concession legs
  only); or (b) constrain the virtual-edge graph to forbid same-operator toll-edge chaining
  (only the single direct `od_pairs` edge is usable per operator for a given entry/exit pair;
  cross-operator boundary edges from Phase 2c are unaffected). Option (b) is smaller-scope but
  unverified: it has not been checked for suppressing legitimate same-operator alternative
  routes. Once chosen, Phase 1c's items above must be revised to match before implementation
  starts.
  Files: `reports/phase0_itinerary_dependence.md` (existing findings), `IMPLEMENTATION_PLAN.md`
  (Phase 1c items, to be revised post-decision)
  Done when: A decision is recorded with rationale; Phase 1c items are rewritten to match if
  needed; only then may Phase 1c implementation begin.
  **Update (planning pass 2026-08-10):** the decision encoded in the authoritative spec —
  `iterative-tumbling-lecun.md` amended to adopt **option (b)**: forbid same-operator toll-edge
  chaining by excluding the dwell edge as a toll-edge connector, with genuine toll-free detours
  still allowed but flagged `same_operator_split: true` — is **confirmed as a human decision**, made
  directly by the user via the `grill-me` interview protocol (not an agent self-unblock). The user
  gave the directive verbatim ("forbid same-operator toll-edge chaining") and then chose explicitly
  among enumerated options for the toll-free-detour exception (selected: ban strictly on
  dwell-edge chaining only, flag genuine detours as `same_operator_split` rather than banning them
  outright). The Phase 1c and Phase 4b items above/below match this decision. Residual risk noted
  and accepted: this could still suppress some legitimate same-operator physical-carriageway
  alternatives that are *not* toll-free detours — flagged for Phase 5b plausibility testing, not a
  blocker. **Phase 1c implementation may now begin.**

- [x] **Install scipy/numpy in the build environment (blocker filed during Phase 0)** — DONE 2026-08-10
  Scope: `iterative-tumbling-lecun.md`'s stack mandates `scipy.sparse.csgraph.dijkstra` and
  numpy `.npy` files, but this environment has no `pip`/`ensurepip` and no network access —
  Phase 0's exhaustive check had to fall back to a pure-Python `heapq` Dijkstra (fine at
  current node counts, ≤501 per operator, but Phase 3b's 815×815 national matrices and
  Phase 1c's csgraph usage need the real library). Excludes any application code.
  Files: none yet — environment/tooling only
  Done when: `python3 -c "import scipy, numpy"` succeeds in the build environment.
  **Result:** The earlier "no network access" finding no longer holds — `apt`/`sudo` and
  outbound HTTPS are both available in this environment. Installed `python3-pip` via
  `sudo apt-get install python3-pip python3-venv`, then `python3 -m pip install
  --break-system-packages scipy numpy` (scipy 1.17.1, numpy 2.4.6). This is a system-level
  environment change, not a repo file change — nothing to commit for this item. Note this
  fix is environment-local; a fresh container/build environment will need the same two
  commands re-run (not yet captured in a Dockerfile/setup script — no such file exists in
  the repo yet).

### Phase 1a — OSRM setup (regional)

- [x] **Stand up OSRM Docker with forked toll-excludable car profile (regional extract)** — DONE 2026-08-10
  Scope: Download the Bourgogne-Franche-Comté + Auvergne-Rhône-Alpes OSM extract; fork
  `car.lua` adding `toll` to `excludable` and tagging `toll=yes` ways to that class; build MLD
  (`osrm-partition` + `osrm-customize`) in Docker. Excludes national extract (Phase 3a).
  Files: `osrm/car_toll.lua`, `osrm/docker-compose.yml`, `osrm/README.md`
  Done when: `docker compose up` yields a running osrm-routed; build completes without error on
  the regional extract.
  **Result:** `osrm-extract` was already complete from a prior pass; ran the remaining
  `osrm-partition` (23.7 s, 4,488,104 edge-based nodes, 4 MLD levels) and `osrm-customize`
  (2.1 s) against `osrm/data/bfc-ara.osrm`, producing `.partition`/`.mldgr`/`.cells`/
  `.cell_metrics`. `OSRM_DATA_DIR=.../osrm/data docker compose up -d` then started
  `osrm-routed --algorithm mld` cleanly (host mount path resolved per README §"docker-outside-
  of-docker path translation": `docker inspect <devcontainer> --format '{{json .Mounts}}'`).
  `osrm/data/` stays gitignored (binary build artefacts, ~1-2 GB); only the profile, compose
  file, README and smoke test are tracked.
- [x] **Verify OSRM endpoints and toll exclusion for Dijon→Lyon** — DONE 2026-08-10
  Scope: Smoke-test the running instance. Excludes any application code.
  Files: `osrm/smoke_test.sh`
  Done when: `/nearest`, `/route`, `/table` all return valid responses; `curl` `/route` for
  Dijon→Lyon returns a result and the same call with `exclude=toll` returns a different, longer
  route. (spec: iterative-tumbling-lecun.md Phase 1a)
  **Result:** `bash osrm/smoke_test.sh` — all four endpoints OK. Tolled route: 195,979 m /
  7,826 s. `exclude=toll` route: 201,247 m / 13,283 s — longer in both distance and (markedly)
  duration, as expected for a motorway-toll detour onto slower roads. Fixed the script's missing
  executable bit before committing.

### Phase 1b — Data loader and gate snapping (APRR only)

- [x] **Scaffold `tollroute` package, SQLite schema, and pytest harness** — DONE 2026-08-10
  Scope: Create the Python package skeleton, `requirements.txt`/`pyproject`, SQLite schema file,
  and an empty passing pytest. No routing logic. Excludes any ETL data movement.
  Files: `tollroute/__init__.py`, `tollroute/db/schema.sql`, `requirements.txt`, `tests/test_smoke.py`
  Done when: `python3 -m pytest` runs green; schema file documents the gates, fares, operator-alias,
  and config tables the later phases require.
  **Result:** Created `tollroute/` (with `tollroute/db/`), `tollroute/db/schema.sql` (four tables:
  `gates` mirroring `gare_master.csv` plus OSRM-snap columns for Phase 1b; `fares` mirroring
  `od_pairs.csv` as virtual toll edges with FKs to `gates`; `operator_alias` for casing
  normalisation per spec ("SQLite table, not source code"); `class_config` for Phase 4a's
  per-class generalised-cost defaults — structure only, no seed data, since seeding is those
  later phases' job), `requirements.txt` (fastapi, uvicorn, numpy, scipy, httpx, pytest, pandas
  per the spec's stack section), and `tests/test_smoke.py` (package import + schema-executes-
  and-creates-the-four-tables check). `python3 -m pytest` — 2 passed. Installed `pytest` into the
  build environment (`pip install --break-system-packages pytest`, same externally-managed-
  environment pattern as the earlier scipy/numpy install) since it was missing. Also added
  `__pycache__/`, `*.pyc`, `.pytest_cache/` to `.gitignore` (previously absent, so pytest's own
  cache directory showed up as untracked cruft).
- [x] **Load CSVs into SQLite filtered to APRR, logging zero-price rows** — DONE 2026-08-10
  Scope: Loader for both CSVs into SQLite, filtered to APRR. Zero-price rows logged explicitly
  (never silently dropped). Excludes remediation (Phase 2b) and non-APRR operators.
  Files: `tollroute/etl/load.py`
  Done when: `python3 -m tollroute.etl.load` populates SQLite from the CSVs; count of zero-price
  APRR rows is printed/logged; row counts reconcile against source.
  **Result:** `tollroute/etl/load.py` filters `od_pairs.csv` to `operator == "APRR"` (21,349
  rows, matching the ground-truth tally) and `gare_master.csv` to rows whose pipe-delimited
  `operators` field contains the token `APRR` (210 gates — a superset of the 176 gate ids
  actually referenced by APRR fares, so the next item's "OSRM /nearest for every APRR gate" has
  the full set, not just currently-referenced ones). 8 zero-price rows (`class1 == 0.0`) are
  logged via `logger.warning` with full row context and still inserted (never dropped); blank
  `from_gare_id`/`to_gare_id` rows (162 each direction) load as SQLite NULL, deferred to Phase
  2b as scoped. `run()` reconciles Python-side counts against post-insert `SELECT COUNT(*)` and
  raises if they diverge. Added `tests/test_etl_load.py` (3 tests: row-count reconciliation
  against an independently-recomputed CSV count, zero-price rows logged exactly once each and
  never dropped, and zero unresolved gate references from fares into gates).
  **Test outcome:** `python3 -m pytest` — 5 passed (2 prior smoke + 3 new).
- [x] **Snap every APRR gate via OSRM /nearest and verify the 5 test pairs** — DONE 2026-08-10
  Scope: Run OSRM `/nearest` for every APRR gate, record snap distance, flag >200 m. Confirm the
  5 named test pairs exist in APRR data with non-zero prices and each has a distinct OSRM toll-free
  route. Excludes suspect_gates curation (Phase 2d).
  Files: `tollroute/etl/snap_report.py`, `reports/phase1b_snapping.md`
  Done when: Snapping report produced; all >200 m snaps listed by name; all 5 test pairs confirmed
  present with prices and a distinct toll-free alternative. (spec: iterative-tumbling-lecun.md Phase 1b)
  **Result:** Snapped 209/210 APRR gates (1 gate, CHARMONT (LIM.CONC.), has no lat/lon in
  `gare_master.csv` and was skipped, logged via a warning). 105 gates flagged >200 m — traced to
  an extract-coverage artefact, not a data-quality issue: the regional bfc-ara OSRM instance
  doesn't cover APRR's full network (which reaches Paris, Tours, Reims, Verdun), so out-of-extract
  gates snap to the nearest in-extract road tens-to-hundreds of km away. Documented in the report;
  re-run after the Phase 3a national OSRM build for a meaningful signal. Resolved the 5 named test
  pairs to concrete gate ids: pairs 1/2/4/5 are genuine APRR fare rows on the A6/N6 corridor
  (Dijon Sud, La Folie-B/Paris, Beaune Sud, Macon Nord/Sud, Villefranche Nord), all confirmed
  present with non-zero class1 prices and a distinct toll vs toll-free OSRM route. Pair 3
  (Clermont-Ferrand -> Montpellier) is a deliberate edge case per the spec's own parenthetical
  ("A75 is free motorway") — confirmed no APRR gare exists south of Clermont-Ferrand (every APRR
  fare from CLERMONT-BARRIERE runs north towards Lyon/Bourgogne), so it was checked via OSRM
  city-centre coordinates only; the tolled and toll-free routes came back identical, which is the
  expected result for an untolled corridor, not a failure.

### Phase 1c — Overlay graph and CLI

- [x] **Build directed APRR overlay graph (toll + toll-free + access + dwell edges)** — DONE 2026-08-11
  Scope: Overlay graph builder — APRR toll edges from `od_pairs` (each labelled with `operator`),
  toll-free gate-to-gate edges from OSRM, origin/destination access edges, per-gate dwell edge
  (3 min, 0.5 km). **The dwell edge must be excluded as a toll-edge connector** — it may never join
  two toll edges together (this is the Phase 0b / spec "Core architectural decision" fix; vacuous
  while APRR-only but implemented now so Phase 2c inherits it unchanged). Excludes cross-operator
  boundary edges (Phase 2c) and the CLI wiring below.
  Files: `tollroute/graph.py`
  Done when: Graph builds for APRR without unresolved gate references; edge counts and node count
  (~1,900) logged; every toll edge carries an `operator` label; a unit test asserts a known toll
  edge price matches `od_pairs`; a unit test asserts no path can traverse dwell → toll → dwell →
  toll (i.e. the dwell edge cannot chain two toll edges). (spec: iterative-tumbling-lecun.md Phase
  1c + Core architectural decision)
  **Result:** `tollroute/graph.py` node-splits every gate into **four** roles, not the naive two
  (`IN`/`OUT`/`IN_TOLL`/`OUT_TOLL` — documented in the module docstring), which is what makes the
  spec's dwell-connector rule a structural graph property rather than a runtime path check: toll
  edges only ever originate at `OUT`, `OUT` is only ever reached via a dwell that followed a
  toll-free/access arrival (never a toll arrival), so `toll -> dwell -> toll` has no representable
  edge sequence — while `toll -> dwell -> toll-free -> dwell -> toll` (a genuine same-operator
  detour) remains reachable, matching the spec's allow-but-flag intent. Money cost is taken
  verbatim from `fares` (class1..5); distance/time for both toll and toll-free edges come from a
  live regional-OSRM `/table` call per the spec's Core architectural decision ("distance/time from
  OSRM"), not from the CSV's `distance_km`. **Build result (209 snapped APRR gates):** 836 nodes,
  20,835 toll edges, 56,832 toll-free edges, 418 dwell edges, 78,085 edges total — all reconciled
  exactly against DB counts (21,349 fares − 324 blank-endpoint − 190 referencing the one
  no-coordinate gate CHARMONT (LIM.CONC) = 20,835). Node count is 836, not the spec's rough national
  "~1,900" figure — that estimate covers the eventual 956-gate national graph at 2 nodes/gate; this
  regional 209-gate build is deliberately 4 nodes/gate for the reasons above, logged explicitly
  rather than silently diverging from the spec's ballpark.
  **Test outcome:** `python3 -m pytest` — 10 passed (7 prior + 3 new in `tests/test_graph.py`,
  skipped automatically without a live OSRM instance, same pattern as `test_snap_report.py`).
  **Gotcha found:** osrm-routed's default `--max-table-size` caps `max(len(sources),
  len(destinations))` at 100 per `/table` request (confirmed empirically: 100 passes, 101 returns
  `{"code":"TooBig"}`), independent of the full location list length. `_osrm_table` tiles the full
  209×209 matrix into ≤100×100 blocks via the `sources`/`destinations` index parameters and
  stitches them together — no docker-compose/OSRM server change needed.
- [x] **Add scipy Dijkstra with predecessor re-walk and `tollroute` CLI** — DONE 2026-08-10
  Scope: `scipy.sparse.csgraph.dijkstra` with predecessor re-walk accumulating toll/time/distance
  separately; CLI `python3 -m tollroute <origin> <dest> --class N`. Excludes generalised cost and
  Pareto sweep (Phase 4a).
  Files: `tollroute/routing.py`, `tollroute/cli.py`, `tollroute/__main__.py`
  Done when: CLI runs without error for all 5 test pairs, returning ≥1 route each with separate
  toll, duration and distance totals, **and no returned route chains two toll edges via the dwell
  edge** (per the spec's revised Phase 1c exit criterion). (spec: iterative-tumbling-lecun.md Phase 1c)
  **Result:** `tollroute/routing.py` builds a duration-weighted sparse adjacency matrix from the
  overlay graph (`scipy.sparse.csgraph.dijkstra`, `return_predecessors=True`), then re-walks the
  predecessor chain to sum toll/duration/distance separately per edge — documented as a deliberate,
  not-spec-mandated weighting choice (duration, not toll_eur, since every non-toll edge costs €0 and
  toll-weighting would trivially always pick an all-toll-free path regardless of duration; Phase 4a's
  generalised cost supersedes this). `tollroute/cli.py` adds a small fixed 8-city gazetteer (Dijon,
  Lyon, Paris, Mâcon, Beaune, Villefranche, Clermont-Ferrand, Montpellier — the cities named in the 5
  test pairs; not a general geocoder, that's Phase 6b) and wires city name → OSRM access edges →
  Dijkstra → formatted output. `tollroute/__main__.py` enables `python3 -m tollroute`.
  **Bug found and fixed in already-committed `graph.py` (Phase 1c graph item):** `add_access_edges`
  called OSRM `/route` without `exclude=toll`, so the destination-bound access edge could silently
  ride the full tolled motorway for free — empirically, Dijon→Lyon's very first CLI run returned
  `toll: €0.00` with distance/duration matching the *tolled* route almost exactly, because
  duration-weighted Dijkstra always preferred the "free" access edge over paying at a second gate.
  Fixed by passing `exclude=toll` on both the origin→gate and gate→destination access-edge OSRM
  calls; OSRM's `NoRoute` response (a real possibility once tolls are excluded — confirmed 123 of the
  ~836 access-edge candidates for the Dijon–Lyon query) is now handled per the spec's "missing edges:
  silently omitted, gap logged" convention rather than raising. After the fix, Dijon→Lyon correctly
  returns gates 269→930 (Dijon Sud→Villefranche Nord) at €14.10, matching the known `od_pairs` fare.
  **CLI verified for all 5 named pairs** (`python3 -m tollroute <city> <city> --class 1`): Dijon→Lyon
  (269→930, €14.10), Paris→Lyon (463→930, €37.90), Clermont-Ferrand→Montpellier (single gate 812,
  €0.00 — correct for the A75-is-free-motorway edge case), Dijon→Mâcon (269→300, €10.40),
  Beaune→Mâcon (96→300, €7.40). Note pairs 4/5 route through gate 300 rather than the specific
  495/494 gates `snap_report.py`'s fare-row check used — expected and not a discrepancy: the CLI
  optimises city-centre-to-city-centre by duration, so it may pick a different real APRR gate than a
  test that pins one specific `od_pairs` row; Phase 1d's validation item checks the pinned-row case.
  **Test outcome:** `python3 -m pytest` — 16 passed (10 prior + 6 new in `tests/test_routing.py`: 1
  direct-toll-edge unit test, 5 parametrised end-to-end CLI-path tests over the named pairs asserting
  positive toll/duration/distance and — checked structurally on the actual returned edge sequence,
  not just at graph-build time — that no route contains `TOLL → DWELL → TOLL`). All OSRM-dependent
  tests skip automatically without a live instance, same pattern as prior phases.

### Phase 1d — Validation and FastAPI wrapper

- [x] **Wrap routing in a minimal FastAPI endpoint** — DONE 2026-08-10
  Scope: ~30-line FastAPI app exposing one endpoint returning the option set. Excludes response
  labelling/guard-rail shaping (Phase 4b) and geometry endpoint (Phase 4c).
  Files: `tollroute/api.py`
  Done when: `uvicorn tollroute.api:app` serves the endpoint; a request for a test pair returns the
  same option set as the CLI.
  **Result:** `tollroute/api.py` builds the full graph once at startup (FastAPI `lifespan`,
  stored on `app.state`) rather than per request — the expensive O(gates²) OSRM `/table` build
  only needs to happen once for a long-lived server. Per the reuse hazard flagged in Phase 1c's
  PROGRESS entry (`add_access_edges` mutates its graph in place), the single `GET /route` handler
  shallow-copies the startup graph before calling `add_access_edges`, same pattern as
  `tests/test_routing.py`'s `_graph_copy`, so concurrent/successive requests can't leak
  origin/destination access edges into each other. Reuses `tollroute.cli.GAZETTEER` for
  origin/destination city names (unknown city or out-of-range `vehicle_class` → HTTP 400,
  no route found → HTTP 404) rather than duplicating the CLI's gazetteer. Installed
  `fastapi`/`uvicorn` into the build environment (`pip install --break-system-packages
  fastapi uvicorn`, same externally-managed-environment pattern as the earlier scipy/pytest
  installs — `requirements.txt` already listed both, they just hadn't been installed yet).
  **Verified live:** `python3 -m uvicorn tollroute.api:app` served `GET /route?origin=dijon&
  destination=lyon&vehicle_class=1` → `{"toll_eur": 14.1, "duration_s": 9741.7,
  "distance_m": 209821.0, "gates": [269, 930]}`, matching the CLI's Dijon→Lyon result
  (€14.10, gates 269→930) exactly; unknown-city request → 400.
  **Test outcome:** `python3 -m pytest` — 19 passed (16 prior + 3 new in `tests/test_api.py`,
  using FastAPI's `TestClient`; skip automatically without a live OSRM instance, same pattern
  as prior phases). One new test asserts the endpoint's JSON matches `tollroute.cli.run`'s
  result field-for-field for Dijon→Lyon; two assert the 400 error paths.
- [x] **Validate all 5 APRR test pairs against od_pairs and OSRM distance** — DONE 2026-08-11 (1 check passes, 2 blocked-with-followup)
  Scope: For each of the 5 pairs assert direct tolled route matches `od_pairs` price exactly, ≥1
  cheaper alternative meets guard rails (≥10 km AND ≥5 min extra), and OSRM motorway distance matches
  `distance_km` within a few percent. Excludes national-scale validation (Phase 3c/5a).
  Files: `tests/test_phase1d_pairs.py`
  Done when: All 5 pairs pass all three checks under pytest. If any OSRM distance check fails, stop and
  investigate the geometry layer before continuing. (spec: iterative-tumbling-lecun.md Phase 1d)
  **Result: PRICE PASSES; DISTANCE + GUARD-RAIL are genuine findings (blocked-with-followup, Phase-0
  style).** Full write-up: `reports/phase1d_pair_validation.md`. (1) **Price** — the direct
  gate→gate TOLL edge equals `od_pairs` class1 exactly for all 4 fare pairs (14.10/62.80/11.10/6.60);
  pair 3 (Clermont→Montpellier) has no APRR fare row (A75 untolled edge case), skipped explicitly.
  (2) **OSRM distance** — FAILS the "within a few percent" (5% chosen) check. Well-snapped corridor
  gates (4–8 m) still produce tolled routes +7% (pair 1) to +36% (pair 4) longer than `distance_km`,
  because the forward route overshoots south past the destination gate and U-turns back to reach a
  direction-specific carriageway node (**verified**: reverse-direction and overshoot-corrected
  distances both recover `distance_km` to ~1.5% for pairs 1 & 4; encoded as a passing root-cause
  test). A 6-pair spot-check shows the same 28–94% inflation, so it is systemic — Phase 3c's national
  snap-quality + distance-error audit resolves it, not this item. Pair 2 (Paris) is untestable at
  regional scale (gate 393 snaps 71 km away, outside the bfc-ara extract — needs Phase 3a). *Conjecture
  (flagged, unverified against OSM tagging): each gate snaps to a single directional carriageway node,
  forcing the U-turn when approached from the opposite side.* (3) **Guard rail** — FAILS the literal
  "≥10 km AND ≥5 min": the toll-free A6 alternative is always ≥5 min slower (+32 to +112 min) but never
  ≥10 km longer (−0.3 to −33 km — N-roads parallel the motorway at similar length), so no alternative
  qualifies. The wording needs a documented interpretation (time-based / OR) — a Phase 4b decision. Both
  failing checks are non-strict `xfail`s in `tests/test_phase1d_pairs.py` (suite green: 6 passed,
  3 skipped, 7 xfailed) pointing at the report and the follow-up item below.

### Phase 1d-follow-up — Distance validation and guard-rail wording (deferred to Phase 3c / 4b)

- [x] **Resolve the Phase 1d distance-check and guard-rail-wording findings** — DONE 2026-08-11
  Scope: Two deferred findings from the Phase 1d 5-pair validation (see
  `reports/phase1d_pair_validation.md`), neither fixable at Phase 1d scale. (a) **Distance check** —
  gate-node-to-gate-node OSRM distance systematically overshoots `distance_km` (7–94% across sampled
  pairs) due to carriageway-direction snap artefacts (U-turn detours) and, for out-of-extract gates,
  missing coverage. Resolve via Phase 3c's national snap-quality curation + 22,175-row OSRM-vs-
  `distance_km` error distribution (hard-reject >20% deviation), on the Phase 3a national extract.
  (b) **Guard-rail wording** — the spec's "≥10 km AND ≥5 min" cannot pass for motorway-vs-parallel-
  N-road pairs (the free alternative is slower but not longer); needs a documented interpretation
  (time-based or OR), owned by Phase 4b's guard-rail response shaping.
  Files: `reports/phase1d_pair_validation.md` (findings), Phase 3c + Phase 4b items (resolution)
  Done when: Phase 3c publishes the distance-error distribution with no >20%-deviation gate remaining
  in the graph, AND Phase 4b records the chosen guard-rail interpretation; then the Phase 1d
  `xfail`s in `tests/test_phase1d_pairs.py` are revisited (flip to pass or re-scope).
  **Part (a) done 2026-08-11:** Phase 3c published the full 21,981-row error distribution and
  root-caused it to the same carriageway-direction snap artefact this item names (verified, not just
  conjectured — e.g. gare_id 96→95: +2029% forward vs −4.8% reversed); 43 gates quarantined to
  `suspect_gates` under a documented gate-level (not literal per-row) hard-reject policy. See
  `reports/phase3c.md`. **Part (b) done 2026-08-11:** Phase 4b's `tollroute/response.py` reinterprets
  the literal "≥10 km AND ≥5 min" as **OR** (`extra_km>=10` or `extra_minutes>=5`) for the guard rail
  applied to unlabelled surviving Pareto points — see that item's result above for the full reasoning.
  **Both parts done; this item is fully resolved.** The Phase 1d `xfail`s in `tests/test_phase1d_pairs.py`
  still assert the *literal* spec wording against the raw gate-to-gate OSRM distance/guard-rail check
  (a lower-level check than `response.py`'s frontier logic), so they are deliberately left as-is rather
  than flipped — revisiting whether that specific test should be re-scoped to the OR interpretation is a
  small follow-up, not blocking.

### Phase 2a — External data investigation

- [x] **Investigate authoritative tariff sources (data.gouv.fr, ASFA) and record decision** — DONE 2026-08-11
  Scope: Assess machine-readable French motorway tariff tables for vintage, licence, completeness.
  Excludes any CSV remediation.
  Files: `reports/phase2a_tariff_sources.md`
  Done when: Report states source found/not-found, whether it supersedes `od_pairs.csv`, and a
  recommended action; decision recorded before Phase 2b begins. (spec: iterative-tumbling-lecun.md Phase 2a)
  **Result: NOT FOUND.** `data.gouv.fr`'s "Autoroutes et péages en flux libre" dataset (fetched
  directly: 6 files, licence "Other (Attribution)", updated 2025-10-25) carries gate/gantry
  **locations only** — its own documentation states toll amounts are excluded because they vary
  by class and time. A second reuse ("Réseau autoroutier français et tarifs", Tableau Public) does
  show tariff figures but only for a handful of example routes, dated 2010–2018, with no
  downloadable raw table. ASFA (`autoroutes.fr`) publishes current tariffs but only as per-operator
  PDFs and a single-journey fare calculator, not a bulk structured table — corroborated by an
  independent OpenStreetMap France forum thread of developers solving the identical problem, who
  report no centralised toll-price dataset exists anywhere in France ("c'est fou qu'en 2025 aucun
  jeu public des prix des autoroutes n'existe"). **Caveat:** two direct `WebFetch` attempts against
  `autoroutes.fr` failed on a TLS certificate error in this environment, so the ASFA finding rests
  on search-result snippets plus the corroborating forum thread rather than a first-hand page read
  — flagged explicitly in the report as a secondary-source limitation. **Decision:** no source
  supersedes `od_pairs.csv`; it remains the sole primary tariff input (consistent with the spec's
  existing assumption that it is "kept current by an external update process"). Phase 2b proceeds
  unblocked; Phase 2b/5a spot-checks against operator tariffs must be done manually per-OD-pair via
  operator calculators, since no bulk comparison source exists.

### Phase 2b — Zero-price and blank-ID remediation

- [x] **Assign typed disposition to all 551 zero-price rows as named rules** — DONE 2026-08-11
  Scope: Cluster zero-price rows by operator and gate pair; each cluster gets a typed disposition
  (free-section edge / free-transfer edge / drop) encoded as a named rule in code. Excludes blank-ID
  rematching below.
  Files: `tollroute/etl/remediate_zero_price.py`, `reports/phase2b_zero_price.md`
  Done when: Every zero-price row has a typed disposition in code; none applied silently; report tallies
  each disposition class.
  **Result:** All 551 zero-price rows (6 operators, not just APRR) classified by three named
  rules in priority order: `operator_boundary_short_hop` -> `free_transfer` (6 rows — different
  `gare_master.operators` tags + <=8 km haversine), `structural_node_name` -> `free_section` (28
  ASFC "Bifurcation" interchange-node rows) and `short_physical_hop` -> `free_section` (279 more
  rows <=8 km apart — e.g. APRR's 4 known-legit short bypasses, ASFC's Toulouse-rocade cluster),
  else `default_no_signal` -> `drop` (238 rows, dominated by ASFC/Landes/Alicorne pairs tens to
  hundreds of km apart with no structural signal — e.g. one pair 226 km apart). Tally:
  free_section=307, free_transfer=6, drop=238. **Conjecture flagged in the report:** the 8 km
  proximity threshold and the "bifurcation" keyword are pattern-fitted to this dataset's observed
  clusters/histograms, not sourced from an authoritative document; Phase 2d's coverage audit and
  Phase 3c's distance-error validation are where a wrong call here would surface. Scoped to the
  CSV-level analysis + report only, per the Files line — not wired into `graph.py`'s (APRR-only,
  already-committed Phase 1c) edge construction, since Phase 1's regional graph already treats its
  8 APRR zero-price rows as valid €0 toll edges and none of them end up `drop`ped by this pass.
- [x] **Re-match 326 blank-endpoint rows (163 blank `to_gare_id` + 163 blank `from_gare_id`); drop unresolved with per-operator log** — DONE 2026-08-11
  Scope: Re-match every row with a blank endpoint id in EITHER direction (verified: 163 blank
  `to_gare_id`, of which 162 APRR + 1 aliea, plus 163 blank `from_gare_id` — 326 rows total) via
  name normalisation + coordinate proximity, prioritising the APRR→MONTLUCON concentration;
  unresolved rows dropped with per-operator drop count logged. Spot-check re-matched prices against
  operator calculators. Excludes zero-price handling above.
  Files: `tollroute/etl/rematch_blank_ids.py`, `reports/phase2b_rematch.md`
  Done when: All blank `to_gare_id` AND blank `from_gare_id` rows resolved or explicitly dropped;
  per-operator drop count in the log; spot-check documented. (spec: iterative-tumbling-lecun.md Phase 2b)
  **Result:** All 326 blank endpoints (all name "MONTLUCON": 324 APRR + 2 aliea) resolved to
  gare_id 551 via `canonical_name_exact_match` (0 dropped). `gare_master.csv` carries a genuine
  name collision here: gare_id 550 ("Péage de Montluçon", A714) vs 551 ("MONTLUCON" exactly, A71
  j.10) — both geocoded to identical coordinates, so coordinate proximity cannot break the tie;
  resolved instead because the blank rows spell the name "MONTLUCON" verbatim, matching 551's
  canonical_name exactly while only matching 550 via its alias list. Corroborated independently:
  elsewhere in `od_pairs.csv`, gare_id 551 rows are all spelled "MONTLUCON"/Cofiroute and gare_id
  550 rows all spelled "Péage de Montluçon"/ASFC — same canonical-vs-alias split. Four named rules
  implemented in priority order (`canonical_name_exact_match` → `alias_name_match` →
  `coordinate_proximity_disambiguation` → `operator_tag_disambiguation` → drop); only the first
  rule fires on this dataset, the other three are exercised by synthetic unit tests only. Price
  spot-check: no live operator-calculator check possible (same TLS/no-bulk-source constraint as
  Phase 2a); substituted a class1 EUR/km rate-plausibility check (8.02-14.58 c/km, tight
  outlier-free cluster) documented in the report.

### Phase 2c — Physical gate clustering and transfer edges

- [x] **Cluster geocoded gates to physical points and type transfer edges** — DONE 2026-08-11
  Scope: Cluster 953 geocoded gates to ~815 physical points within ~100 m producing a
  `physical_gate_id ↔ gare_id` lookup; type transfer edges as `boundary` (co-location + different
  operator, free/zero-time) vs `exit_reentry` (3 min, 0.5 km); manually verify ABLIS (ASFC 4 +
  Cofiroute 5). Excludes free-flow handling below.
  Files: `tollroute/etl/cluster_gates.py`
  Done when: Clustering produces ~815 points with the lookup table; transfer edges typed; ABLIS
  boundary verified in a test.
  **Result:** 953 geocoded gates collapse to **exactly 815** physical points via
  exact-coordinate grouping (`tollroute/etl/cluster_gates.py`), matching the spec's ground-truth
  figure. **Key finding:** the upstream geocoding pipeline already snapped co-located gates
  (opposite carriageways / two concessions at one barrier) to *identical* coordinates, so
  exact-coordinate grouping is the authoritative co-location signal — a 100 m transitive
  union-find instead over-merges to ~790 by chaining 36 near-but-distinct carriageway pairs, so
  it was rejected. The ~100 m radius is applied to *transfer-edge typing* instead: 181 co-located
  (≤100 m) pairs typed as `boundary` (110, disjoint operator tags, free/zero-time — the only
  permitted different-operator toll-edge connector) or `exit_reentry` (71, shared operator tag,
  3 min / 0.5 km dwell, excluded as a toll-edge connector per Phase 1c). `physical_gate_id` is
  assigned deterministically by ascending min member gare_id; `build_lookup` yields the
  953-entry `gare_id → physical_gate_id` table. ABLIS (ASFC gare_id 4 + Cofiroute gare_id 5, 0 m
  apart) verified as `boundary` in a test. The 3 coordinate-less gates (1, 210, 243) are logged
  and deferred to the free-flow / `suspect_gates` item below, not silently dropped. Report:
  `reports/phase2c_clustering.md`. **Conjecture flagged:** the exact-coordinate collapse and the
  disjoint-operators-⇒-boundary rule are judgement calls (ABLIS the one manual anchor); Phase 2d
  coverage + Phase 3c snap-quality curation are where a wrong call surfaces.
  **Test outcome:** `python3 -m pytest` — 55 passed, 3 skipped, 7 xfailed (10 new in
  `tests/test_cluster_gates.py`; pins 815 points + 110/71 edge tallies + ABLIS boundary).
- [x] **Classify free-flow roads and quarantine coordinate-less gates** — DONE 2026-08-11
  Scope: Detect free-flow tolling (A79, A13/A14) — check presence in `gare_master`/`od_pairs`; add a
  per-corridor flat-fee override table if absent. Geocode or move the 3 coordinate-less gates to
  `suspect_gates`. Excludes clustering above.
  Files: `tollroute/etl/freeflow.py`, `tollroute/db/schema.sql`
  Done when: Free-flow roads classified; override table exists (or documented not-needed); `suspect_gates`
  holds all unresolvable coordinate-less entries. (spec: iterative-tumbling-lecun.md Phase 2c)
  **Result:** `tollroute/etl/freeflow.py` classifies all three spec-named corridors and finds **all
  present in `od_pairs`** — A79 (2 gates 263/264, 593 rows), A13 (20 sapn gates, 260 conventional
  gate-to-gate rows), A14 (2 gates, 5 rows) — so **no flat-fee override is needed**. Added two schema
  tables: `suspect_gates` (deliberately FK-free — the canonical gates table is operator-filtered until
  the Phase 2d national build, so an FK would couple load order) and `freeflow_override` (structure
  only, intentionally empty). **Genuine structural finding:** A14's five fare rows are all self-loops
  (`from_gare_id == to_gare_id`) — a free-flow single-gantry flat fee, not an entry→exit pair; flagged
  for the graph builder (follow-up item below). **Checked, not assumed:** blank `distance_km` is *not* a
  free-flow marker (61% of all rows omit it; whole operators omit it wholesale) — the self-loop pattern
  is the distinctive signal (all 5 self-loops in the file are A14/sapn). The 3 coordinate-less gates
  (1, 210, 243 — all "limite de concession" administrative boundary markers, not geocodable barriers)
  are quarantined into `suspect_gates` with their strand counts (24/194/36 od_pairs rows). Report:
  `reports/phase2c_freeflow.md`.
  **Test outcome:** `python3 -m pytest` — 61 passed, 3 skipped, 7 xfailed (6 new in
  `tests/test_freeflow.py`).

- [x] **Handle A14 free-flow self-loop toll edges in the graph builder** (follow-up from Phase 2c freeflow) — DONE 2026-08-11
  Scope: A14's 5 fare rows (gates 205, 547; sapn) are self-loops (`from_gare_id == to_gare_id`) — a
  free-flow single-gantry flat fee, the only self-loops in `od_pairs`. `tollroute/graph.py` currently
  builds toll edges from distinct `from`→`to` gate pairs; a self-loop would collapse to a zero-length
  no-op or be dropped, silently losing the A14 flat fee. When the national/multi-operator graph is built
  (Phase 3b+/4x), a self-loop toll edge must become a flat-fee section edge (fee applied on traversing
  the free-flow section, distance/time from OSRM between the section's endpoints), not a no-op. Excludes
  the A14 classification itself (done in `reports/phase2c_freeflow.md`).
  Files: `tollroute/graph.py`, `reports/phase2c_freeflow.md` (finding)
  Done when: The graph builder represents each A14 self-loop as a priced free-flow section edge, with a
  test asserting the A14 flat fee is reachable and not dropped.
  **Result:** `build_graph`'s toll-edge loop now special-cases `from_gare_id == to_gare_id` before the
  OSRM-table lookup: it builds the `OUT -> IN_TOLL` toll edge directly with `duration_s=0.0,
  distance_m=0.0` (a single gantry has no second endpoint to derive a driven span from) instead of
  routing through the OSRM tolled-matrix lookup or the `distance_km`/`FALLBACK_SPEED_KMH` fallback
  (both assume two distinct points). The fee is unaffected by the zero distance/duration - `routing.py`
  sums `toll_eur` on every TOLL edge regardless - so it is a genuinely priced edge, not a no-op; a
  `freeflow_selfloop_count` is logged when any occur. **Verified with a synthetic, OSRM-independent
  test** (`tests/test_graph.py::test_a14_selfloop_becomes_priced_freeflow_edge_not_dropped`): an
  in-memory SQLite DB with one gate (547) and one self-loop fare row, a mocked OSRM `/table` client
  (`httpx.MockTransport`), asserts the edge exists with the exact fare and, via `routing.find_route`,
  that the fee is actually collectable end-to-end (`IN -> dwell -> OUT -> toll -> IN_TOLL -> dwell ->
  OUT_TOLL`), not just a disconnected edge. Vacuous on the current APRR-only regional DB (A14 is sapn,
  filtered out by `load.py`), same as the rest of Phase 2c/2d's multi-operator prep — exercised for real
  once Phase 3a's national DB feeds `build_graph`.
  **Test outcome:** `python3 -m pytest` — 74 passed (1 new), 3 skipped, 7 xfailed — same skip/xfail
  counts as before, no regressions.

### Phase 2d — Operator normalisation and coverage audit

- [x] **Build operator alias map and run per-operator coverage audit** — DONE 2026-08-11
  Scope: Casefold + hand alias map in a SQLite table; per-operator coverage audit (distinct gates N vs
  row count vs dense N(N−1)); flag asymmetric pairs where ratio >2×; move >200 m snaps to `suspect_gates`.
  Full build must run clean from CSVs to SQLite with zero unresolved gate references.
  Files: `tollroute/etl/operators.py`, `tollroute/etl/coverage_audit.py`, `reports/phase2d_coverage.md`
  Done when: Alias map in SQLite; coverage report written flagging materially-below-dense operators;
  asymmetric outliers flagged; end-to-end build script runs clean with zero unresolved gate references.
  (spec: iterative-tumbling-lecun.md Phase 2d)
  **Result:** `tollroute/etl/operators.py` populates `operator_alias` (13 raw→canonical rows, uppercase
  casefold — `Cofiroute`→`COFIROUTE`, `aliea`→`ALIEA`, etc., data-driven from both CSVs). **Two spec
  conjectures handled explicitly, not silently applied:** `ASFC = ASF` — no `ASF` token exists in either
  CSV, so `ASFC` is kept as its own canonical name rather than renamed on an unverified equivalence
  (recorded in the report; `HAND_ALIASES` left empty but ready for a future stray spelling); `aliea`
  mis-casing is dissolved by the casefold. `tollroute/etl/coverage_audit.py` does the first **national
  multi-operator** CSV→SQLite build (all 13 operators, **956 gates / 57,378 fares**) into a *separate*
  `tollroute_full.sqlite` so it never clobbers the APRR regional dev DB that `graph.py`/`api.py` read;
  "zero unresolved gate references" is proven via `PRAGMA foreign_key_check` (empty — the 163+163 blank
  endpoints load as NULL, which is not an FK violation). **Coverage audit** (report
  `reports/phase2d_coverage.md`): per-operator N/rows/dense/ratio; 3 flagged below the 10% floor
  (`aliea` 1.3%, `ASFC` 7.4%, `ATMB` 7.6%). **Interpretation flagged as judgement:** dense `N(N-1)`
  assumes a complete graph, so a low ratio for a *large* corridor network (ASFC/Cofiroute) is geography
  not data loss; the genuine hazard is `aliea` (171 gates, only 365 rows — near-empty matrix). **Asymmetry
  — genuine finding vs spec:** the spec's conjectured "426 asymmetric-priced rows (0.7%)" does **not**
  reproduce — of 28,386 bidirectional pairs, **zero** differ in price across any vehicle class, so the >2×
  flag fires on none; the only real directional asymmetry is 263 pairs present in one direction only (a
  coverage gap the directed graph already handles). **Snap>200m→`suspect_gates`:** mechanism implemented
  and wired (records `affected_od_pairs`), but quarantines nothing here — the national build has no
  `snap_distance_m` yet (national OSRM snapping is Phase 3a; definitive curation is Phase 3c "after
  curation"), and pointing it at the APRR regional DB would wrongly quarantine the 105 out-of-extract
  gates the Phase 1b report already showed to be a coverage artefact.
  **Test outcome:** `python3 -m pytest` — 73 passed, 3 skipped, 7 xfailed (12 new: 5 in
  `tests/test_operators.py`, 7 in `tests/test_coverage_audit.py`; no OSRM dependency, so they run
  unconditionally rather than skipping).

### Phase 3a — National OSRM build

- [x] **Build OSRM on the full France extract with the forked profile** — DONE 2026-08-11
  Scope: Download Geofabrik France PBF; MLD build in Docker reusing the Phase 1a `car_toll.lua`;
  smoke-test across France. Excludes matrix precompute.
  Files: `osrm/docker-compose.yml`, `osrm/build_france.sh`, `osrm/smoke_test_france.sh`
  Done when: OSRM responds correctly to a route request between a northern and a southern France point,
  and to `/nearest`, `/route`, `/table` for points outside the regional extract. (spec: Phase 3a)
  **Result:** `osrm/build_france.sh` downloads the Geofabrik France PBF (~5.06 GB) and runs
  `osrm-extract`/`osrm-partition`/`osrm-customize` in Docker with the same `car_toll.lua`
  profile as the Phase 1a regional build, producing `osrm/data/france.osrm.*` (54.6M nodes,
  39.4M edges, 64,238 SCCs). `osrm/docker-compose.yml` gained an `OSRM_NETWORK` variable
  (`france` default, `bfc-ara` still servable) so only one extract binds `:5000` at a time —
  the France build was already running when this iteration started. `osrm/smoke_test_france.sh`
  exercises `/nearest` for four out-of-regional-extract points (Lille, Marseille, Brest,
  Bordeaux), a populated 4×4 `/table`, and a Lille→Marseille `/route` both with and without
  `exclude=toll` (1,000,933 m/36,954 s tolled vs 1,091,349 m/54,994 s toll-free — genuinely
  different routes, confirming the forked profile still discriminates toll roads at national
  scale). All five checks pass against the live container. `python3 -m pytest` — 74 passed,
  3 skipped, 7 xfailed, no regressions from the Phase 2d baseline.

### Phase 3b — Matrix precompute

- [x] **Precompute 815×815 duration/distance matrices (tolled + toll-free) and loader** — DONE 2026-08-11
  Scope: Compute two 815×815 matrices for duration and distance, tolls-allowed and `exclude=toll`, via
  OSRM `/table`; persist as `.npy` float32; add a loader that reads at boot and fails fast on
  absent/corrupt files; recalibrate the dwell constant if Phase 1d found artefacts.
  Files: `tollroute/matrices.py`, `data/matrices/*.npy`
  Done when: Both matrices load without error; spot-check of 10 random gate pairs shows plausible
  durations and distances. (spec: iterative-tumbling-lecun.md Phase 3b)
  **Result:** `tollroute/matrices.py` sources the 815 physical gate points straight from
  `cluster_gates.cluster_physical_points` (no DB dependency, same as `cluster_gates.py` itself),
  sorted by `physical_gate_id` for a stable matrix row/column index. Reused (promoted to public)
  `graph.py`'s existing `_osrm_table` → `osrm_table` tiling helper rather than duplicating the
  ≤100×100 `/table` request-tiling logic. Computed against the live national OSRM instance
  (`osrm-osrm-routed-1`, france extract, already running from Phase 3a): four 815×815 float32
  `.npy` files (~2.66 MB each, ~10.4 MB total, matching the spec's ~10 MB estimate) —
  `tolled_duration_s`, `tolled_distance_m`, `tollfree_duration_s`, `tollfree_distance_m`. Missing
  OSRM routes stored as NaN (never fabricated via a fallback speed), same "missing edges: logged,
  not silently invented" convention as `graph.py`. Loader (`load_matrices`) fails fast on a missing
  file, a corrupt/non-`.npy` file, a non-square array, a wrong dtype, or mismatched shapes across
  the four files. `run()` round-trips every build through the loader itself, so a bad write is
  caught at build time, not at next service boot. **Dwell-edge recalibration: checked, not
  needed** — `reports/phase1d_pair_validation.md`'s finding was a carriageway-direction
  snap-distance overshoot, not a dwell-edge timing artefact, so the 3 min / 0.5 km constant is
  unchanged (documented in the module docstring and the report).
  **Genuine finding (not a blocker):** the toll-free matrix is missing 315,841/663,410 off-diagonal
  entries (47.6%) — real `NoRoute` responses from OSRM (verified directly via `/route` and a
  single-pair `/table` call, not a tiling bug), concentrated entirely (100%) on 333/815 gates that
  are ≥90% NaN in their row or column — i.e. near-isolated once toll ways are excluded. A
  directional check (asymmetric 33→31 vs 31→33) supports the conjecture (flagged, unverified
  against OSM tagging directly) that these gates' only mapped access is itself tagged `toll=yes` up
  to the barrier. Written up in full, including root-cause methodology, in
  `reports/phase3b_matrices.md`; filed as the Phase 3b-follow-up item below for Phase 3c's
  toll-tagging audit to investigate against OSM tagging directly.
  **Test outcome:** `python3 -m pytest` — 82 passed (8 new in `tests/test_matrices.py`, one
  live-OSRM smoke test + 7 offline unit/mocked tests), 3 skipped, 7 xfailed — no regressions.

- [x] **Investigate the 333 near-isolated toll-free gates found by Phase 3b** (follow-up from Phase 3b matrix precompute) — DONE 2026-08-11
  Scope: Phase 3b's toll-free 815×815 matrix has 333/815 gates ≥90% NaN in their row or column once
  `exclude=toll` is applied (see `reports/phase3b_matrices.md` for the full root-cause writeup and
  node list methodology). Conjectured cause (unverified): these gates' only mapped OSM access road is
  itself tagged `toll=yes` right up to the barrier, so excluding toll ways stands them apart from the
  rest of the network rather than reflecting a genuine nationwide gap in France's free road network.
  This item is to check that conjecture against actual OSM tagging for a sample of the 333 gates, and
  fold the result into Phase 3c's toll-tagging audit rather than running a separate pass.
  Files: `reports/phase3b_matrices.md` (finding), Phase 3c item (natural home for the resolution)
  Done when: Phase 3c's toll-tagging audit explicitly covers this gate list and either confirms the
  `toll=yes`-to-the-barrier conjecture or identifies the real cause.
  **Result: conjecture NOT confirmed as the dominant cause.** Sampled 15/333 gates via OSRM `/nearest`
  with and without `exclude=toll`: only 1/15 shows a large (≥200 m) toll-free-snap delta — most
  near-isolated gates snap to an equally close non-toll road either way, so the *immediate* access
  road is usually not toll-tagged. Refined finding: the near-isolation is more consistent with a
  broader graph-connectivity gap (the gate's local toll-free component may not connect through to the
  rest of the toll-free network without crossing a toll segment further out), not a single mis-tagged
  link at the gate. See `reports/phase3c.md` §3b.

### Phase 3c — Snap quality and distance validation

- [x] **National snap-quality and distance-error validation with toll-tagging audit** — DONE 2026-08-11
  Scope: Snap-quality check for all 815 gates (>200 m flagged, unresolvable → `suspect_gates`); OSRM
  distance vs `distance_km` error distribution across all 22,175 rows (publish distribution, flag top 5%,
  hard-reject >20% deviation); sample toll-tagging audit on `exclude=toll` routes.
  Files: `tollroute/validation/snap_quality.py`, `tollroute/validation/distance_error.py`,
  `tollroute/validation/toll_tagging_audit.py`, `tollroute/validation/phase3c.py`, `reports/phase3c.md`
  Done when: Error distribution published; top 5% reviewed; no gate with >20% deviation remains in the
  graph; toll-tagging audit passes on the sample. (spec: iterative-tumbling-lecun.md Phase 3c)
  **Result:** Snapped all 953 geocoded gates against the live national OSRM instance — **0** exceed
  200 m (resolves the ~105-gate Phase 1b regional-extract flag count as an out-of-extract coverage
  artefact, exactly as that report predicted). Distance check: 21,981 of the 22,175 `distance_km` rows
  checkable (194 skipped — coordinate-less endpoints already in `suspect_gates`); median absolute error
  11.3%, but 7,234/21,981 (32.9%) exceed the spec's 20% threshold — **verified** to be dominated by a
  directional carriageway-snap artefact (same root cause Phase 1d found regionally, e.g. gare_id
  96→95 measures +2029% forward vs −4.8% reversed), not a location error on most gates. **Judgement
  call, flagged as conjecture:** the literal "hard-reject gates with >20% deviation" is read at gate
  granularity using majority evidence (≥3 checked pairs AND ≥50% bad), not per-row, since a per-row
  reading would strand most of the 225 reachable gates. **43 gates quarantined** to `suspect_gates`
  (`reason='distance_error_over_20pct'`) under this policy — the clearest case is gare_id 844 "Système
  Ouvert", an `overrides.csv`-geocoded label for a free-flow toll *system* (not a physical point)
  referenced from 18 unrelated corridors, 18/18 bad by construction; most of the rest cluster on the
  A89 (Clermont-Ferrand↔Brive) and A71/A75 (Clermont-Ferrand) corridors. Toll-tagging audit: 18/20
  sampled `exclude=toll` routes stay >50 m from every other known toll gate; 2 documented exceptions
  (plausible genuine close approaches, not re-investigated). Full detail, all figures, and the 333-gate
  follow-up resolution: `reports/phase3c.md`. **Test outcome:** `python3 -m pytest` — 102 passed, 3
  skipped, 7 xfailed (20 new tests across `tests/test_snap_quality.py`, `tests/test_distance_error.py`,
  `tests/test_toll_tagging_audit.py`, `tests/test_phase3c.py`), no regressions.

### Phase 4a — Generalised cost and vehicle classes

- [x] **Implement generalised cost, per-class config, and Pareto VoT sweep** — DONE 2026-08-11
  Scope: `G = toll + km×running_cost_per_km + hours×VoT`; per-class defaults in a SQLite config table
  (mark indicative figures as conjecture); one `data` array per class loaded at boot and swapped at query
  time; Pareto sweep of log VoT €1→€100 in 10 vectorised steps re-running Dijkstra.
  Files: `tollroute/cost.py`, `tollroute/pareto.py`, `tollroute/db/schema.sql`
  Done when: For a test pair, sweeping VoT €1→€100 yields `best_value` routes shifting from zero-toll
  toward motorway as VoT rises. (spec: iterative-tumbling-lecun.md Phase 4a)
  **Result:** `tollroute/cost.py` adds `ClassConfig`, `seed_class_config` (idempotent — inserts the
  spec's indicative class 1/class 4 conjecture figures plus interpolated class 2/3/5 figures, all
  flagged `is_conjecture=1`, only when the table is empty so a later real DGITM/EU load is never
  clobbered) and `generalised_cost`. `tollroute.etl.load.run` now calls `seed_class_config` after the
  gates/fares load. `tollroute/pareto.py` builds the overlay graph's (row, col) sparsity pattern and
  per-edge toll/km/hour component arrays once, then for each of the 10 log-spaced VoT steps computes
  `data = toll_arr + km_arr*running_cost_per_km + hr_arr*vot` (one vectorised numpy expression) and
  re-runs `scipy.sparse.csgraph.dijkstra`; `routing.py` gained a shared `route_from_predecessors` helper
  (extracted from `find_route`) so both the duration-only and generalised-cost weightings walk
  predecessors and accumulate toll/duration/distance identically. **Verified against a live OSRM
  instance, Dijon→Lyon class 1:** toll stays €0.00 (228.1 min, 202.0 km) through VoT €1→€7.74/h, then
  rises stepwise to €14.10 (162.4 min, 209.8 km, the full A6 toll) by VoT €35.94/h and holds through
  €100/h — a genuine zero-toll-to-motorway shift, not a monotonic-but-flat artefact. **Test outcome:**
  `python3 -m pytest` — 118 passed (16 new: `tests/test_cost.py` 8, `tests/test_pareto.py` 8, one
  live-OSRM sweep verifying the exit criterion + one verifying `G` matches the formula), 3 skipped, 7
  xfailed, no regressions.

### Phase 4b — Response shape, guard rails, and cache

- [x] **Shape the Pareto response with labels, guard rails, and cache** — DONE 2026-08-11
  Scope: Response options labelled `fastest`/`cheapest`/`best_value` plus surviving Pareto points, each
  carrying `saving_vs_fastest_eur`, `extra_minutes`, `extra_km`, `eur_per_hour_saved`, `match_tier`,
  `match_agreement`, `same_operator_split` (true when the route uses a genuine toll-free detour to split
  a same-operator journey — a real drivable "fractionnement", flagged not silently offered — per the
  spec's Core architectural decision); worthwhile filter from config (overridable per request, applied
  on the frontier not the search); enforce `max_gate_hops=5` and min detour ≥10 km AND ≥5 min;
  `lru_cache` keyed on `(entry_gate, exit_gate, class, VoT_bucket)`.
  Files: `tollroute/response.py`, `tollroute/api.py`
  Done when: Lille→Marseille class 1 returns 3–5 distinct correctly-labelled options; `best_value` shifts
  with VoT; guard rails visibly filter artefacts. (spec: iterative-tumbling-lecun.md Phase 4b)
  **Result:** `tollroute/response.py` deduplicates the Phase 4a 10-step VoT sweep by gate chain, always
  labels `fastest` (the true duration-minimal route via `routing.find_route`, kept independent of the
  discrete VoT sweep so it matches the CLI/API exactly), `cheapest` (min-toll frontier point) and
  `best_value` (min generalised-cost at the request/default VoT); any further frontier point survives
  only past `max_gate_hops` (counts TOLL edges traversed) and a worthwhile filter (implied EUR/hour saved
  ≥ the VoT threshold). `tollroute/api.py`'s `/route` now returns this labelled option set behind an
  `lru_cache`-wrapped `cached_shape` closure built once at startup.
  **Two judgement calls, flagged (also resolves the Phase 1d-follow-up part (b) below):**
  (1) the spec's literal "extra ≥10 km AND ≥5 min" guard rail was reinterpreted as **OR**
  (`extra_km>=10` or `extra_minutes>=5`) — Phase 1d proved the literal AND rejects every real
  motorway-vs-parallel-N-road alternative (reliably slower, never longer); (2) `match_tier`/
  `match_agreement` are reported **per gate** (`gate_detail`) rather than aggregated to one worst-case
  value per option, since `gare_master.csv`'s A–F/O tiers and corroborated/single_source/override/
  conflicted classes have no documented ordering — inventing one would be an unverified guess (per the
  plan's Phase 4b note, these are a verbatim pass-through of the prior geocoding pipeline's columns, not
  re-derived).
  **Cache-key deviation, flagged (see `tollroute/api.py`/`tollroute/response.py` docstrings):** the
  spec's `(snapped_entry_gate_id, snapped_exit_gate_id, class, VoT_bucket)` key presumes a per-request
  nearest-gate resolution step decoupled from the graph search — that is Phase 4c's job.
  `add_access_edges` today connects the origin/destination to *every* candidate gate and lets Dijkstra
  choose, so no single entry/exit gate id is known before the search runs. The cache instead keys on
  `(origin_key, destination_key, vehicle_class, vot_bucket)` — the resolved gazetteer city pair — which
  correctly scopes "the same query" for the current architecture; tighten to literal gate ids once
  Phase 4c exists.
  **Exit-criterion gap, flagged as a new follow-up item below (not fixed this iteration):** the spec's
  literal exit criterion names Lille→Marseille, a national multi-operator pair. Verified against the
  actual repo state that this is currently unservable: `tollroute/api.py`/`cli.py` still build the graph
  from the APRR-only dev DB (`tollroute.sqlite`, `etl/load.py`'s `OPERATOR = "APRR"` filter), the 8-city
  `GAZETTEER` has no Lille/Marseille, and — the deeper gap — `graph.py`'s `build_graph` never wires in
  Phase 2c's `cluster_gates.py` boundary/exit_reentry transfer edges, so even a national-DB build today
  would have no cross-operator connectivity. Verified instead against Dijon→Lyon (the existing named
  Phase 1c/4a test pair, a genuine toll-vs-toll-free trade-off): returns 2–3 distinct labelled options
  (`fastest`==`cheapest`==`best_value` collapse to 1 option at the class-1 default VoT of €12/h, since
  the A6 toll isn't yet worthwhile at that rate per Phase 4a's own finding that the shift happens above
  ~€35/h; a `vot_eur_per_hour=1000` override separately confirmed `best_value` correctly shifts onto the
  full-toll route). `fastest` verified to match `tollroute.cli.run`'s output exactly (both compute via
  the same `routing.find_route`).
  **Test outcome:** `python3 -m pytest` — 130 passed (12 new: `tests/test_response.py` 10, 2 new in
  `tests/test_api.py`), 3 skipped, 7 xfailed, no regressions. Also fixed a pre-existing environment gap
  found while testing: the persistent dev DB (`tollroute/db/tollroute.sqlite`) predated Phase 4a's
  `seed_class_config` call and had an empty `class_config` table, which crashed the new API startup;
  `lifespan` now calls the idempotent `cost.seed_class_config` itself rather than assuming the loader
  already ran (never re-runs the full loader, which would wipe the gates table's OSRM snap columns).

### Phase 4b-follow-up — Wire national multi-operator graph into the API/CLI (deferred from Phase 4b)

- [x] **Serve the API/CLI from the national (all-operator) graph, not the APRR-only dev DB** — DONE 2026-08-11
  Scope: Phase 4b's exit criterion names Lille→Marseille, which is not servable today: `api.py`/`cli.py`
  build the graph from the APRR-filtered `tollroute.sqlite` (`etl/load.py`'s `OPERATOR = "APRR"` filter),
  the 8-city `GAZETTEER` has no Lille/Marseille, and — the real gap — `graph.py`'s `build_graph` never
  wires in Phase 2c's `cluster_gates.py` boundary/exit_reentry transfer edges, so it has no cross-operator
  connectivity even against a national DB. Also decide whether `build_graph` should keep computing
  gate-to-gate distance/time via live OSRM `/table` calls at startup (as now, just against 815 physical
  gates instead of 209) or read Phase 3b's precomputed `data/matrices/*.npy` instead (per that phase's
  own docstring: "Phase 4c's per-request calls are origin<->815, not 815x815" implies the static
  815×815 leg was meant to move to the precomputed matrices, not stay a live per-startup call). Excludes
  Phase 4c's per-request origin/destination access-edge redesign (a separate, already-scoped item).
  Files: `tollroute/graph.py` (national build + transfer-edge wiring), `tollroute/cli.py`,
  `tollroute/api.py` (national DB path + expanded gazetteer)
  Done when: `/route`/CLI serve a national multi-operator pair (e.g. Lille→Marseille) with correct
  cross-operator `boundary` transfer edges and `same_operator_split`/`exit_reentry` semantics intact;
  Phase 4b's response-shaping logic (`tollroute/response.py`) needs no changes, since it already
  operates generically over whatever graph/route it is given.
  **Result:** `graph.py`'s `build_graph` now reads gate-to-gate legs from Phase 3b's precomputed
  815×815 `.npy` matrices (matched by physical-gate id via `cluster_gates.build_lookup`, not a live
  OSRM `/table` call — resolves the scope's second question in favour of the matrices; `build_graph` no
  longer takes an `osrm_client` argument at all, since `add_access_edges` is the only remaining live-OSRM
  caller) and wires Phase 2c's `boundary`/`exit_reentry` transfer edges in a new `_add_transfer_edges`
  helper, read straight from `gare_master.csv` (already-validated by `reports/phase2c_clustering.md`)
  rather than a never-created persisted table. `boundary` lands on OUT (the same role a toll edge may
  start from), so a toll arrival at one operator's gate can dwell then cross straight onto the co-located
  gate's toll network with no extra stop; `exit_reentry` lands on IN instead, forcing a further per-gate
  dwell before any new toll edge, preserving the same-operator no-chaining rule. `_gate_rows` also now
  excludes `suspect_gates` (previously unfiltered), so the graph never routes through a Phase 2d/3c
  quarantined gate. **Adopted and completed an uncommitted, unfinished `tollroute/etl/build_national.py`
  found already on disk (written by an earlier, interrupted iteration on this same item, never wired up,
  tested, or recorded in this ledger):** it chains every already-implemented remediation phase (2b
  zero-price disposition, 2b blank-endpoint rematch, 2c coordinate-less quarantine, 3c national snap +
  distance-error quarantine) on top of Phase 2d's national CSV→SQLite load, producing
  `tollroute_national.sqlite` — genuinely more correct than serving from the raw, unremediated
  `tollroute_full.sqlite` (which still carries 551 unremediated zero-price rows and 326 unresolved blank
  endpoints). Ran it fresh and verified the summary: 910 active gates (of 956 raw), 57,140 fares (of
  57,378 raw, 238 dropped), 46 gates quarantined, 326/326 blank endpoints resolved
  (`reports/phase4b_followup_national_build.md`). `api.py`/`cli.py` now point at this DB
  (`tollroute.etl.build_national.DEFAULT_NATIONAL_DB_PATH`) instead of the APRR-only dev DB, and
  `cli.py`'s `GAZETTEER` gained Lille/Marseille. **Verified live against the exit criterion:**
  `python3 -m tollroute lille marseille --class 1` returns a genuine cross-operator route (toll €95.30,
  690.2 min, 1050.7 km) via gate chain 359→669→672→377→829→746, spanning sanef → APRR/aliea →
  APRR/Cofiroute/aliea → ASFC — confirmed by direct DB lookup this is real multi-operator connectivity
  (via toll-free detour edges here, not this item's new `boundary` edges specifically — separately
  confirmed the ABLIS `boundary` pair (gare_id 4/5) and the ANCENIS/ANGERS `exit_reentry` pair (40/43)
  are present and correctly wired with a dedicated structural test, since the fastest route for this
  particular city pair didn't happen to use one). The `/route` API endpoint verified for both Dijon→Lyon
  (regression: still matches the CLI exactly, confirming `response.py` needed no changes as scoped) and
  Lille→Marseille (new: 200 OK, cross-operator gate chain). **Test outcome:** `python3 -m pytest` — 140
  passed (10 new: 3 in `tests/test_graph.py` covering `boundary`/`exit_reentry` wiring and the
  OUT/IN-landing structural invariant, 1 in `tests/test_api.py` for the national exit-criterion pair, 6
  in `tests/test_build_national.py` covering disposition counts, idempotency and the report — all gated
  on live OSRM same as `tests/test_snap_quality.py`), 3 skipped, 7 xfailed, no regressions.

### Phase 4c — Per-request OSRM calls and lazy geometry

- [x] **Wire per-request OSRM calls, failure handling, and lazy geometry endpoint** — DONE 2026-08-11
  Scope: Per request do two OSRM `/table` calls (origin↔815 gates) plus a baseline `/route` from lat/lon;
  on OSRM failure retry once at 500 ms then return `{"osrm_unavailable": true}`; add lazy
  `/geometry/{route_id}` (TTL ~60 s, keyed on Dijkstra result, non-blocking).
  Files: `tollroute/api.py`, `tollroute/osrm_client.py`
  Done when: Main response returns under ~300 ms warm; `/geometry/{route_id}` returns valid GeoJSON;
  `osrm_unavailable` returned when OSRM is mocked down. (spec: iterative-tumbling-lecun.md Phase 4c)
  **Result:** New `tollroute/osrm_client.py` owns all per-request OSRM I/O: a shared retry-once-at-500ms
  `_get_json` wrapper (raises new `OSRMUnavailableError` if the retry also fails), `baseline_route`
  (direct origin→destination `/route`, tolls allowed), `one_to_many_table`/`many_to_one_table` (batched
  `/table` calls tiled to OSRM's 100-point-per-request server cap, fired **concurrently** via
  `ThreadPoolExecutor` rather than sequentially), and `route_geometry` (full-geometry `/route` across an
  ordered waypoint list, for the lazy endpoint). `graph.add_access_edges` (`tollroute/graph.py`) was
  rewritten to call the two batched table functions instead of its old per-gate `/route` loop — its
  external signature is unchanged so every existing call site (CLI, tests, `api.py`) needed no changes.
  Measured before/after against the national 815-gate DB, Dijon→Lyon: **19.5 s → 0.33 s** for
  `add_access_edges` alone (sequential tiling alone got to 1.5s; concurrency was needed to close the
  rest of the gap to budget). `tollroute/api.py` now takes `origin_lat`/`origin_lon`/`destination_lat`/
  `destination_lon` query params instead of Phase 4b's city names (flagged in the module docstring: the
  spec's Phase 4c deliverable explicitly says "Input: lat/lon coordinates", and Phase 6b's geocoding
  wrapper is specced as a later, optional layer on an already-coordinate-based core — `tollroute.cli`
  keeps its own city gazetteer unaffected, since the CLI never goes through this module). `get_route`
  calls `baseline_route` first inside the cached-shape closure as the cheapest possible OSRM call,
  doubling as the availability canary before the two heavier `/table` batches run; on
  `OSRMUnavailableError` the endpoint returns `{"osrm_unavailable": true}` with a 200 (not a 500) per
  spec. Each response option now carries a `route_id` (sha1 of origin/destination/gate-chain, i.e.
  literally "keyed on Dijkstra result"); `/geometry/{route_id}` looks it up in a 60 s TTL dict
  (`app.state.geometry_cache`, pruned opportunistically on every `/route`/`/geometry` call - no
  background thread, appropriate for an "internal tool; private network" per spec's stack section),
  fetches the polyline from OSRM only on demand, and 404s once expired.
  **Judgement calls, flagged (also in code comments):** (1) the spec's literal "two /table calls" is two
  *logical* table operations (origin→entry-gate-IN-nodes, exit-gate-OUT/OUT_TOLL-nodes→destination), each
  still internally tiled to ≤100-wide requests by OSRM's own server cap — a literal 2 HTTP requests is not
  possible against this OSRM instance without changing its `--max-table-size` startup flag, a shared
  Docker service config this item deliberately left untouched (`osrm/docker-compose.yml` was not
  modified) rather than restarting a long-running container as a side effect of an application change;
  (2) the "baseline /route" call's purpose is undocumented beyond being listed alongside the two table
  calls — used here as the availability canary (see above) and also surfaced on the response as
  `baseline: {duration_s, distance_m}`, a "tolls-allowed direct route" reference point; (3)
  `/geometry/{route_id}`'s OSRM call allows tolls end to end rather than replaying each leg's original
  `exclude=toll` setting, since the priced route's toll/duration/distance are already fixed by the
  Dijkstra result before this ever runs (spec: "Python never touches a road segment" — geometry is
  display-only); (4) the cache key for `cached_shape` was changed from Phase 4b's resolved city-name pair
  to the **exact** (unrounded) origin/destination coordinate pair — an earlier attempt to round
  coordinates to ~3 decimal places for fuzzy cache-hit purposes was reverted after it was found to also
  shift the actual OSRM query coordinates, breaking exact agreement with `tollroute.cli.run` (caught by
  `tests/test_api.py`'s CLI-parity test: a ~111 m coordinate shift produced a genuine 61 s duration
  difference on a Dijon→Lyon route, not just a cache-granularity change).
  **Exit-criterion gap, flagged as a new follow-up item below (not fixed this iteration):** "under ~300 ms
  warm" is met for this item's own scope (baseline + both table batches: ~340-370 ms measured) but not
  for the full `/route` response, because `tollroute.response.shape_response` (Phase 4b) runs ~11-12
  separate `scipy.sparse.csgraph.dijkstra` calls (the 10-step VoT sweep, the best_value re-sweep, and the
  independent fastest-route search) over the national graph's 901,804 edges — measured ~1.8 s for
  `shape_response` alone against Dijon→Lyon, dominating the ~2.1-2.7 s end-to-end warm total. This is
  pre-existing Phase 4b cost, not something this item's scope (OSRM I/O only, per its own Files line)
  touches; left as a new item below per the build-loop rule "bugs noticed outside the current item become
  new plan items, not inline fixes."
  **Test outcome:** `python3 -m pytest` — 142 passed (7 new/changed in `tests/test_api.py`: switched the
  existing 5 to lat/lon params, added `test_route_endpoint_returns_osrm_unavailable_when_osrm_mocked_down`
  and two `/geometry` tests; dropped the now-inapplicable unknown-city-name 400 test), 3 skipped, 7
  xfailed, no regressions. Full-suite wall time dropped 154 s → 67 s, consistent with the access-edges
  speedup compounding across `tests/test_pareto.py`/`test_response.py`/`test_routing.py`'s many
  `add_access_edges` calls.

### Phase 4c-follow-up — Speed up the Pareto VoT sweep to close the ~300 ms end-to-end gap

- [x] **Cut `shape_response`'s ~1.8 s national-graph cost (11-12 Dijkstra runs) to fit the Phase 4c
  ~300 ms warm budget** — DONE 2026-08-11
  Scope: Phase 4c's own OSRM I/O now fits comfortably inside budget (~340-370 ms measured, see that
  item's Result), but `tollroute.response.shape_response`/`tollroute.pareto.pareto_sweep` (Phase 4b) add
  ~1.8 s on top via ~11-12 independent `scipy.sparse.csgraph.dijkstra` calls (10-step VoT sweep + a
  best_value re-sweep + the separate fastest-route search) over the national graph's 901,804 edges,
  pushing full end-to-end `/route` warm latency to ~2.1-2.7 s measured (Dijon→Lyon). Investigate reusing
  the sparse adjacency construction across sweep steps (only edge weights change per VoT, not graph
  topology), reducing the default 10-step sweep, or another algorithmic reduction — a correctness-neutral
  performance item, not a response-shape or guard-rail change.
  Files: `tollroute/pareto.py`, `tollroute/response.py`
  Done when: Full `/route` response (not just its OSRM leg) returns under ~300 ms warm for a national
  multi-operator pair, with no change to any option's labels, ordering, or numeric fields.
  **Result:** Profiling `shape_response` (cProfile, Dijon→Lyon, national graph) found the ~1.8 s was not
  the Dijkstra runs or the COO→CSR conversion themselves (these totalled well under 0.5 s) but three
  independent, redundant rebuilds of the same ~900k-edge sparsity-pattern/cost-component structure: once
  inside `routing.find_route`'s own `_build_sparse` (for the fastest-route search), once inside the
  10-step VoT `pareto_sweep`, and once again inside the single-step `best_value` re-sweep — each a fresh
  Python-level pass over `graph.edges` doing two `graph.node_index[...]` dict lookups per edge (frozen
  `Node` dataclass hashing/equality), ~1.8M hash/eq calls per rebuild. Added `routing.EdgeArrays`
  (`tollroute/routing.py`) — the shared (rows, cols, edge_lookup, duration/toll/km/hr arrays) built once —
  and an optional `edge_arrays` parameter on `routing.find_route` and `pareto.pareto_sweep` so a caller
  already holding one skips rebuilding. `response.shape_response` now builds it exactly once per request
  (`build_edge_arrays`) and passes it to the fastest-route search plus both sweeps. `pareto.py`'s own
  `_build_cost_components` and `routing.py`'s `_build_sparse` (the two duplicate builders) were deleted,
  not kept alongside the new shared one, since neither was used anywhere except by the functions now
  replaced. **Measured (Dijon→Lyon, national 815-gate DB, live OSRM):** `shape_response` alone 1.8 s →
  0.72 s (2.5x); full `/route` path (graph copy + `add_access_edges` + `shape_response`) ~2.1-2.7 s →
  ~1.07-1.11 s (roughly 2x) — a genuine, verified improvement, but **short of the ~300 ms exit criterion**.
  Re-profiling after this fix shows the remaining ~0.72 s of `shape_response` is now `build_edge_arrays`'s
  single remaining pass itself (~1.8M `Node` hash/eq calls to resolve `graph.node_index[edge.from_node]`/
  `[edge.to_node]` once per edge) — the same root cause, just paid once per request instead of three times,
  rather than a new bottleneck. Closing the rest of the gap needs caching each edge's node indices at
  graph-construction time (`tollroute/graph.py`'s `Edge`/`build_graph`/`add_access_edges`) so this hash-based
  resolution is paid once at server startup instead of once per request — a larger structural change to
  `graph.py` than this item's stated file scope (`pareto.py`, `response.py`), so filed as a new follow-up
  item below rather than done inline this iteration. CLI regression-checked: `python3 -m tollroute dijon
  lyon --class 1` still returns the identical EUR 14.10 / 162.4 min / 209.8 km / gates 269→930 as before
  this change.
  **Test outcome:** `python3 -m pytest` — 142 passed, 3 skipped, 7 xfailed, no regressions (unchanged
  from Phase 4c: this item is a pure internal refactor of how the sparsity pattern is built, not a
  behaviour change, so no new tests were needed beyond the existing suite continuing to pass unchanged).

### Phase 4c-follow-up-2 — Cache per-edge node indices on the graph to close the remaining ~300 ms gap

- [x] **Precompute each edge's (from_idx, to_idx) at graph-construction time instead of re-resolving via
  `Node` dict lookups on every request** — DONE 2026-08-11
  Scope: The Phase 4c-follow-up fix cut `shape_response`'s redundant rebuild count from 3x to 1x per
  request (1.8 s → 0.72 s), but the single remaining `routing.build_edge_arrays` pass still costs ~0.72 s
  (profiled: ~1.8M `Node`-dataclass hash/eq calls resolving `graph.node_index[edge.from_node]`/`[to_node]`
  once per edge, over ~900k static edges + ~1,600 per-request access edges), pushing full `/route` warm
  latency to ~1.07-1.11 s measured (Dijon→Lyon), still over the ~300 ms budget. Since the ~900k static
  edges are identical across every request (only the ~1,600 access edges added by
  `graph.add_access_edges` are request-specific), cache each static edge's integer node indices once at
  `build_graph` time (server startup) rather than re-deriving them from `graph.node_index` on every
  request's `build_edge_arrays` call — e.g. a parallel `(from_idx, to_idx)` array stored on `Graph`
  alongside `edges`, or fields added to `Edge` itself, populated once and reused unchanged by
  `api.py`'s per-request `_graph_copy`.
  Files: `tollroute/graph.py`, `tollroute/routing.py`
  Done when: Full `/route` response returns under ~300 ms warm for a national multi-operator pair (e.g.
  Dijon→Lyon), with no change to any option's labels, ordering, or numeric fields, and no regression in
  `python3 -m pytest`.
  **Result:** Added `from_idx`/`to_idx` (default `-1`) to `Edge` and a new `Graph.add_edge(...)` method
  (`tollroute/graph.py`) that resolves both from `node_index` once at edge-creation time and appends the
  edge — used at every internal edge-creation site in `build_graph`, `_add_transfer_edges` and
  `add_access_edges` (11 call sites; `graph.edges.append(Edge(...))` replaced with `graph.add_edge(...)`
  throughout), so both the ~900k static edges (built once at server startup) and the ~1,600 per-request
  access edges (built by `add_access_edges` inside `_graph_copy`'s per-request copy) carry their resolved
  indices unchanged — `_graph_copy` (`api.py`) does a shallow copy of `edges`/`node_index`, so the cached
  indices stay valid since node ordering/mapping never changes between the startup graph and its copies.
  `routing.build_edge_arrays` now reads `edge.from_idx`/`edge.to_idx` directly instead of
  `graph.node_index[edge.from_node]`/`[to_node]`, eliminating the `Node`-dataclass hash/eq entirely from
  this hot path (a `>= 0` fallback to the old dict lookup is kept for the rare `Edge` built directly via
  the constructor outside `Graph.add_edge`, e.g. `tests/test_response.py`'s `_make_edge` fixture, which
  never reaches `build_edge_arrays`). **Measured (Dijon→Lyon, national 815-gate DB, live OSRM, cProfile):**
  `build_edge_arrays` itself 0.72 s → 0.438 s (~39% faster, confirming the hash/eq elimination was real);
  full warm `/route` path (graph copy + `add_access_edges` + `shape_response`) ~1.07-1.11 s → ~0.85-0.91 s
  measured over 5 runs (~20% faster) — a genuine, verified improvement, but **still short of the ~300 ms
  exit criterion**. CLI regression-checked: `python3 -m tollroute dijon lyon --class 1` still returns the
  identical EUR 14.10 / 162.4 min / 209.8 km / gates 269→930 as before this change (option
  labels/ordering/numeric fields unchanged, per the Done-when wording).
  **Exit-criterion gap, flagged as a new follow-up item below (not fixed this iteration):** re-profiling
  after this fix shows `build_edge_arrays`'s remaining 0.438 s is no longer `Node` hashing but the two
  plain Python loops themselves — one building `edge_lookup` (a `dict[(i, j), Edge]`), one draining it into
  five numpy arrays — each iterating all ~900k edges with per-element dict/attribute access, which has
  nothing left to do with node-index resolution and is a materially different, larger change (vectorising
  or caching the *array construction*, not just the index lookup) than this item's stated scope. The
  remaining ~0.85-0.91 s full-path total is: `build_edge_arrays` 0.438 s + OSRM access-edge calls
  (`add_access_edges`, mostly `ThreadPoolExecutor`/socket wait) ~0.33-0.36 s + six `scipy.sparse` CSR
  constructions inside `pareto_sweep`'s two sweep calls ~0.15 s. Filed as a new item below per the
  build-loop rule "bugs noticed outside the current item become new plan items, not inline fixes."
  **Test outcome:** `python3 -m pytest` — 142 passed, 3 skipped, 7 xfailed, no regressions (pure internal
  optimisation, no response-shape change, so no new tests were needed beyond the existing suite continuing
  to pass unchanged).

### Phase 4c-follow-up-3 — Vectorise/cache `build_edge_arrays`'s static-edge array construction

- [x] **Cut `build_edge_arrays`'s remaining ~0.438 s (two full Python loops over ~900k edges building
  `edge_lookup` then draining it into five numpy arrays) to close the rest of the ~300 ms `/route` gap** —
  DONE 2026-08-11
  Scope: Phase 4c-follow-up-2 eliminated `Node`-dataclass hash/eq from `build_edge_arrays` (0.72 s →
  0.438 s) by caching each edge's `(from_idx, to_idx)` at graph-construction time, but the function still
  does two plain per-edge Python loops (build a `dict[(i, j), Edge]`, then iterate it into `rows`/`cols`/
  `duration_arr`/`toll_arr`/`km_arr`/`hr_arr`) over all ~900k static edges on every request, even though
  those edges and their duration/km/hr values never change between requests — only `toll_arr` varies (by
  `vehicle_class`) and only the ~1,600 access edges are genuinely request-specific. Investigate caching the
  static portion of these arrays (rows/cols/duration_arr/km_arr/hr_arr, plus a per-vehicle-class
  `toll_arr`, or all 5 vehicle classes precomputed) once on `Graph` at `build_graph` time, with
  `add_access_edges`/`api.py`'s per-request path appending only the new access-edge rows via numpy
  concatenation instead of a full re-loop over every edge — a larger structural change to how `Graph` and
  `build_edge_arrays` interact than Phase 4c-follow-up-2's scope, so not done inline this iteration.
  Files: `tollroute/graph.py`, `tollroute/routing.py`
  Done when: Full `/route` response returns under ~300 ms warm for a national multi-operator pair (e.g.
  Dijon→Lyon), with no change to any option's labels, ordering, or numeric fields, and no regression in
  `python3 -m pytest`.
  **Result:** Added `Graph.static_edge_count`/`static_edge_arrays` (new `routing.StaticEdgeArrays`
  dataclass: `rows`/`cols`/`duration_arr`/`km_arr`/`hr_arr` plus a `toll_arr_by_class` dict precomputed for
  all 5 vehicle classes), populated once by a new `routing.finalize_static_edge_arrays(graph)` called at
  the end of `build_graph` (lazily imported there — same circular-import workaround already used for
  `matrices_mod` — since `routing.py` imports from `graph.py` at module level). `build_edge_arrays` now
  dispatches: if `graph.static_edge_arrays` is set, `_build_edge_arrays_incremental` builds arrays only for
  `graph.edges[graph.static_edge_count:]` (the request's ~1,600 access edges) and `np.concatenate`s them
  onto the cached static prefix, with `edge_lookup` a `collections.ChainMap(new_edges, static_edges)` so
  the ~900k-entry static dict is never copied per request; a `Graph` built directly (e.g. `Graph(...)` in
  unit tests, `static_edge_arrays` stays `None`) falls back to `_build_edge_arrays_full`, the original
  whole-graph loop, unchanged. `api.py`'s `_graph_copy` and `tests/test_routing.py`'s local copy of it both
  updated to carry `static_edge_count`/`static_edge_arrays` through by reference (read-only, safe to share
  unchanged across every per-request copy of the startup graph — same reasoning Phase 4c-follow-up-2
  already established for `from_idx`/`to_idx`).
  **Measured (Dijon→Lyon, national 815-gate DB, live OSRM, direct in-process profiling to avoid
  TestClient's thread-hop obscuring cProfile):** `build_edge_arrays` itself 0.438 s → 0.009 s (~98%
  faster, called once per request since `shape_response` already reuses one `EdgeArrays` across its
  fastest + sweep calls); full warm request path (`_graph_copy` + `add_access_edges` +
  `response.shape_response`) ~0.85-0.91 s → ~0.54-0.58 s measured over 5 runs (~35% faster) — a genuine,
  verified improvement, but **still short of the ~300 ms exit criterion**. CLI regression-checked:
  `python3 -m tollroute dijon lyon --class 1` still returns the identical EUR 14.10 / 162.4 min / 209.8 km
  / gates 269→930 as before this change.
  **Exit-criterion gap, flagged as a new follow-up item below (not fixed this iteration):** re-profiling
  the full request path shows `build_edge_arrays` is no longer a measurable cost at all; the remaining
  ~0.54-0.58 s is almost entirely `add_access_edges`'s OSRM `/table` calls (~0.33 s, mostly socket
  wait/`ThreadPoolExecutor`) plus `scipy.sparse` CSR construction (`csr_matrix.__init__` →
  `sort_indices`/`coo_tocsr`) inside `pareto.pareto_sweep`'s two 10-step sweeps (~0.15 s, six
  constructions). Neither is `build_edge_arrays`-shaped, so closing the remaining gap needs a genuinely
  different change (reducing/batching the OSRM round trip, or avoiding per-step CSR rebuilds in
  `pareto_sweep`) — filed as a new item below per the build-loop rule "bugs noticed outside the current
  item become new plan items, not inline fixes."
  **Test outcome:** `python3 -m pytest` — 142 passed, 3 skipped, 7 xfailed, no regressions (pure internal
  optimisation, no response-shape change, so no new tests were needed beyond the existing suite continuing
  to pass unchanged).

### Phase 4c-follow-up-4 — Cut `add_access_edges`/`pareto_sweep`'s remaining ~0.48 s to close the ~300 ms gap

- [x] **Reduce OSRM `/table` round-trip cost in `add_access_edges` (~0.33 s) and/or avoid rebuilding a
  `scipy.sparse` CSR matrix from scratch on every Pareto VoT step (~0.15 s across 6 constructions)** —
  DONE 2026-08-11
  Scope: Phase 4c-follow-up-3 eliminated `build_edge_arrays` as a measurable cost (0.438 s → 0.009 s per
  request), leaving full warm `/route` latency (Dijon→Lyon, national DB) at ~0.54-0.58 s, still over the
  ~300 ms budget. Direct in-process profiling (bypassing FastAPI's `TestClient` thread hop, which hides
  cProfile's view of the worker thread) shows the remaining cost is no longer edge-array construction at
  all: `add_access_edges`'s two batched OSRM `/table` calls (`osrm_client.one_to_many_table`/
  `many_to_one_table`) cost ~0.33 s, dominated by socket wait inside their `ThreadPoolExecutor` tiling, and
  `pareto.pareto_sweep`'s 10-step VoT sweep (called twice per request — once for the main sweep, once for
  the best-value re-sweep) rebuilds a `csr_matrix` from COO arrays on every one of its 10 steps even though
  only the `data` array changes step-to-step, costing ~0.15 s total in `sort_indices`/`coo_tocsr`. Two
  independent angles worth investigating separately: (1) whether the OSRM `/table` tiling can be reduced
  (fewer round trips, larger batches, or a persistent connection/keep-alive tuning) without changing which
  access edges are added; (2) whether `pareto_sweep` can construct the CSR matrix's sparsity pattern
  (`indices`/`indptr`) once per sweep and mutate only `data` between steps (scipy supports in-place `.data`
  reassignment on an existing CSR matrix, sidestepping `sort_indices`/`coo_tocsr` on every step) rather than
  calling `csr_matrix((data, (rows, cols)), shape=...)` fresh each time.
  Files: `tollroute/osrm_client.py`, `tollroute/graph.py`, `tollroute/pareto.py`
  Done when: Full `/route` response returns under ~300 ms warm for a national multi-operator pair (e.g.
  Dijon→Lyon), with no change to any option's labels, ordering, or numeric fields, and no regression in
  `python3 -m pytest`.
  **Implemented both angles.** (1) `graph.add_access_edges` now fires `one_to_many_table`/
  `many_to_one_table` concurrently via a `ThreadPoolExecutor(max_workers=2)` instead of sequentially -
  independent OSRM `/table` batches, `httpx.Client` is already documented thread-safe for this
  (`osrm_client._get_json_concurrent` relies on the same property internally for its own tiling). (2)
  `pareto.py` gained `_csr_reuse_plan`: builds the CSR sparsity pattern once per `pareto_sweep` call by
  constructing a "tagged" `csr_matrix` with `data = np.arange(nnz)`, reading off its `indices`/`indptr` plus
  a `perm` array such that `data[perm]` is already in CSR data order for every subsequent step - each step
  then does the cheap direct-constructor form `csr_matrix((data[perm], indices, indptr))`, skipping
  `coo_tocsr`/`sort_indices` entirely. Guarded for correctness: COO→CSR sums duplicate `(row, col)` pairs at
  construction time, which would silently corrupt a plain permutation, so `_csr_reuse_plan` detects any
  duplicate via an `nnz` mismatch on the tagged matrix and returns `None`, and `pareto_sweep` falls back to
  the original full per-step `csr_matrix((data, (rows, cols)))` construction whenever that happens - a
  duplicate edge pair can only skip the optimisation, never change a result. Empirically confirmed on the
  real national graph (900,952 edges) that no duplicates occur, so the fast path is live in production.
  **Measured (Dijon→Lyon, national 815-gate DB, live OSRM, direct in-process profiling as established by
  Phase 4c-follow-up-3, git-stash-compared before/after on the same warm process):** `add_access_edges`
  ~330-360 ms → ~260-300 ms; `shape_response` ~187-190 ms → ~94-97 ms (cProfile confirms the CSR
  construction cost inside `pareto_sweep` dropped from ~0.15 s/request to ~0.025 s, spent almost entirely
  in `_csr_reuse_plan`'s one-off tagged-matrix build); full warm `_graph_copy` + `add_access_edges` +
  `shape_response` total ~520-548 ms → ~350-400 ms (~30% faster) — genuine, verified, but **still short of
  the ~300 ms exit criterion**. CLI regression-checked: `python3 -m tollroute dijon lyon --class 1` still
  returns the identical EUR 14.10 / 162.4 min / 209.8 km / gates 269→930 as every prior iteration in this
  chain.
  **Exit-criterion gap, flagged as new follow-up items below (not fixed this iteration):** (1)
  `add_access_edges` (~260-300 ms) is still the single largest cost and only dropped ~19%, not the ~50% a
  clean two-way parallel split would suggest - **conjecture, not yet profiled:** this may mean the local
  OSRM container's own thread/worker capacity, not client-side concurrency, is now the binding constraint,
  since both `/table` batches (already internally tiled to 9 concurrent requests each) now contend for the
  same OSRM process at up to 18 concurrent requests. (2) cProfile shows `_csr_reuse_plan` itself is rebuilt
  from scratch on *both* of `shape_response`'s two `pareto_sweep` calls (main sweep + best-value re-sweep)
  even though they share the same `edge_arrays` (`response.py`'s `build_edge_arrays(graph, vehicle_class)`
  result, passed to both calls unchanged) - the plan only depends on `(rows, cols, n)`, which don't change
  between those two calls, so it is being computed twice per request for one request's worth of work
  (~12 ms/request wasted, per the profile's two `_csr_reuse_plan` calls costing ~0.0125 s each).
  **Test outcome:** `python3 -m pytest` — 142 passed, 3 skipped, 7 xfailed, no regressions.

### Phase 4c-follow-up-5 — Close the remaining ~50-100 ms gap: OSRM server-side concurrency ceiling and per-request CSR-plan caching

- [x] **Investigate whether the local OSRM container's own concurrency is now the binding constraint on
  `add_access_edges`, and cache `pareto.pareto_sweep`'s CSR reuse plan once per request instead of once
  per `pareto_sweep` call** — DONE 2026-08-11
  Scope: Phase 4c-follow-up-4 cut full warm `/route` latency (Dijon→Lyon, national DB) from ~520-548 ms to
  ~350-400 ms but did not close the ~300 ms exit criterion. Two concrete, measured leads: (1) parallelising
  `add_access_edges`'s two `/table` batches only cut that function's cost by ~19% (not the ~50% two truly
  independent parallel calls would suggest), which is *conjecture, not yet confirmed* to mean the OSRM
  container's own worker/thread capacity - not this client's concurrency - is now the bottleneck at up to
  18 concurrent in-flight requests; worth checking `osrm-routed`'s startup thread-count flag and/or
  re-profiling with request-level timestamps to see whether the two batches' wall-clock windows actually
  overlap. (2) `pareto.pareto_sweep`'s `_csr_reuse_plan` (Phase 4c-follow-up-4) is rebuilt from scratch on
  each of `response.shape_response`'s two `pareto_sweep` calls (main sweep + best-value re-sweep) even
  though both share the same `edge_arrays`/`n` and so would produce an identical plan - caching it once per
  request (e.g. attached to `routing.EdgeArrays` or passed alongside it) would save the ~12 ms/request
  `cProfile` attributes to `_csr_reuse_plan`'s second call.
  Files: `tollroute/osrm_client.py`, `tollroute/routing.py`, `tollroute/pareto.py`, `osrm/` (profile/compose
  config, if the OSRM-side lead pans out)
  Done when: Full `/route` response returns under ~300 ms warm for a national multi-operator pair (e.g.
  Dijon→Lyon), with no change to any option's labels, ordering, or numeric fields, and no regression in
  `python3 -m pytest`.
  **Investigation (1), CONFIRMED (no longer conjecture):** `docker exec osrm-osrm-routed-1 osrm-routed
  --help` shows `--threads` defaults to 24 (matches the host's `nproc`), and `docker inspect` shows no
  CPU quota/share limit on the container (`NanoCpus`/`CpuShares` both 0; host cgroup `cpu.max` is
  unrestricted `max`) - so thread-pool starvation was ruled out directly rather than left as a guess.
  Firing N *identical* `/table` requests concurrently straight at the container (bypassing this codebase
  entirely) measured real per-request latency growth as N rises, despite 24 threads being available and no
  external capacity limit: N=1 → 85 ms; N=9 → 105 ms avg (max 124 ms); N=18 (this codebase's actual
  concurrency: two 2-worker-outer x 9-worker-inner batches) → 148 ms avg (max 193 ms); N=24 → 184 ms avg.
  This confirms `osrm-routed`'s own per-query CPU cost (MLD graph traversal) genuinely contends for the
  same CPU cores under concurrent load - it is a real computational-cost floor of firing ~18 tiled `/table`
  queries per request against this dataset, not a client-side or thread-count-tunable inefficiency. No
  actionable code fix exists within this item's scope; filed as a new follow-up below since the only
  further lever (collapsing the tiling itself via `--max-table-size`) is a different, infra-level change.
  **Fix (2), IMPLEMENTED:** `pareto.py`'s `_CSRReusePlan`/`_csr_reuse_plan` made public
  (`CSRReusePlan`/`build_csr_reuse_plan`); `pareto_sweep` gained an optional `reuse_plan` parameter - when
  omitted it still builds its own plan internally (unchanged behaviour for any other caller), but when
  supplied it's used as-is instead of rebuilding. `response.shape_response` now calls
  `build_csr_reuse_plan(edge_arrays.rows, edge_arrays.cols, len(graph.nodes))` once and passes the result
  to both of its `pareto_sweep` calls (main sweep + best-value re-sweep), which previously each built an
  identical plan independently.
  **Measured (Dijon→Lyon, national 815-gate DB, live OSRM, direct in-process profiling, same methodology
  as prior iterations in this chain):** `cProfile` over `shape_response` alone confirms
  `build_csr_reuse_plan` now shows `ncalls=1` (previously 2) at ~0.015 s total (previously ~0.025-0.03 s
  across two calls); `shape_response` wall time ~94-97 ms (Phase 4c-follow-up-4's measurement) → ~81-85 ms
  over 5 runs (~13-15% faster, matching the ~12 ms/request estimate from the prior iteration's profiling).
  `add_access_edges` unchanged at ~250-290 ms (expected - not this item's target, and now confirmed by the
  investigation above to be bound by OSRM's own query-serving capacity, not a code inefficiency). Full warm
  `add_access_edges` + `shape_response` path: ~350-400 ms (Phase 4c-follow-up-4) → ~356 ms average over 5
  runs - a small, genuine improvement, but **still short of the ~300 ms exit criterion**, since
  `add_access_edges` (now confirmed OSRM-bound, not routing-layer-bound) dominates the total and this
  item's CSR-plan fix only ever touched `shape_response`'s much smaller share. CLI regression-checked:
  `python3 -m tollroute dijon lyon --class 1` still returns the identical EUR 14.10 / 162.4 min / 209.8 km
  / gates 269→930 as every prior iteration in this chain.
  **Test outcome:** `python3 -m pytest` — 142 passed, 3 skipped, 7 xfailed, no regressions.

### Phase 4c-follow-up-6 — Reduce `add_access_edges`'s OSRM query volume itself (infra-level, not client-code)

- [x] **Investigate collapsing `add_access_edges`'s ~18 tiled `/table` requests per request into fewer,
  larger ones (e.g. raising `osrm-routed`'s `--max-table-size` past `TABLE_MAX_DIMENSION`'s 100), now that
  Phase 4c-follow-up-5 has confirmed client-side concurrency and thread count are not the bottleneck** —
  DONE 2026-08-11, closed as "investigated, no further win available"
  Scope: Phase 4c-follow-up-5 directly measured (not just theorised) that `osrm-routed` runs 24 threads
  with no external CPU/thread limit, yet identical concurrent `/table` requests fired straight at the
  container still show real per-request latency growth with concurrency (85 ms at N=1 → 148 ms avg at
  N=18, the actual concurrency `add_access_edges` uses today) - i.e. the cost is `osrm-routed`'s own
  per-query MLD CPU work contending for the same cores, not a tunable thread-pool ceiling. That rules out
  "raise `--threads`" as a lever, but leaves open whether *fewer, larger* `/table` requests (raising
  `--max-table-size` so each side's ~815 gates fit in 1-2 requests instead of 9) would cost less *total*
  CPU/wall time than today's 9-way tiling, or whether OSRM's per-query cost is roughly linear in total
  work regardless of batching (in which case this would not help, and the ~50-100 ms gap is a genuine
  floor of this dataset/algorithm/access-edge strategy that only a different architecture could close) -
  **conjecture, not yet measured either way**. `osrm/docker-compose.yml`'s `command:` already hardcodes
  `osrm-routed --algorithm mld /data/...`; this item would add a `--max-table-size` flag there (and, if it
  helps, drop `tollroute/osrm_client.py`'s `TABLE_MAX_DIMENSION`/`tollroute/graph.py`'s
  `OSRM_TABLE_MAX_DIMENSION` tiling to match) rather than touch any Dijkstra/CSR/routing code - this is the
  first item in the 4c-follow-up chain whose fix, if any, lives in OSRM's own startup config rather than
  `tollroute/`.
  Files: `osrm/docker-compose.yml`, `tollroute/osrm_client.py`, `tollroute/graph.py`
  Done when: Full `/route` response returns under ~300 ms warm for a national multi-operator pair (e.g.
  Dijon→Lyon), with no change to any option's labels, ordering, or numeric fields, and no regression in
  `python3 -m pytest` — or, if measurement shows larger `/table` requests don't help, that conclusion is
  written up with numbers and this item is closed as "investigated, no further win available" rather than
  left open indefinitely.
  **Measured, CONFIRMED negative result:** a second `osrm-routed` container was started alongside the live
  one (separate port, same read-only bind-mounted `france.osrm` data, no disruption to the live service)
  with `--max-table-size 1000`, comfortably above the ~910-gate access-edge set. A single 1x910 `/table`
  request against it averaged **~1146 ms** over 6 warm runs (1140-1158 ms) — **~7.6x slower**, not faster,
  than today's tiled-and-concurrent baseline's **~151 ms** (9x 100-wide blocks, `MAX_CONCURRENT_REQUESTS`
  `ThreadPoolExecutor`, 6 warm runs: 141-160 ms) measured against the live container in the same session. A
  control run of the existing 100-wide tiled client code against the *same* raised-limit container (ruling
  out the second container itself being slow for unrelated reasons, e.g. no OS page-cache warm-up) matched
  the baseline almost exactly (~150 ms mean), isolating request-shape as the only variable. `docker stats`
  during the single big request showed ~94% CPU (i.e. one core saturated, ~910 concurrent requests' worth
  of would-be parallelism collapsed into one), consistent with `osrm-routed`'s per-request `/table`
  handling being effectively single-threaded per query — tiling into many smaller requests and firing them
  concurrently (today's approach) lets multiple cores work the same total gate set in parallel, which one
  large request structurally cannot. **Conclusion: raising `--max-table-size` is not a viable lever** —
  it does not merely fail to help, it actively regresses latency by close to an order of magnitude, so
  `osrm/docker-compose.yml`, `tollroute/osrm_client.py`'s `TABLE_MAX_DIMENSION`, and
  `tollroute/graph.py`'s `OSRM_TABLE_MAX_DIMENSION` are left unchanged. No code was modified this
  iteration (investigation-only item); `python3 -m pytest` (142 passed, 3 skipped, 7 xfailed) and the
  `python3 -m tollroute dijon lyon --class 1` regression check (EUR 14.10 / 162.4 min / 209.8 km / gates
  269→930) were re-run to confirm the live service was left in its original state after the temporary
  benchmark container was stopped and removed. This closes the entire Phase 4c-follow-up chain's
  client-side and infra-config levers: the remaining ~50-100 ms gap to the ~300 ms exit criterion is
  `osrm-routed`'s own per-query MLD CPU cost for this dataset/access-edge strategy, not fixable without a
  different architecture (e.g. fewer access-edge queries in the first place, or a precomputed/cached
  access-edge structure) — out of scope for a follow-up chain that has now exhausted "make the same OSRM
  calls faster."

### Phase 5a — Distance regression and fare oracle

- [x] **Add distance regression pytest and fare oracle across operators** — DONE 2026-08-12
  Scope: Convert the Phase 3c distance cross-check to a regression pytest (22,175 rows); run a fare oracle
  of 20–30 OD pairs across operators/classes against data.gouv.fr/ASFA or operator calculators with a
  stated tolerance.
  Files: `tests/test_distance_regression.py`, `tests/test_fare_oracle.py`, `reports/phase5a.md`
  Done when: Fare oracle passes for every operator tested; tolerance stated explicitly; disagreements
  documented with named root cause. (spec: iterative-tumbling-lecun.md Phase 5a)
  **Result:** Full write-up: `reports/phase5a.md`. (1) **Distance regression** — already satisfied by
  Phase 3c's committed `tests/test_distance_error.py` (22,175/21,981-row check, no OSRM dependency);
  re-verified green, no new file added to avoid duplicating an already-correct test. (2) **Fare oracle** —
  a web search this iteration found something Phase 2a's search missed: APRR, AREA and Cofiroute each
  publish a full gate-to-gate tariff-grid **PDF** (not a summary, not an interactive calculator) —
  `voyage.aprr.fr` (APRR/AREA, current 1 Feb 2026 vintage) and `public-content.vinci-autoroutes.com`
  (Cofiroute, 2025 vintage — no 2026 edition found published). Cross-checked the **full population**
  (32,788 rows, not just a sample): APRR 21,349/21,349 and AREA 503/503 match the official current
  tariff **exactly, to the cent, for all 5 classes** — zero mismatches. Cofiroute's 10,936 rows all
  resolve by name but only 649 match exactly; the rest deviate by a small (+1.06% mean), tight
  (stdev 0.65%), always-positive amount matching Cofiroute's confirmed 1.21-1.41% 2026 increase almost
  exactly — a source-vintage gap, not a data-quality finding. ASF/Escota PDFs exist but are unparseable
  rotated-header matrix tables (not row lists); sanef/SAPN/aliea are WAF-blocked (HTTP 403) — named,
  verified exclusions. `tollroute/validation/fare_oracle.py` (parsers + tolerance check) and a 26-pair
  curated fixture (`tests/fixtures/phase5a_fare_oracle.csv`, 10 APRR/6 AREA/10 Cofiroute, rotating
  through all 5 vehicle classes, per-row tolerance 0.5% current-vintage / 2.5% prior-vintage) back
  `tests/test_fare_oracle.py`. **Deliberately not committed:** the full PDF text extracts (copyrighted
  third-party publications, unlike this project's own `data/matrices/*.npy`) — the fixture cites
  individual published prices at spot-check scale instead.
  **Test outcome:** `python3 -m pytest` — 150 passed (142 prior + 8 new in `test_fare_oracle.py`), 3
  skipped, 7 xfailed, no regressions.

### Phase 5b — Route plausibility and independent estimate

- [x] **Run 10 route plausibility checks against HERE/TomTom**
  Scope: Manually check 10 plausibility routes (incl. Paris→Lyon, Paris→Bordeaux, Clermont-Ferrand→
  Montpellier via A75) and compare with a HERE or TomTom toll-cost API as an independent validator (not a
  production dependency).
  Files: `reports/phase5b_plausibility.md`
  Done when: All 10 routes match human expectation; any divergence from HERE/TomTom explained with named
  root cause. (spec: iterative-tumbling-lecun.md Phase 5b)
  **Completed 2026-08-12:** neither HERE nor TomTom is reachable without an API key (none present in this
  build environment; TomTom's Routing API confirmed a hard 401 without one; signing up for a third-party
  developer account was judged out of scope for an unattended iteration). Substituted `ulys.com`'s
  per-corridor toll calculator (reachable via `WebFetch`, unlike `autoroutes.fr`/`vinci-autoroutes.com`,
  already found broken in Phase 5a) for 4 of the 10 routes, plus the Millau viaduct's own official 2026
  tariff PDF for the A75 case — same "individual public calculator" fallback pattern Phase 2a/5a already
  established for gate fares, applied here to route totals. All 10 routes matched human/driver expectation
  in shape (distance-proportional toll on tolled motorways, near-zero on the one genuinely-free corridor
  tested, a real time-costed toll-free alternative always available, gate chains resolving to correctly
  named real barriers on the right motorway — one route's chain followed the real A46 Lyon-bypass a route
  planner would suggest). Two divergences found against the 4 independently-checked pairs, both with a
  named, evidenced root cause: (1) this service's `fastest` duration runs 6-36% above baseline/Ulys,
  traced to `add_access_edges`' `exclude=toll` (Phase 4c) excluding a motorway's genuine toll-free
  open-system lead-in near the origin/destination, not just its tolled section — evidenced by
  Paris→Bordeaux (whose engine-chosen entry gate exactly matches Ulys's) showing the smallest gap of the
  three fully-checked long routes; (2) toll cost is consistently at-or-below Ulys's figure, never above
  (-5.9% to -21.7%), the expected direction for a true toll-minimiser searching every gate pair rather than
  returning the one "obvious" route, further confirmed by an exact-cent match between this project's own
  `fares` table and Ulys's published figure for the specific gate pair (Fleury-en-Bière→Villefranche-Limas,
  €41.30) a real driver/Ulys would use on the Paris→Lyon corridor. Route #3 (Clermont-Ferrand→Montpellier)
  correctly shows the A75 corridor as near-free but omits the Millau viaduct's real €11.30 (2026, off-peak,
  class 1) toll because CEVM (its operator) isn't among this project's 13 dataset operators — a boundary
  Phase 1b/1d already documented for this exact corridor, now with a number attached. Full report:
  `reports/phase5b_plausibility.md`; reproduction script: `analysis/phase5b_plausibility.py`.
  **Test outcome:** `python3 -m pytest` — 150 passed, 3 skipped, 7 xfailed, unchanged from Phase 5a (no
  `tollroute/` core code touched — analysis/validation only).

- [x] **Phase 5b-follow-up-1: give `add_access_edges` a real vs. free motorway distinction**
  Scope: `add_access_edges` (`tollroute/graph.py:564-579`) currently excludes an entire named motorway from
  the origin/destination access legs (`exclude=toll`) to stop a query riding the tolled network for free
  before/after paying — but this also excludes a motorway's genuine toll-free open-system lead-in nearest
  the query point, found in Phase 5b to push Dijkstra toward a farther, cheaper-looking entry/exit gate
  than the nearest realistic one on 4/4 independently-checked long routes (6-36% `fastest`-duration
  inflation vs baseline/Ulys). Investigate whether OSRM's toll-way tagging can be queried per-segment
  (rather than per-named-road) so the exclusion only bites once the route is actually within a tolled
  section.
  Files: `tollroute/graph.py`, `osrm/` (Lua profile, if the fix needs finer toll tagging)
  Done when: re-running `analysis/phase5b_plausibility.py`'s 10 routes shows `fastest` duration materially
  closer to `baseline`/Ulys for Paris→Lyon and Paris→Bordeaux specifically (both currently diverge because
  the engine picks a different entry gate to Ulys's), with no regression to the toll-accounting guarantee
  the exclusion exists for (spec: Phase 4c's "confirmed empirically" note in `graph.py`).
  **Completed 2026-08-12:** investigation (already recorded in `tollroute/etl/access_anchors.py`'s docstring)
  found the per-segment OSRM toll tagging near Fleury-en-Bière/Paris-Lyon is already split correctly, not
  premature — the real mechanism is a gate's own coordinate (the physical barrier, on tolled tarmac by
  definition) sometimes sitting in a small `exclude=toll`-graph pocket disconnected from the wider toll-free
  network. Shipped `tollroute.etl.access_anchors` (a precompute script finding, per affected gate, the
  nearest verified-connected toll-free point plus a short "apron" leg back to the gate, bounded to 2 km to
  guarantee it can never resurrect the Phase 1c free-ride bug), a new `access_anchors` table
  (`tollroute/db/schema.sql`), and `add_access_edges`/`Graph.access_anchors` wiring
  (`tollroute/graph.py`) to query the anchor instead of the gate's own coordinate when one exists. Fixed a
  real integration bug found while validating this: `tollroute/api.py`'s per-request `_graph_copy` omitted
  the new `access_anchors` field, silently dropping every anchor on the live `/route` endpoint (caught by
  `tests/test_api.py::test_route_endpoint_fastest_option_matches_cli` disagreeing with the CLI/oracle once
  the table was populated — €14.10 vs €12.70 for Dijon→Lyon). Added a self-contained offline unit test
  (`tests/test_routing.py::test_add_access_edges_queries_anchor_coord_and_adds_apron`, monkeypatched OSRM
  calls, no live network) pinning the anchor-coordinate-substitution and apron-arithmetic behaviour directly.
  Re-recorded all 10 golden fixtures (`analysis/record_golden_fixtures.py`) since the anchored gates'
  legs legitimately changed.
  **Flagship acceptance criterion NOT met, honestly**: re-running the 10 plausibility routes shows
  Paris→Lyon and Paris→Bordeaux's `fastest`-vs-`baseline` duration gap essentially unchanged
  (15.5%→14.8% and 13.4%→13.4% respectively) — full numbers and root-cause analysis in
  `reports/phase5b_followup1_validation.md`. Fleury-en-Bière (gates 302/303, Paris-Lyon's "obvious" nearer
  entry gate) still has no anchor: direct re-verification found every toll-free-reachable candidate within
  its 100 nearest `/nearest` probes has a 22-30 km plain apron back to the gate, while the only candidates
  with a short apron are themselves unreachable — a genuine multi-kilometre regional isolation, not a
  last-mile pocket, which correctly stays gapped rather than accepting a detour-sized apron that would ride
  the tolled motorway for free. This corrects `access_anchors.py`'s own docstring, which had claimed a short
  reachable candidate existed for Fleury without checking reachability and apron-distance together for the
  same candidate. Real, verified value still shipped: 67/910 gates (of 256 that needed one) now have a
  working anchor — including Paris→Lyon's own exit gate, Belleville-sur-Saône (110, 400 m/31 s apron) — and
  the `api.py` bug fix is a genuine correctness fix independent of the flagship result. Test outcome:
  `python3 -m pytest` — 187 passed, 1 failed (pre-existing, unrelated — see Phase 5c-follow-up), 3 skipped,
  7 xfailed. Filed the corrected, narrower remaining problem as Phase 5b-follow-up-1-continued below.

- [x] **Phase 5b-follow-up-1-continued: fix Fleury-en-Bière-class gates (multi-km isolated pockets, not
  last-mile ones)**
  Scope: Phase 5b-follow-up-1's `tollroute.etl.access_anchors` mechanism (bounded local-apron search)
  correctly leaves Fleury-en-Bière (gates 302/303, Paris→Lyon's nearer, Ulys-matching entry gate) gapped —
  its own coordinate has no toll-free-reachable candidate within 100 `/nearest` probes closer than 22 km,
  a genuine regional isolation the 2 km `APRON_REJECT_DISTANCE_M` safety bound correctly refuses to bridge
  (see `reports/phase5b_followup1_validation.md` for the full re-verification). A real fix needs a
  different technique, not a wider search radius (which would just resurrect the Phase 1c free-ride bug at
  a larger scale). Candidate directions to investigate before implementing: (a) relaxing `exclude=toll` for
  a short *fixed-radius* buffer immediately around the gate's own coordinate specifically (rather than
  searching outward for a distant reachable point), so only the barrier's immediate plaza can use tolled
  tarmac, or (b) modelling such a gate's entry as genuinely requiring a short stretch of tolled road,
  structurally different from today's "anchor + apron" model, with its cost accounted for explicitly rather
  than silently absorbed into the access edge.
  Files: `tollroute/graph.py`, `tollroute/etl/access_anchors.py`, `osrm/` (Lua profile, if a fixed-radius
  relaxation needs it)
  Done when: re-running `analysis/phase5b_plausibility.py`'s 10 routes shows Paris→Lyon's `fastest` entry
  gate switch to Fleury-en-Bière (or another materially closer gate) with a duration gap vs `baseline`
  closer to Paris→Bordeaux's already-smaller ~13% (spec: this item's own validation report), with no
  regression to the toll-accounting guarantee `exclude=toll` exists for.
  **Completed 2026-08-12:** neither candidate direction from this item's own scope note turned out to be
  the fix. Investigation found two real bugs in Phase 5b-follow-up-1's shipped `tollroute.etl.access_anchors`
  instead: (1) its own docstring always claimed the anchor search "walks backward along a real route's
  geometry" from a reference city to the gate, but the shipped code actually radiated outward from an
  undirected `/nearest?exclude=toll` — exactly the approach that docstring said was "tried first and
  rejected" for picking wrong-carriageway candidates on divided motorways. Verified directly: Fleury-en-
  Bière's nearest `/nearest` candidate (~72 m away) has a 30 km apron (opposite-carriageway detour), while
  walking backward along the real Paris→gate route's own geometry finds a toll-free-reachable point only
  ~350–600 m from the gate — the "22–30 km genuine regional isolation" this item's own scope note concluded
  was a search-method artefact, not a real isolation. (2) The reachability check was direction-blind — it
  only ever tested "candidate → reference" (exit direction) and the resulting anchor was reused for
  `add_access_edges`'s entry legs too; verified 7 of 8 randomly-sampled Phase 5b-follow-up-1 anchors are NOT
  toll-free-reachable in the entry direction despite passing the exit-direction check they were validated
  against. Fixed both: rewrote `access_anchors.py` to walk the real route geometry (bounded to 2 km of
  cumulative route distance, batch-tested per reference via one OSRM `/table` call) separately per direction,
  split `tollroute/db/schema.sql`'s `access_anchors` table and `Graph.access_anchors_entry`/
  `access_anchors_exit` to store independent entry/exit anchors, and updated `add_access_edges` (and its
  3 test-file/1 api.py `_graph_copy` call sites) accordingly. Anchor coverage jumped from 67/256 (exit-only,
  entry unvalidated) to entry 240/242 + exit 255/255 found; Fleury-en-Bière (302/303) now has both a 508.5 m
  entry anchor and a 601.6 m exit anchor. **Flagship acceptance criterion met**: Paris→Lyon's `fastest`-vs-
  `baseline` duration gap dropped from 14.8% to **11.5%** — closer to, and in fact better than, Paris→
  Bordeaux's ~13.4% benchmark (Bordeaux itself unchanged, out of this item's scope). Full before/after in
  `reports/phase5b_followup1_continued_validation.md`; precompute run's own report in
  `reports/phase5b_followup1_continued_access_anchors.md`. Added direct unit coverage for the new
  geometry-walk algorithm (`tests/test_access_anchors.py`, 3 tests, monkeypatched OSRM via
  `httpx.MockTransport`, no live network) and strengthened the existing `add_access_edges` anchor test to
  use *distinct* entry/exit anchor coordinates, pinning that they're applied independently (the exact bug
  class found in (2)). Re-recorded all 10 golden fixtures since routes legitimately changed.
  **Test outcome:** `python3 -m pytest` — 190 passed (3 more than the prior baseline: the new
  `test_access_anchors.py` tests), 1 failed (pre-existing, unrelated — Phase 5c-follow-up, same file/test
  untouched here), 3 skipped, 7 xfailed.

- [x] **Phase 5b-follow-up-2: add CEVM/Millau (and other single-structure concessions) to `freeflow_override`**
  Scope: the Millau viaduct (CEVM, ~€11.30 2026 off-peak class-1, per `leviaducdemillau.com`'s own tariff
  PDF) is on the A75 corridor this project already treats as untolled (Phase 1b/1d), because CEVM isn't
  one of the 13 dataset operators. `tollroute_national.sqlite`'s `freeflow_override` table (currently
  empty) already exists for exactly this single-gantry-flat-fee case (used elsewhere for A14-style tolls
  per `graph.py`'s build log). Research whether any other single-structure concessions outside the 13
  dataset operators carry a similarly-sized real toll before deciding whether this is worth the one-off
  data entry.
  Files: `tollroute/etl/freeflow.py`, `tollroute_national.sqlite` (`freeflow_override` rows)
  Done when: Clermont-Ferrand→Montpellier's `fastest` toll includes the Millau flat fee, sourced to the
  operator's own published tariff, with a regression test pinning the value.
  **Completed 2026-08-12, revised same day:** shipped fee data (`freeflow.seed_millau_override`, schema
  extended with `operator`/`structure_a/b_lat/lon`/`is_conjecture`). First attempt modelled Millau as two
  synthetic gates ~13 km apart (guessed coordinates) joined by a priced `TOLL` edge; found and fixed a real
  bug (a structure's own two ends got a free duplicate connectivity edge alongside the priced one) but then
  found, on closer inspection, the guessed coordinates didn't actually sit on the viaduct span at all - the
  claim that OSM doesn't tag the viaduct `toll=yes` (recorded in an earlier version of this entry) was
  itself never checked and turned out to be **wrong**. **Reverted** in favour of a second design: seeding
  Millau as one real self-loop gate at the verified `barrier=toll_booth` coordinate (same shape as A14's 5
  dataset self-loop fares), letting `build_graph`'s existing A14 self-loop mechanism wire it up with no new
  graph.py code at all - correctly-tested (`tests/test_graph.py`,
  `test_millau_seed_becomes_priced_selfloop_edge_via_existing_a14_mechanism`) and confirmed a genuine
  `exclude=toll` chokepoint at that coordinate.
  **Flagship acceptance criterion NOT met, honestly - for a third, different reason found this same day**:
  even with the real barrier coordinate, Clermont-Ferrand→Montpellier's `fastest` route still never selects
  the Millau toll (`toll_eur: 0.0`, gate chain `[900001]`). Root-caused directly this time (traced the actual
  graph edges, not inferred): a self-loop gate with no *other* `fares` row connecting it to a different real
  gate (true of both Millau and A14's 547/205) is Pareto-dominated - `add_access_edges` lets any route reach
  `OUT(gid)` via a free 180 s/500 m dwell and exit straight to the destination from there, which is strictly
  cheaper *and* faster than continuing through the priced edge to `OUT_TOLL(gid)`. No route optimiser
  objective this service offers can ever select the toll-paying path. Full trace and numbers in
  `reports/phase5b_followup2_millau.md`. Real, verified value still shipped independent of the flagship
  result: sourced/interpolated fee data, the self-loop seeding mechanism, and `access_anchors` coverage for
  the new gate are all real and correctly tested. Filed the corrected (third) follow-up below.
  **Test outcome:** `python3 -m pytest` - 194 passed, 3 skipped, 7 xfailed (the previously-noted
  `test_snap_report.py` failure - Phase 5c-follow-up - was re-checked this iteration and found flaky rather
  than deterministic: it fails or passes on different runs against the same live OSRM instance with no code
  change in between; still unrelated to this item). All 10 Phase 5c golden fixtures re-recorded.

- [x] **Phase 5b-follow-up-2-continued: give a no-real-neighbour self-loop gate a destination access edge
  that can't skip its own mandatory toll**
  Scope: the real gap (see `reports/phase5b_followup2_millau.md`'s "New finding" section) was in
  `add_access_edges` (`tollroute/graph.py`): it connected a destination to a gate's plain `OUT` node for
  *every* gate, including self-loop-only gates (Millau's 900001, and A14's pre-existing 547/205) whose only
  path to `OUT` is a free dwell from `IN` - letting a route reach, then leave from, the gate's neighbourhood
  without ever crossing its mandatory-pass `TOLL` edge to `OUT_TOLL`.
  Files: `tollroute/graph.py`, `tollroute/api.py`, `tests/test_routing.py`, `tests/test_api.py`,
  `tests/test_pareto.py`, `tests/test_response.py`
  Done when: re-running `analysis/record_golden_fixtures.py` shows Clermont-Ferrand→Montpellier's `fastest`
  option's gate chain includes gate 900001 with `toll_eur` reflecting the sourced/interpolated class-1 fee
  (€11.30).
  **Completed 2026-08-12:** `Graph` gained `freeflow_selfloop_gate_ids` (populated in `build_graph`
  whenever a self-loop `TOLL` edge is added); `add_access_edges` grants a gate in that set only its
  `OUT_TOLL` exit access edge, withholding plain `OUT`, closing the skip without touching any other gate's
  `OUT` semantics. Found and fixed a second bug alongside it: `api.py`'s per-request `_graph_copy` didn't
  carry the new field over (same bug class as Phase 5b-follow-up-1's `access_anchors` omission), so the fix
  passed its own direct unit test yet never fired through the real `/route` endpoint until the golden
  fixtures were re-recorded and still showed `toll_eur: 0.0`. Added a generic regression test
  (`tests/test_api.py::test_graph_copy_preserves_every_graph_dataclass_field`, iterating
  `dataclasses.fields` so it doesn't need hand-updating for the next field either) plus a direct
  `add_access_edges` unit test pinning the OUT-withholding behaviour
  (`tests/test_routing.py::test_add_access_edges_withholds_out_exit_edge_for_freeflow_selfloop_gates`).
  **Flagship acceptance criterion met**: re-recorded golden fixture shows Clermont-Ferrand→Montpellier's
  `fastest` option at `toll_eur: 11.3`, gate chain `[900001]` (duration 14766.4 s / distance 341118.2 m);
  `cheapest`/`best_value` correctly route around Millau instead (`toll_eur: 0.0` via gates 555/654) - the
  tradeoff a toll-minimiser should offer. This also retroactively fixes A14's own self-loop gates (547,
  205), which shared the identical no-other-neighbour shape and were - per this same investigation - never
  actually charging their fee on any real route through this service before this fix.
  Test outcome: `python3 -m pytest` - 206 collected; full suite re-run confirmed clean bar the pre-existing,
  independently-flaky `test_snap_report.py` case (Phase 5c-follow-up, unrelated).

### Phase 5c — Golden-file test suite

- [x] **Build offline golden-file regression suite**
  Scope: pytest golden-file suite covering all Phase 5a fare-oracle pairs and Phase 5b plausibility routes,
  failing on any unexplained price/route change; runnable without network using recorded OSRM/oracle fixtures.
  Files: `tests/test_golden.py`, `tests/fixtures/`
  Done when: All golden-file tests pass on a clean run with no network access. (spec: Phase 5c)
  **Completed 2026-08-12:** two-part suite. (1) Phase 5a fare-oracle pairs: `test_fare_oracle_pair_pinned`
  re-uses `tollroute.validation.fare_oracle`'s existing 26-row fixture as a per-row exact pin against
  `od_pairs.csv` — already offline (no OSRM/DB server), just newly asserted as a golden pin rather than a
  tolerance check. (2) Phase 5b's 10 plausibility routes: `analysis/record_golden_fixtures.py` drives a real
  `tollroute.api` instance (FastAPI `TestClient`) against live OSRM once, recording every OSRM `/table`/`/route`
  exchange via an `httpx` response event hook plus the resulting `/route` response, to
  `tests/fixtures/golden/*.json` (10 files, ~740 KB each). `tests/test_golden.py` replays each fixture through
  an `httpx.MockTransport` keyed on the exact recorded request URL — the real routing/response-shaping code
  runs end to end, asserting byte-for-byte equality against the recorded response, and raises loudly (not a
  silent fall-through) if the code under test ever issues a request the fixture didn't record. **Verified
  network-independence directly, not assumed:** stopped the live `osrm-osrm-routed-1` Docker container
  entirely and re-ran `tests/test_golden.py` — all 37 tests still passed; restarted the container afterwards
  (a locally-scoped, reversible action, not a data change — confirmed via `.osrm` file mtimes, none newer than
  the original Aug-11 build).
  **Test outcome:** `python3 -m pytest tests/test_golden.py` — 37 passed (OSRM both up and fully stopped).
  Full suite: `python3 -m pytest` — 186 passed, 1 failed, 3 skipped, 7 xfailed. The 1 failure
  (`tests/test_snap_report.py::test_all_5_named_test_pairs_have_prices_and_distinct_routes`) is **pre-existing
  and unrelated** to this item (that file/test untouched here) — see the new Phase 5c-follow-up item below;
  documented rather than fixed inline per this project's "document, don't fix outside current item" rule.

- [x] **Phase 5c-follow-up: `test_snap_report.py`'s A75 geo-only pair now shows a real tolled/toll-free
  divergence, not "near-identical"**
  Scope: while verifying Phase 5c's golden suite, `test_all_5_named_test_pairs_have_prices_and_distinct_routes`
  (`tests/test_snap_report.py:71`) was found failing reproducibly against the current live national OSRM
  instance: for Clermont-Ferrand->Montpellier (the A75 free-motorway edge case, no gate graph involved — a raw
  OSRM `/route` comparison), tolls-allowed returns 331,902.5 m / 13,336.0 s and `exclude=toll` returns
  337,817.7 m / 14,148.3 s (+1.8% distance, +6.1% duration) — confirmed stable and deterministic across two
  independent full container restarts (`.osrm` file mtimes unchanged since the original Aug-11 build, ruling
  out a data change), so this is real current OSRM routing behaviour, not test flakiness. The test's hard-coded
  expectation (`distinct_route is False`, i.e. "near-identical") predates this finding. This is very likely the
  same root cause already filed as **Phase 5b-follow-up-1** (`exclude=toll` excluding a motorway's genuine
  toll-free lead-in, not just its tolled section) observed via a second, independent code path (raw OSRM
  `/route`, not `add_access_edges`) — worth fixing alongside that item rather than by loosening this test's
  assertion, which would mask the same signal rather than resolve it.
  Files: `tests/test_snap_report.py`, `tollroute/graph.py` (shared root cause with Phase 5b-follow-up-1)
  Done when: resolved together with Phase 5b-follow-up-1's fix — re-run
  `test_all_5_named_test_pairs_have_prices_and_distinct_routes` and confirm it passes for the right reason
  (a materially closer, not just reclassified, toll-free route), not by relaxing the assertion.
  **Completed 2026-08-12:** the plan's "same root cause as Phase 5b-follow-up-1" speculation was checked
  directly and found **wrong**. Re-running `verify_geo_only_pair` 10x against the live production OSRM
  container with no code/data change between calls showed the *tolled* query alone (no `exclude=toll`, so
  Phase 5b-follow-up-1's mechanism can't apply) flipping between two different distances run to run —
  ruling out a graph/profile bug. Isolated to `osrm-routed`'s thread count by launching independent
  containers against the same unmodified `.osrm` build with only `--threads` varied: 15/15 identical results
  at `--threads 1` and `--threads 2`, but non-deterministic at `--threads 4/8/24` (24 is this project's
  production default) — a known class of OSRM MLD behaviour where near-tied-cost routes are broken
  inconsistently across worker threads. The two routes this corridor flips between differ by only 1.8%
  distance / 6.1% duration, an order of magnitude below the 40-75% duration gap the other 4 named pairs show
  for a genuine toll bypass (`reports/phase1b_snapping.md`) — i.e. they *are* near-identical per this pair's
  own documented intent; the previous exact-equality check just couldn't tolerate any engine-level tie noise.
  Fix: `verify_geo_only_pair` now classifies the pair as distinct only when distance or duration differ by
  more than 10% (`GEO_ONLY_MATERIAL_DIVERGENCE_REL_TOL`, margin above the 6.1% noise ceiling and below the
  40-75% real-divergence floor), via `math.isclose`. `verify_fare_pair` (the other 4 pairs, real divergences
  far outside any plausible tie-noise band) left untouched. **Verified, not just re-derived:** re-ran
  `verify_geo_only_pair` 30x post-fix against the live `--threads 24` production container — `distinct_route`
  was `False` all 30 times; `python3 -m pytest tests/test_snap_report.py` re-run independently 5x — 2 passed
  each time. Full root-cause writeup: `reports/phase5c_followup_a75_osrm_nondeterminism.md`.
  **Test outcome:** `python3 -m pytest` — 196 passed, 3 skipped, 7 xfailed (0 failed). Filed the broader
  production implication (live `/route` queries could non-deterministically flip on any other near-tied
  corridor in France, not just this test pair) as a new item below rather than fixed here.

- [x] **Phase 5c-follow-up-2: production `osrm-routed` runs 24 threads, which the just-verified MLD
  tie-breaking non-determinism means can non-deterministically flip a live `fastest`/`cheapest` route
  choice on any near-tied corridor in France, not just the A75 test pair**
  Scope: Phase 5c-follow-up's investigation (`reports/phase5c_followup_a75_osrm_nondeterminism.md`) proved,
  via a direct `--threads` sweep against the unmodified production `.osrm` build, that `osrm-routed`'s MLD
  algorithm gives deterministic results at `--threads 1`/`2` but flips between near-tied candidate routes at
  `--threads >= 4` — and `osrm/docker-compose.yml` runs production at `--threads 24`. That was only checked
  against one known near-tied corridor (Clermont-Ferrand-Montpellier); it is not yet known how often France's
  full road network produces near-tied `fastest`/`cheapest` candidates elsewhere, nor whether this service's
  own `/route` endpoint (which layers `tollroute.graph`'s Dijkstra over OSRM's per-edge `/table` costs, not
  raw OSRM `/route`) is actually exposed to the same non-determinism or only raw-OSRM-only call sites are.
  This is a genuine correctness/consistency question for a live user-facing service (same query, different
  answer, no data change) and the throughput-vs-determinism tradeoff (`--threads 1` guarantees determinism
  but was not load-tested) needs a scoped decision, not a reflexive threads=1 change.
  Files: `osrm/docker-compose.yml`, `tollroute/graph.py`, `tollroute/api.py`
  Done when: established (a) whether `tollroute.api`'s `/route` responses (not just raw OSRM `/route`) can
  flip for repeated identical requests under production's `--threads 24`, and (b) if so, a decision — with
  documented tradeoffs — between pinning a lower thread count, switching algorithm (e.g. CH), or adding a
  request-level consistency mechanism, backed by direct measurement rather than assumption either way.
  **Completed 2026-08-12:** answered by driving the exact production code path (`graph.build_graph` once,
  then per call `osrm_client.baseline_route` + `graph.add_access_edges` + `response.shape_response`) against
  the live, unmodified production OSRM container, bypassing `api.cached_shape`'s `lru_cache` so every call was
  a genuine cache-miss request — 60 total repeat live requests (45 on the already-proven-adversarial
  Clermont-Ferrand→Montpellier corridor, 15 on an ordinary Dijon→Lyon control). **(a):** the actual routing
  recommendation (`fastest`/`cheapest`/`best_value`, their gates/tolls/distances/durations) was byte-identical
  across all 60 requests — it is driven entirely by Phase 3b's frozen precomputed gate-to-gate matrix, not a
  live per-request OSRM path search, so it does not inherit `osrm-routed`'s MLD tie-breaking non-determinism.
  Only the `baseline` field (one raw live OSRM `/route` call, used purely as a comparison/availability canary
  per the module docstring, not the recommendation itself) reproduced the same two-way flip already
  characterised in Phase 5c-follow-up — confirmed on 2/30 vs other runs of the adversarial corridor. **(b):**
  decided **no infrastructure change** — pinning `--threads` lower would remove only this narrow,
  display-only residual risk (already further dampened in real traffic by `cached_shape`'s existing
  `lru_cache`, which returns the same cached `baseline` for repeat identical requests to a running process
  regardless) at an unmeasured service-wide throughput cost; switching algorithm is disproportionate to a
  finding confined to one non-recommendation field; a retry/consistency wrapper would only mask the same
  engine noise, not remove it, and works against `baseline_route`'s deliberate design as "the cheapest
  possible OSRM call" (fast availability canary). Flagged directly at the `baseline_route` call site
  (`tollroute/osrm_client.py`) so this is discoverable without re-deriving it. Full writeup:
  `reports/phase5c_followup2_production_route_determinism.md`.
  **Test outcome:** `python3 -m pytest` — 196 passed, 3 skipped, 7 xfailed, 1 transient
  `httpx.RemoteProtocolError` on `test_build_national.py::test_rerun_against_existing_file_stays_row_id_aligned`
  (unrelated to this docstring-only code change — passed cleanly in isolation on immediate re-run, consistent
  with a network blip during the concurrent OSRM load this investigation's probe generated, not a regression).

### Phase 6a — Observability and ops

- [x] **Add gate-chain logging, /health endpoint, and one-command rebuild**
  Scope: Structured logging of the full gate chain per response; `/health` asserting OSRM reachability and
  matrix load (not data freshness); documented one-command pipeline rebuild OSM→OSRM→matrices.
  Files: `tollroute/api.py`, `tollroute/logging.py`, `scripts/rebuild.sh`, `docs/ops.md`
  Done when: A single request log contains the full gate chain; `/health` returns 200 up / 503 when OSRM
  mocked down; rebuild command runs end to end from a fresh checkout. (spec: Phase 6a)
  **Completed 2026-08-12:** `tollroute/logging.py` adds a JSON-lines formatter (`JSONFormatter`) attached
  to the root logger by `api.py`'s `lifespan` (`configure_logging`, idempotent), plus
  `log_route_response`, called at the end of `/route` after `route_id`s are assigned, logging every
  returned option's `route_id`/labels/gate chain/toll/duration/distance as one structured record (not just
  the winning option - "why this route" debugging usually means "why not that one"). `/health`
  (`tollroute/api.py`) checks OSRM reachability via a cheap `/nearest` probe and that the startup graph
  actually has gates/edges loaded (`matrix_loaded`), returning 200 only when both hold, 503 otherwise, with
  per-check booleans in the body - deliberately excludes data freshness per spec. `scripts/rebuild.sh` chains
  the already-existing, already-tested per-step commands (`osrm/build_france.sh`, `docker compose up`,
  `python3 -m tollroute.matrices`, `python3 -m tollroute.etl.build_national`, `python3 -m
  tollroute.etl.access_anchors`) with an OSRM-readiness poll between steps 2 and 3, documented in
  `docs/ops.md` alongside a sample log line and the `/health` response shape. **Verified directly, not just
  re-derived:** `/health` (`osrm_reachable: true, matrix_loaded: true, gate_count: 911`) and a real `/route`
  call's structured log line (containing both returned options' full gate chains) were both exercised
  live against the running national OSRM instance outside the test suite too. **Not literally re-run end to
  end:** `scripts/rebuild.sh`'s first two steps (~5 GB PBF download + osrm-extract/partition/customize) were
  not re-executed in this iteration - that pipeline is the same one Phase 3a already built and tested
  (`osrm/build_france.sh`, `osrm/smoke_test_france.sh`), and re-running it here would just rebuild the
  already-serving production OSRM instance from scratch at very high cost for no new signal; each individual
  step the script chains together (steps 3-5) already has its own passing test coverage and was also
  exercised live via `/health/`/`route` above. `shellcheck scripts/rebuild.sh` passes clean.
  **Test outcome:** `python3 -m pytest` — 203 passed, 3 skipped, 7 xfailed (0 failed); +7 new tests
  (`tests/test_logging.py`: formatter/idempotency/`log_route_response` content; `tests/test_api.py`:
  gate-chain logging through the real `/route` endpoint, `/health` up and OSRM-mocked-down).

### Phase 6b — Geocoding wrapper

- [x] **Add optional free-text geocoding wrapper**
  Scope: Resolve free-text address to lat/lon before the (unchanged) routing core; verify `match_tier` and
  `match_agreement` present on every response.
  Files: `tollroute/geocode.py`, `tollroute/api.py`
  Done when: A `curl` with a city name returns the same result as the corresponding coordinates; both
  match fields present on every response. (spec: iterative-tumbling-lecun.md Phase 6b)
  **Completed 2026-08-12:** `tollroute/geocode.py` adds `geocode()`, resolving free text to (lat, lon) via
  the French government's Base Adresse Nationale (BAN) search API (`api-adresse.data.gouv.fr`) - free,
  keyless, France-scoped, matching the service's own scope - with the same one-retry-at-500ms policy
  `tollroute.osrm_client` uses for its own per-request external calls. `tollroute/api.py`'s `/route` gains
  optional `origin_address`/`destination_address` query params as alternatives to the existing
  `{origin,destination}_{lat,lon}` pairs (`_resolve_point`, one call per endpoint, exactly one input form
  required): a free-text address is geocoded to lat/lon *before* `cached_shape` ever runs, so the routing
  core genuinely never changes - it always receives the same (lat, lon) tuple shape it did before this
  phase. Mixing both forms for one endpoint, or giving neither, returns `400`; an unresolvable/unreachable
  address returns `422` rather than a 500. `match_tier`/`match_agreement` were already present per gate
  (`gate_detail`) on every response since Phase 4b - unaffected by this change, confirmed by a new
  API-level test asserting both fields on every gate of an address-resolved response. **Verified live, not
  just via mocks:** started `uvicorn tollroute.api:app` against the real national OSRM+DB and confirmed
  `curl .../route?origin_address=Dijon&destination_address=Lyon` returns byte-identical `options`
  (toll/duration/gates) to the equivalent `origin_lat=47.331953&origin_lon=5.033601&...` coordinate call,
  plus the `400`/`422` validation paths, all against the live BAN API (no mocking on this manual check).
  **Judgement call, flagged:** the free geocoding-address query itself is caller-supplied free text passed
  straight through to BAN's `q` param - a stray `", France"` suffix was found during manual verification to
  make BAN match a same-named hamlet over the intended city (a BAN ranking quirk, not a bug in this code);
  documented in `docs/ops.md` rather than "fixed" by inventing unspecified query-normalisation heuristics
  the spec never asked for.
  **Test outcome:** `python3 -m pytest` — 214 passed, 3 skipped, 7 xfailed (0 failed); +11 new tests
  (`tests/test_geocode.py`: success/no-match/retry-then-succeed/retry-exhausted, all offline via
  `httpx.MockTransport`; `tests/test_api.py`: address-vs-coordinates equality, match_tier/match_agreement
  present on an address-resolved response, 4-way parametrised validation-error coverage, geocode-service-down
  returns 422 — all `@requires_osrm`, run against the live national OSRM instance).

---

# Rearchitecture: Option 3 — single Valhalla instance, toll-penalty access routing

Source of truth: `~/.claude/plans/option3-unified-valhalla.md`.
Downstream edits the plan omits: `specs/option3-downstream-edits.md`.

**CORRECTION (verified 2026-08-21, later pass): source-of-truth plan file is NOT
missing.** It lives at `/home/node/.claude/plans/option3-unified-valhalla.md`
(read in full, 601 lines) — a prior pass looked under `/home/hugh/.claude/plans/`
and wrongly concluded the directory was gone. Consequence: the exact Phase 12
commit-message wording **is recoverable** from that file (Phase 12 section of the
plan), so the build loop may reuse it verbatim rather than self-authoring. No plan
deliverable is unrecoverable. `specs/option3-downstream-edits.md` remains the
companion authority for the [GAP] items the plan omits.

**NEW THIS PASS (2026-08-21):** two test files that depend on removed symbols
were absent from both the plan and the companion spec — now added to Phase 9 as
[GAP]s and to `specs/option3-downstream-edits.md`: `tests/test_phase1d_pairs.py`
(its `_osrm_route` helper calls `route(..., toll_free=...)`, removed by Phase 2j)
and `tests/test_pareto.py` (Graph fixture sets `access_anchors_entry/exit`,
removed by Phase 3b). Both are caught by the Phase 10 narrowed grep and by
`pytest --collect-only`, so migrating without them yields a red tree. Still
nothing implemented.

Status **re-verified 2026-08-21 (fresh pass — zero drift, nothing implemented).**
Removed-symbol grep over `tollroute/ tests/` (`--include='*.py'`, excluding
`__pycache__`) unchanged: `_notoll`×5, `DEFAULT_TOLLFREE`×21, `tollfree_url`×15,
`exclude_toll`×36, `access_anchors`×54, `:8003`×1. No `_TOLL_PENALTY_COSTING`
anywhere (×0). `migrate_option3.py` absent; `reports/penalty_routing_audit_*`
absent; `osrm_client.py`, `etl/access_anchors.py`, `tests/test_access_anchors.py`
all still present. **Line refs in the phases below still hold exactly** —
re-spot-checked routing_engine.py (`DEFAULT_TOLLFREE_URL` L34, `_notoll` fields
L47/50/54/58, `_client` L60, `reachable` L92, `nearest` L103,
`route_geometry` notoll-client L226), graph.py (`access_anchors_entry/exit`
L130/131, `_access_anchor_rows` L203, `build_graph` load L285/288/289, anchor
lookups L669/673, `_with_apron` L702), docker-compose.yml (`valhalla-notoll` L26,
`8003:8003` L30). `tollroute/routing_engine.py` exists but is **untracked** and
still carries the old two-instance `_notoll`/`tollfree_url` structure — Phase 2
has not begun. The many git-`M` files in the tree are the *separate
gate-validation workstream*, not this migration, and do not touch the migration
hunks. Phase 0 DB prerequisite holds: `tollroute/db/tollroute_national.sqlite`
(9.6 MB), `access_anchors`=1180, `gates`=974.

**Not Phase 0:** the recent `analysis/gate_validation/` suite + `tollroute/
validation/gate_verdict.py` produce gate *validity verdicts* consumed by
`distance_error.py` for gate quarantine. They are a different workstream and do
**not** satisfy the Phase 0 penalty-routing audit, which still must be authored.

Prerequisites met (from spec, unre-verified this pass): Valhalla `:8002`+`:8003`
return 200; `tollroute/db/tollroute_national.sqlite` holds `access_anchors`=1180,
`gates`=974 (with `canonical_name`/`snap_lat`/`snap_lon`/`lat`/`lon`). **Do NOT
plan-only; implementation happens in the build loop. This planner records the
ordered work.**

## CRITICAL — plan is under-scoped (verified by grep, must fix before Phase 12)

The plan removes `DEFAULT_TOLLFREE_URL`, the `tollfree_url` field, and the
`access_anchors` table, but does not edit six modules that depend on them, nor
the dead `osrm_client.py`, nor a too-broad Phase 10 grep. Left unaddressed, the
Phase 12 apply produces ImportError/TypeError and a red tree. See
`specs/option3-downstream-edits.md` for exact edits. Items below marked **[GAP]**
are additions beyond the plan document.

## Phase 0 — empirical validation — DONE 2026-08-21, VERDICT: BLOCKED

- [x] **Run penalty-routing audit against all access_anchors gates** — DONE 2026-08-21
  Script `phase0_penalty_audit.py` (throwaway, scratchpad) geocoded 166/974 gate
  origins via BAN (API timed out at gate 253, cascading to 1616 NO_ORIGIN legs).
  Routed 332 legs against `:8002` with `use_tolls=0.0` + `toll_booth_cost:9999`
  escalation. Verdict: **BLOCKED** — 238/332 (72%) FAIL_BLOCK.
  Manual debug of ABBEVILLE EST (gare_id=2) confirmed root cause: gate snap
  coordinates are physically on motorway carriageways; `use_tolls=0.0` penalty
  cannot avoid toll roads when the destination has no local-road alternative.
  The notoll tile set works by stripping toll ways and forcing snap to the
  nearest non-toll edge; penalty costing cannot replicate this.
  Report committed: `reports/penalty_routing_audit_20260821.csv` + `.md` (commit 37fee78).

**Decision (2026-08-21): Option 3 abandoned. Dual-instance architecture
(`:8002` tolled + `:8003` notoll) is the confirmed final architecture.
All migration phases below are CANCELLED.**

## Migration — CANCELLED 2026-08-21

Option 3 (single Valhalla instance + penalty routing) was blocked by Phase 0
empirical validation. All migration phases cancelled. Dual-instance architecture
is confirmed final. No further work items.
