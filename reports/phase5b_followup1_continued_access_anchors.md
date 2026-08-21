# Phase 5b-follow-up-1-continued — direction-aware access-anchor precompute

Rewrote the anchor search to do what this module's own docstring always claimed (walk backward along the real route's geometry, not probe outward from `/nearest` - the latter picks wrong-carriageway candidates on divided motorways) and made reachability direction-aware (entry: reference -> gate; exit: gate -> reference), since a shared anchor validated only in the exit direction was found silently wrong for entry in most of the previous iteration's shipped anchors. Full investigation in this module's docstring.

Checked **974** snapped, non-quarantined gates, per direction:
- **entry**: 590 needed an anchor; 590 found; 0 still gapped (no verified-connected candidate within 2000 m of route distance).
- **exit**: 590 needed an anchor; 590 found; 0 still gapped (no verified-connected candidate within 2000 m of route distance).

Anchor apron distance (both directions combined): min 0 m, median 34 m, max 957 m.

