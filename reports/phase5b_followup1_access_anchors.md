# Phase 5b-follow-up-1 — access-anchor precompute

Investigation revised the plan item's own hypothesis: OSM's `toll=yes`/`toll=no` tagging near Fleury-en-Bière/Paris-Lyon is already split at the right place, not "premature". The real mechanism - confirmed against the live national OSRM instance and consistent with `reports/phase3c.md` section 3b's already-published finding - is a local graph-connectivity gap right at some barriers' final approach, not a taggable per-segment fix.

Checked **910** snapped, non-quarantined gates. **67** needed an anchor (their own coordinate was not directly toll-free-reachable from any of 6 reference cities); **189** had no verified-connected candidate within 20 `/nearest` probes and are left exactly as before (`add_access_edges` omits them, gap logged - unchanged pre-existing behaviour).

Anchor apron distance: min 91 m, median 537 m, max 1990 m.

