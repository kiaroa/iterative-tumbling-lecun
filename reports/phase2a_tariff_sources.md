# Phase 2a — External tariff data source investigation

**Objective (spec §Phase 2a):** determine whether a machine-readable authoritative
French motorway tariff source exists before remediating `od_pairs.csv` in Phase 2b.

## Method

Web search + page fetches against `data.gouv.fr` and `autoroutes.fr` (ASFA), plus one
corroborating community source (an OpenStreetMap France forum thread on the identical
problem — computing toll cost for a given route). Direct `WebFetch` of two ASFA pages
(`autoroutes.fr/n-tarifs.htm`, `autoroutes.fr/fr/les-principaux-tarifs.htm`) failed with
a TLS certificate error in this environment; findings on ASFA below rest on search-result
snippets and the corroborating forum thread rather than a direct fetch of ASFA's own
markup — flagged as a secondary-source limitation, not a first-hand page read.

## Findings

### data.gouv.fr

Directly fetched (successful): **"Autoroutes et péages en flux libre"** dataset
(`data.gouv.fr/datasets/autoroutes-et-peages-en-flux-libre`), maintained by the Ministry
of Ecological Transition. 6 resource files (CSV/XLSX/GeoJSON/GPX), licence "Other
(Attribution)", last updated 2025-10-25. Content is **gantry/toll-terminal locations
only** — the dataset's own documentation states explicitly that toll amounts are not
included because they vary by vehicle class and change over time. Not a tariff source.

A second reuse, **"Réseau autoroutier français et tarifs"** (Tableau Public
visualisation, derived from the Ministry's "Gestionnaires du réseau routier national"
dataset), does show comparative tariff-evolution figures — but only for a handful of
named example routes, covering **2010–2018** (created 2018-05-23, page last touched
2024-04-30 with no indication the underlying price data was refreshed), with **no
downloadable raw dataset** — the data is only reachable through an interactive Tableau
view. Too stale, too partial (illustrative routes, not a full gate-pair matrix), and not
machine-readable in bulk. Not a viable source.

No other data.gouv.fr dataset surfaced in search results carrying per-gate or per-class
toll prices.

### ASFA (autoroutes.fr)

ASFA publishes a "Tarif autoroutier" page and per-year "principaux tarifs" pages, but
these present tariffs as **per-operator PDF documents and/or a route-based fare
calculator** (enter origin/destination, get a price for that specific journey), not a
downloadable structured table of gate-pair prices. This matches the independent
corroborating account in an OpenStreetMap France forum thread
(`forum.openstreetmap.fr/t/api-calcul-cout-des-peages-sur-un-itineraire-donne/1245`) from
developers who tried to solve the identical problem (toll cost by route, for OSM-based
routing): they report toll pricing exists **only as scattered per-operator PDFs with
inconsistent layouts**, no centralised repository, and no API — one participant's quote
translates as "it's crazy that in 2025 no public toll price dataset exists." No mention
of `data.gouv.fr` carrying tariff data either, consistent with the finding above.

## Assessment against the three questions

| Question | Answer |
|---|---|
| Source found? | **No.** No machine-readable, bulk-downloadable, per-gate/per-class tariff table exists at either `data.gouv.fr` or ASFA. |
| Supersedes `od_pairs.csv`? | **No** — there is nothing to supersede it with. |
| Vintage / licence / completeness (for the record, on what *does* exist) | data.gouv.fr's location-only dataset: current (Oct 2025), permissive attribution licence, but no prices. The one tariff-bearing reuse found: stale (2010–2018), partial (example routes only), not downloadable. ASFA: current tariffs exist per-operator but only as PDFs / a single-journey calculator, no bulk licence terms published for scraping. |

## Recommended action

Keep `od_pairs.csv` as the sole primary tariff input, as the spec already assumes
("`od_pairs.csv` is kept current by an external update process; no vintage gate is
needed" — spec, dataset table preamble). No source supersedes it, so Phase 2b's zero-
price/blank-ID remediation should proceed unchanged. For **spot-checking** re-matched
prices (Phase 2b) and the fare oracle (Phase 5a), use ASFA's per-route calculator and/or
individual operator calculators manually, one OD pair at a time — the only viable
comparison mechanism given no bulk source exists — exactly as the spec's Phase 5a
deliverable already allows ("data.gouv.fr/ASFA (if found in Phase 2a) or individual
operator calculators"). This is now resolved: **use individual operator calculators**,
since data.gouv.fr/ASFA carries no comparable bulk data.

**Decision recorded (2026-08-11):** no supersession; `od_pairs.csv` remains primary;
Phase 2b may begin unblocked.
