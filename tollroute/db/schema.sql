-- SQLite schema for the toll-minimising route service.
-- Source spec: iterative-tumbling-lecun.md. Populated by the Phase 1b+ ETL loaders
-- (tollroute/etl/*.py) — this file only defines structure, no data.

PRAGMA foreign_keys = ON;

-- One row per toll gate, sourced from gare_master.csv (956 rows, 953 with lat/lon).
-- snap_* columns are filled by the Phase 1b OSRM /nearest snapping step, not the CSV load.
CREATE TABLE IF NOT EXISTS gates (
    gare_id             INTEGER PRIMARY KEY,
    canonical_name      TEXT,
    all_names           TEXT,
    primary_route       TEXT,
    all_routes          TEXT,
    inferred_route      TEXT,
    junction_ref        TEXT,
    all_junctions       TEXT,
    operators           TEXT,
    name_collision      TEXT,
    lat                 REAL,
    lon                 REAL,
    pr_km               REAL,
    commune             TEXT,
    departement         TEXT,
    is_interchange      TEXT,
    connecting_road     TEXT,
    direction_served    TEXT,
    toll_system_type    TEXT,
    concession_boundary TEXT,
    gare_type           TEXT,
    match_tier          TEXT,
    match_agreement     TEXT,
    match_source        TEXT,
    snap_lat            REAL,
    snap_lon            REAL,
    snap_distance_m     REAL
);

-- One row per fare-matrix entry, sourced from od_pairs.csv (57,378 rows).
-- Each row is a virtual toll edge: entry gate -> exit gate, priced per vehicle class.
-- class1..class5 are nullable: zero-price rows are loaded (never silently dropped) and
-- remediated as typed dispositions in Phase 2b.
CREATE TABLE IF NOT EXISTS fares (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_gare_id  INTEGER,
    to_gare_id    INTEGER,
    operator      TEXT NOT NULL,
    from_route    TEXT,
    from_junction TEXT,
    from_gare     TEXT,
    to_route      TEXT,
    to_junction   TEXT,
    to_gare       TEXT,
    distance_km   REAL,
    start_time    TEXT,
    end_time      TEXT,
    class1        REAL,
    class2        REAL,
    class3        REAL,
    class4        REAL,
    class5        REAL,
    -- Row-level quarantine (Phase 3c revision). Set by
    -- `tollroute.validation.distance_error`: a fare row whose source `distance_km` and the
    -- OSRM tolled distance disagree beyond the threshold is dropped on its own, instead of
    -- quarantining its endpoint gate and taking every other fare that touches it down too.
    quarantined      INTEGER NOT NULL DEFAULT 0,
    quarantine_reason TEXT,
    FOREIGN KEY (from_gare_id) REFERENCES gates (gare_id),
    FOREIGN KEY (to_gare_id) REFERENCES gates (gare_id)
);

CREATE INDEX IF NOT EXISTS idx_fares_from_gare_id ON fares (from_gare_id);
CREATE INDEX IF NOT EXISTS idx_fares_to_gare_id ON fares (to_gare_id);
CREATE INDEX IF NOT EXISTS idx_fares_operator ON fares (operator);

-- Operator name normalisation (spec: "Operator alias map: SQLite table, not source code").
-- raw_name is the exact casing/spelling as it appears in the source CSVs
-- (e.g. "sanef", "ASFC", "escota", "aliea"); canonical_operator is the normalised form.
CREATE TABLE IF NOT EXISTS operator_alias (
    raw_name          TEXT PRIMARY KEY,
    canonical_operator TEXT NOT NULL
);

-- Gates quarantined out of the routing graph (spec: the "suspect_gates" table referenced
-- by Phases 2c, 2d and 3c). Populated incrementally by each phase's curation step:
--   Phase 2c (tollroute/etl/freeflow.py): coordinate-less gates.
--   Phase 2d (coverage audit): gates snapping >200 m from any road.
--   Phase 3c (snap-quality): unresolvable snaps / >20% OSRM-vs-distance_km deviation.
-- affected_od_pairs records how many od_pairs fare rows reference the gate, so the cost of
-- excluding it is visible (spec: "logged with affected OD pair count").
-- Deliberately NO foreign key to gates(gare_id): the canonical gates table is built
-- operator-filtered until the Phase 2d national build, so a suspect gate may be absent from
-- it, and an FK would couple load order (DELETE FROM gates would fail while suspect rows
-- reference it). The exclusion list must survive independently of the gates table.
CREATE TABLE IF NOT EXISTS suspect_gates (
    gare_id           INTEGER PRIMARY KEY,
    canonical_name    TEXT,
    reason            TEXT NOT NULL,
    source_phase      TEXT NOT NULL,
    affected_od_pairs INTEGER NOT NULL DEFAULT 0,
    detail            TEXT
);

-- Per-corridor flat-fee override for free-flow (barrierless) tolling, where a corridor's
-- fares are ABSENT from od_pairs (spec Phase 2c: "If absent from fare matrix, add per-corridor
-- flat-fee override table"). Structure only; intentionally EMPTY at Phase 2c because the
-- free-flow audit (tollroute/etl/freeflow.py) found A79, A13 and A14 all present in od_pairs,
-- so no override is required yet. Ready for a future free-flow corridor genuinely missing its
-- fares (one row per corridor per vehicle class).
--
-- operator/is_conjecture (Phase 5b-follow-up-2, nullable/default 0): fee-provenance
-- bookkeeping for a genuine single-structure concession (e.g. the Millau viaduct/CEVM) that
-- sits on a corridor this project otherwise treats as untolled. Such a structure has no
-- dataset gate at all, so it is seeded as a real self-loop gate/fares row instead (same
-- shape A14's 5 dataset self-loop rows already use, wired by `build_graph`'s existing
-- self-loop handling with no override-table involvement) - this table only records where
-- each vehicle class's fee came from. is_conjecture flags a vehicle class whose fee was
-- interpolated from another class's sourced figure rather than read directly from the
-- operator's own tariff (same convention as class_config.is_conjecture).
CREATE TABLE IF NOT EXISTS freeflow_override (
    corridor        TEXT NOT NULL,
    vehicle_class   INTEGER NOT NULL,
    flat_fee_eur    REAL NOT NULL,
    note            TEXT,
    operator        TEXT,
    is_conjecture   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (corridor, vehicle_class)
);

-- Per-vehicle-class generalised-cost defaults (Phase 4a: G = toll + km*running_cost_per_km
-- + hours*value_of_time_eur_per_hour). Populated by Phase 4a, not this scaffold; structure
-- only. is_conjecture flags figures not yet sourced from DGITM/EU data.
CREATE TABLE IF NOT EXISTS class_config (
    vehicle_class              INTEGER PRIMARY KEY,
    running_cost_per_km        REAL,
    value_of_time_eur_per_hour REAL,
    is_conjecture              INTEGER NOT NULL DEFAULT 0
);

-- Per-gate, per-direction toll-free "access anchor" for `add_access_edges`
-- (Phase 5b-follow-up-1, direction split added in Phase 5b-follow-up-1-continued).
-- A gate's own coordinate IS the physical barrier, sitting on tolled tarmac by
-- definition, so an `exclude=toll` OSRM query straight to it can return NoRoute even
-- when a real driver reaches the barrier fine - Phase 3c's toll-tagging audit already
-- found this is usually NOT a "toll tag starts too early" problem (the immediate access
-- road is typically not toll-tagged at all - reports/phase3c.md section 3b) but a
-- broader graph-connectivity gap: the gate's local toll-free road pocket doesn't connect
-- through to the rest of the toll-free network without eventually crossing a toll
-- segment somewhere close by. `tollroute.etl.access_anchors` finds, per affected gate
-- and per direction, the nearest point on the real (plain) driving route between the
-- gate and a reference city that is both toll-free-reachable in the correct direction
-- AND verified NOT to be an isolated pocket.
--
-- `direction` is 'entry' (used for `add_access_edges`'s origin->gate IN-node legs;
-- reachability checked reference->anchor) or 'exit' (used for the gate's OUT/OUT_TOLL->
-- destination legs; reachability checked anchor->reference) - kept as separate rows
-- rather than one shared anchor because reachability on a divided/oneway motorway is
-- directional: verified directly that reusing one direction's anchor for the other
-- silently breaks it (7/8 sampled Phase 5b-follow-up-1 anchors, validated only in the
-- exit direction, turned out unreachable in the entry direction - see
-- reports/phase5b_followup1_continued.md).
--
-- apron_distance_m/apron_duration_s is the plain (toll allowed) OSRM leg between the
-- anchor and the gate's own coordinate (anchor->gate for 'entry', gate->anchor for
-- 'exit') - short by construction (the anchor is the nearest point along the real route
-- that clears the isolated pocket), so letting the final local hop use toll tarmac
-- cannot resurrect the Phase 1c free-ride bug (`exclude=toll` on the *whole* access edge
-- is what fixed that; this table only ever contributes a few hundred metres right at the
-- barrier). No row for a given (gare_id, direction) means no reachable anchor was found
-- for that direction - `add_access_edges` falls back to its pre-existing "leg is None ->
-- omitted, gap logged" behaviour for that direction only.
CREATE TABLE IF NOT EXISTS access_anchors (
    gare_id          INTEGER NOT NULL,
    direction        TEXT NOT NULL CHECK (direction IN ('entry', 'exit')),
    anchor_lat       REAL NOT NULL,
    anchor_lon       REAL NOT NULL,
    apron_distance_m REAL NOT NULL,
    apron_duration_s REAL NOT NULL,
    PRIMARY KEY (gare_id, direction),
    FOREIGN KEY (gare_id) REFERENCES gates (gare_id)
);
