# Phase 1d — 5-pair validation (price, guard rail, OSRM distance)

Validation of the 5 named APRR test pairs against `od_pairs` and live regional OSRM
(`bfc-ara` extract), per `iterative-tumbling-lecun.md` Phase 1d. Tests:
`tests/test_phase1d_pairs.py`.

**Bottom line:** the **price** check passes cleanly for all 4 fare pairs. The **OSRM
distance** and **guard-rail** checks do **not** pass as literally worded, for genuine,
non-trivially-fixable reasons (carriageway-direction snap artefacts + a guard-rail
wording that doesn't fit real French toll geometry). Following the Phase 0 precedent,
this is documented here and filed as a new follow-up plan item rather than silently
forced to pass. The existing Phase 1d item is marked done with this result recorded.

## The 5 pairs

| # | pair | gates | od `distance_km` | od `class1` | snap quality |
|---|---|---|---|---|---|
| 1 | Dijon→Lyon | 269→930 | 149.15 | €14.10 | both <8 m |
| 2 | Paris→Lyon | 393→930 | 493.17 | €62.80 | gate 393 **71 km** (outside extract) |
| 3 | Clermont-Ferrand→Montpellier | — | — | — | no APRR fare row (A75 untolled) |
| 4 | Dijon→Mâcon | 269→495 | 118.93 | €11.10 | both <8 m |
| 5 | Beaune→Mâcon | 96→494 | 74.10 | €6.60 | both <7 m |

## Check 1 — price: PASS

The direct gate-to-gate route through the overlay graph (`find_route` on
`Node(from, OUT) → Node(to, IN_TOLL)`, single TOLL edge) returns `toll_eur` exactly
equal to `class1` for all 4 fare pairs (14.10, 62.80, 11.10, 6.60). Pair 3 has no APRR
fare row at all — A75 south of Clermont-Ferrand is an untolled state motorway (the
deliberate edge case documented in Phase 1b) — so there is no direct-toll price to
check; the price test skips it explicitly.

Verified: `test_direct_toll_edge_matches_od_pairs` — 4 passed, 1 skipped.

## Check 3 — OSRM distance vs `distance_km`: FAIL (documented)

Chosen tolerance: **5%** ("a few percent"). Justification below: with a clean
single-carriageway snap and no U-turn, OSRM motorway routing agrees with the operator's
tariff distance to ~1.5%, so 5% is a generous "few percent" ceiling.

Measured (live OSRM, gate snap-coord to gate snap-coord, `overview=full`):

| pair | od `distance_km` | OSRM tolled | error | southward overshoot | reverse-direction OSRM |
|---|---|---|---|---|---|
| 1 Dijon→Lyon | 149.15 km | 159.85 km | **+7.2%** | 5.2 km | 151.30 km (**+1.4%**) |
| 4 Dijon→Mâcon | 118.93 km | 161.89 km | **+36.1%** | 20.6 km | 120.96 km (**+1.7%**) |
| 5 Beaune→Mâcon | 74.10 km | 88.84 km | **+19.9%** | 4.4 km | 86.58 km (+16.8%) |
| 2 Paris→Lyon | 493.17 km | — | n/a | — | not testable (extract) |

None of the in-extract pairs is within 5%.

### Root cause (verified)

The forward (north→south) OSRM tolled route **overshoots south past the destination gate
then U-turns back to reach it**. For pair 4 the route dips to lat 46.10 (≈20.6 km south of
Mâcon Sud at lat 46.286) before doubling back north — a ~41 km round-trip detour that
directly accounts for the +36% inflation. Pair 1 shows the same pattern at ~5 km.

Two independent cross-checks confirm the overshoot is the dominant error source, not a
geocoding error (the snaps are 4–8 m, i.e. essentially exact):

1. **Reverse direction is clean.** Routing 495→269 and 930→269 (i.e. *departing* the
   gate northbound rather than arriving southbound) drops the error to +1.7% and +1.4%
   respectively — well inside 5%.
2. **Overshoot correction recovers `distance_km`.** `forward − 2 × overshoot` lands within
   ~0.2–1.5% of `distance_km` for pairs 1 and 4. This is asserted as a *passing* positive
   test (`test_uturn_overshoot_explains_distance_gap`) so the diagnosis is regression-guarded.

Pair 5's ~4.4 km overshoot explains only part of its error (a ~8% residual remains after
correction), so a second, smaller effect is also present there (plausibly that `distance_km`
for a short cross-corridor Beaune→Mâcon pairing is not a single-carriageway road distance —
not investigated further; that is Phase 3c's job).

### Conjecture (flagged, not verified against authoritative OSM data)

The overshoot is consistent with each toll-gate coordinate snapping to a node on a **single
directional carriageway** of the divided motorway. A route arriving from the *opposite*
carriageway cannot stop at that node directly; OSRM must continue to the next interchange,
cross over, and come back. I have **not** verified the carriageway side of each snapped node
against authoritative OSM way tagging in this pass — the direction-asymmetry evidence above is
strong but circumstantial. Whatever the precise mechanism, the mismatch is between
`distance_km` (the operator's tariff distance along one physical corridor run) and "OSRM route
to a literal, direction-specific gate node", not a coding bug in the graph layer.

### Systemic, not corridor-specific

A spot-check of 6 further in-extract, well-snapped (<50 m) APRR pairs (e.g. Ambérieu→Arlay
+34%, Ambérieu→Bellegarde +94%) shows the same 28–94% inflation. The gate-node-to-gate-node
OSRM distance check is therefore **not trustworthy at regional/gate-node scale generally**.
This is exactly what Phase 3c is scoped to resolve at national scale (snap-quality curation +
a full 22,175-row OSRM-vs-`distance_km` error distribution, hard-rejecting >20% deviation).
Fixing it inside Phase 1d would be doing Phase 3c's work early.

Pair 2 (Paris) is a *separate* known issue: gate 393 snaps 71 km away because Paris is outside
the regional `bfc-ara` extract (documented in Phase 1b). It is not testable until the Phase 3a
national build and is skipped, not counted as a fresh finding.

## Check 2 — guard rail (≥1 cheaper alternative, ≥10 km AND ≥5 min): FAIL (documented)

**Methodology chosen:** the plain OSRM `exclude=toll` gate-to-gate route as the "cheaper
alternative". This is exactly the €0 option the overlay graph surfaces against the tolled
direct edge, so a raw point-to-point OSRM pair is the most faithful, least-assumption way to
measure its extra km/min (no graph-forced-detour construction needed).

| pair | tolled | toll-free | extra km | extra min | literal ≥10 km AND ≥5 min |
|---|---|---|---|---|---|
| 1 Dijon→Lyon | 159.85 km / 94.8 min | 158.72 km / 166.3 min | **−1.1 km** | +71.6 min | **FAIL** (km) |
| 4 Dijon→Mâcon | 161.89 km / 96.0 min | 129.05 km / 134.3 min | **−32.8 km** | +38.3 min | **FAIL** (km) |
| 5 Beaune→Mâcon | 88.84 km / 53.5 min | 88.57 km / 86.0 min | **−0.3 km** | +32.5 min | **FAIL** (km) |

The **time** half of the guard rail always holds (the free route is +32 to +112 min slower).
The **distance** half never holds — the free N-road alternative is the same length or *shorter*
than the motorway, just slower. This is real French toll geometry (N6/N7 parallel the A6 closely)
and matches the handoff's diagnosis. Under the literal "AND" reading, no alternative qualifies, so
"≥1 cheaper alternative meets guard rails" cannot pass for any A6 pair.

The guard rail as written ("≥10 km AND ≥5 min") appears intended to suppress artefact
alternatives that differ only trivially; but it implicitly assumes the cheaper route is *longer*,
which does not hold for motorway-vs-parallel-N-road in France. It needs a documented
interpretation — most likely time-based ("≥5 min slower") or an OR — before it is testable. That
is a Phase 4b decision (Phase 4b owns the guard-rail response shaping), not a Phase 1d fix.

## Disposition

- **Price check: passes** — recorded on the Phase 1d item.
- **Distance + guard-rail checks: genuine findings, not trivially fixable in Phase 1d.**
  Encoded as non-strict `xfail`s in `tests/test_phase1d_pairs.py` (suite stays green, failures
  stay visible and self-documenting) plus the passing overshoot root-cause test.
- New follow-up plan item filed (see `IMPLEMENTATION_PLAN.md`, appended after the Phase 1d item)
  routing the distance check to Phase 3c and the guard-rail wording to Phase 4b. The existing
  Phase 1d item is **not** rewritten or deleted; it is marked done with this result.

## Test outcome

`python3 -m pytest tests/test_phase1d_pairs.py` — 6 passed, 3 skipped, 7 xfailed. Full suite:
25 passed, 3 skipped, 7 xfailed.
