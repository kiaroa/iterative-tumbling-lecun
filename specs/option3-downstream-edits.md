# Spec: Option 3 downstream edits (omitted by the plan)

Companion to `~/.claude/plans/option3-unified-valhalla.md`. That plan removes
three symbols but only edits a subset of the modules that depend on them. This
spec enumerates the remaining edits required for the migration to leave a
green tree. Confirmed by grep on 2026-08-21.

## Removed symbols and their full dependant set

The migration deletes:
- `routing_engine.DEFAULT_TOLLFREE_URL` (Phase 2b)
- `RoutingEngine.tollfree_url` field + `_notoll` client (Phase 2d–2f)
- `RoutingEngine.reachable/nearest/route`'s `toll_free`/`exclude_toll` params
  and `one_to_many_table`/`many_to_one_table`'s `exclude_toll` param (Phase 2h–2m)
- `access_anchors` table (Phase 6) and `etl/access_anchors.py` (Phase 5)

Every module below still references at least one of these and is **not** in the
plan's edit list. Each must be edited in the same migration or `pytest
--collect-only` / import will fail.

### 1. `tollroute/matrices.py`  (plan wrongly lists this under "What NOT to change")
- L41: drop `DEFAULT_TOLLFREE_URL` from the import.
- L374, L403, L414: remove the `tollfree_url` parameter, its `--tollfree-url`
  CLI arg, and `tollfree_url=` in the `RoutingEngine(...)` construction.
- L96–140 `_anchor_coords_for_clusters()` and L154–158 `if db_path is not None`
  branch: the `access_anchors` table is dropped, so the anchor-based tollfree
  matrix path is dead. Collapse `compute_matrices` to always call
  `engine.table(coords, toll_free=True)` (which now injects penalty costing),
  and delete `_anchor_coords_for_clusters`. Remove the now-unused `db_path`
  plumbing and the `--db` "uses access_anchors" help text (L407).
- `table(..., toll_free=True)` calls (L152/157/160) themselves stay — that
  parameter is kept per plan Phase 2n/2o.

### 2. `tollroute/cli.py`
- L21: drop `DEFAULT_TOLLFREE_URL` from import.
- L108: remove `--tollfree-url` arg.
- L111: `RoutingEngine(full_url=args.full_url, tollfree_url=args.tollfree_url)`
  → `RoutingEngine(full_url=args.full_url)`.

### 3. `tollroute/validation/distance_error.py`
- L69 import, L546 `--tollfree-url`, L549 `RoutingEngine(tollfree_url=)` — same
  three-line treatment as cli.py.

### 4. `tollroute/validation/phase3c.py`
- L23 import, L287 `--tollfree-url`, L290 `RoutingEngine(tollfree_url=)` — same.

### 5. `tollroute/etl/build_national.py`
- L68 import, L297 `--tollfree-url`, L300 `RoutingEngine(tollfree_url=)` — same.
- L206–216: remove the lazy `from tollroute.etl import access_anchors` import and
  the `anchors = access_anchors.run(...)` call (the module is deleted in Phase 5).
  Remove any downstream use of `anchors` and the comment block referencing the
  emptied `access_anchors` table.

### 6. `tollroute/etl/snap_report.py`  (plan Phase 8 only covers snap_quality.py)
- L25 import: drop `DEFAULT_TOLLFREE_URL`.
- L130–133 `osrm_route(..., exclude_toll=...)`: the helper calls
  `engine.route(origin, destination, toll_free=exclude_toll)`. `route()` loses
  `toll_free` (Phase 2j). Decide: either route the toll-free comparison with
  `costing_options=_TOLL_PENALTY_COSTING`, or drop the toll-free comparison
  entirely. The report's `toll_free_distance_m`/`toll_free_duration_s` output
  keys (L207–248, L304–324) depend on this choice.
- L375/377: remove `--tollfree-url` arg and `tollfree_url=`.

### 7. `tollroute/osrm_client.py`  — DEAD CODE, contains `exclude_toll`
- Never imported anywhere (only referenced in prose docstrings). Contains
  `exclude_toll` at L125/134/163/170 which would trip the Phase 10 grep.
- Delete the file, or exclude it from the Phase 10 grep. Deleting is cleaner —
  it was superseded by `routing_engine.py`.

### 8. `tollroute/etl/freeflow.py`  — comments only
- L103/104/151 mention `access_anchors` in prose only. Trips the Phase 10 grep.
  Reword the comments to drop the stale `access_anchors` references.

## Phase 9 test under-scoping

### `tests/test_routing.py`  (plan only lists L62–63)
- L130–175 is an entire test (`Phase 5b-follow-up-1`) asserting anchor-query
  behaviour, with `access_anchors_entry=`/`access_anchors_exit=` fixtures and
  `one_to_many_table(..., exclude_toll=False)` / `many_to_one_table(...)` stubs.
  With anchors removed this test is obsolete — delete it (or rewrite to assert
  gates are queried at their raw `gate_coords`). Also update the remaining
  `exclude_toll=False` stub signatures (L171/175/229/232) to
  `costing_options=None`.

### `tests/test_phase1d_pairs.py`  (not listed in plan or Phase 9 at all)
- L117–127 `_osrm_route()` helper takes `exclude_toll: bool` and calls
  `engine.route(origin, destination, toll_free=exclude_toll, geometry=geometry)`.
  `route()` loses `toll_free` (Phase 2j), so this breaks at call time.
  Change the helper's `exclude_toll: bool` param to
  `costing_options: dict | None = None` and the call to
  `engine.route(origin, destination, geometry=geometry, costing_options=costing_options)`.
- Update call sites: L203/246/312 `_osrm_route(..., exclude_toll=False)` →
  drop the arg (defaults to normal costing); L313
  `_osrm_route(..., exclude_toll=True)` (the toll-free comparison) →
  `costing_options=routing_engine._TOLL_PENALTY_COSTING`. Import the constant.
  Confirmed by grep 2026-08-21 (L121/124/203/246/312/313).

### `tests/test_pareto.py`  (not listed in plan or Phase 9 at all)
- L58–59 pass `access_anchors_entry=dict(g.access_anchors_entry)` /
  `access_anchors_exit=dict(g.access_anchors_exit)` into a `Graph()` fixture.
  Those fields are removed in Phase 3b, so the fixture raises `TypeError`.
  Delete both lines. Confirmed by grep 2026-08-21 (L58/59).

## Phase 10 grep pattern is too broad (guaranteed false failures)

The plan's grep matches bare `toll_free`, which legitimately survives in:
- `response.py` `toll_free_route` label (L267/319/390) — user-facing route option
- `matrices.py` `_toll_free_isolation_summary`, `engine.table(..., toll_free=True)`
- `test_matrices.py` `toll_free: bool = False` stubs (kept per Phase 9)
- `snap_report.py` `toll_free_distance_m` output keys (if kept)

Narrow the Phase 10 grep to the actually-removed identifiers so it can reach
zero:
```
grep -rnE '\b_notoll\b|DEFAULT_TOLLFREE|tollfree_url|exclude_toll|access_anchors|:8003|localhost:8003' \
  tollroute/ tests/ --include='*.py' | grep -v __pycache__
```
Keep `toll_free` out of the pattern (it is retained on `table`/`asymmetric_table`
and in the response label).

## Prerequisites (verified 2026-08-21, all met)
- Valhalla `:8002` and `:8003` both return 200.
- `tollroute/db/tollroute_national.sqlite` (9.6 MB): `access_anchors`=1180 rows,
  `gates`=974 rows with `canonical_name`, `snap_lat`, `snap_lon`, `lat`, `lon`.
  (The root `national.db`, `data/national.db`, `tollroute_national.sqlite` are
  all 0 bytes — do not point Phase 0 at those.)
- Phase 0 geocoding needs internet (`api-adresse.data.gouv.fr`).
