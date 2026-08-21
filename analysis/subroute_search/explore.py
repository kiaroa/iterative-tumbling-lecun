"""Sub-route search-tree exploration (see /home/hugh/.claude/plans/subroute-search-exploration.md).

Question: does a manual sub-route search tree over an OSRM route's toll sections find
cheaper France routes than the two options OSRM gives for free (fastest, full exclude=toll)?

Method per OD pair:
  1. OSRM alternatives=3.
  2. Snap toll gates to each polyline, group into contiguous toll sections.
  3. Per section build candidates: keep-full / skip / partial (enter and exit at
     intermediate gates).
  4. DP across sections over (stage, current position) to combine choices exactly, at
     several values of time.
  5. Compare best tree result against fastest-route and full-notoll baselines.

Run: venv/bin/python3 analysis/subroute_search/explore.py
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
import sqlite3
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import substring

OSRM = os.environ.get("OSRM_BASE_URL", "http://localhost:5000")
DB = Path("tollroute/db/tollroute_national.sqlite")
OUT_DIR = Path("analysis/subroute_search")

GATE_SNAP_M = 300          # same threshold as analysis/gate_validation/route_decompose.py
GAP_KM = 60                # along-route gap between snapped gates that ends a toll section
FREE_ROAD_MAX_SEPARATION_M = 300   # a toll-free line this close to the driven line IS the driven road
PROBE_MARGIN_M = 2000      # how far outside a section to anchor the toll-free probe
ALIAS_RADIUS_M = 500       # co-located gate records treated as one physical point for pricing
MAX_SECTION_GATES = 6      # endpoints + up to 4 intermediates -> <=15 candidate pairs
VOTS = (5.0, 10.0, 20.0, 40.0)   # EUR/hour
N_PAIRS = 25
DIST_MIN_KM, DIST_MAX_KM = 350.0, 450.0
SEED = 20260814
WORKERS = 8
VEHICLE_CLASS = "class1"   # car

# ponytail: coordinates typed from memory, accurate to a few km. Immaterial at 400 km,
# but this is not a verified commune dataset - stated as a caveat in the report.
CITIES = [
    ("Paris", 48.8566, 2.3522), ("Lyon", 45.7640, 4.8357), ("Marseille", 43.2965, 5.3698),
    ("Toulouse", 43.6047, 1.4442), ("Nice", 43.7102, 7.2620), ("Nantes", 47.2184, -1.5536),
    ("Montpellier", 43.6108, 3.8767), ("Strasbourg", 48.5734, 7.7521),
    ("Bordeaux", 44.8378, -0.5792), ("Lille", 50.6292, 3.0573), ("Rennes", 48.1173, -1.6778),
    ("Reims", 49.2583, 4.0317), ("Le Havre", 49.4944, 0.1079),
    ("Saint-Etienne", 45.4397, 4.3872), ("Toulon", 43.1242, 5.9280),
    ("Grenoble", 45.1885, 5.7245), ("Dijon", 47.3220, 5.0415), ("Angers", 47.4784, -0.5632),
    ("Nimes", 43.8367, 4.3601), ("Clermont-Ferrand", 45.7772, 3.0870),
    ("Le Mans", 48.0061, 0.1996), ("Aix-en-Provence", 43.5297, 5.4474),
    ("Brest", 48.3904, -4.4861), ("Tours", 47.3941, 0.6848), ("Amiens", 49.8941, 2.2957),
    ("Limoges", 45.8336, 1.2611), ("Annecy", 45.8992, 6.1294),
    ("Perpignan", 42.6887, 2.8948), ("Besancon", 47.2378, 6.0241), ("Metz", 49.1193, 6.1757),
    ("Orleans", 47.9029, 1.9092), ("Rouen", 49.4432, 1.0999), ("Mulhouse", 47.7508, 7.3359),
    ("Caen", 49.1829, -0.3707), ("Nancy", 48.6921, 6.1844), ("Poitiers", 46.5802, 0.3404),
    ("La Rochelle", 46.1603, -1.1511), ("Pau", 43.2951, -0.3708),
    ("Bayonne", 43.4929, -1.4748), ("Calais", 50.9513, 1.8587), ("Troyes", 48.2973, 4.0744),
    ("Valence", 44.9333, 4.8924), ("Chambery", 45.5646, 5.9178), ("Avignon", 43.9493, 4.8055),
    ("Bourges", 47.0810, 2.3987), ("Chartres", 48.4469, 1.4890), ("Niort", 46.3239, -0.4646),
    ("Auxerre", 47.7982, 3.5731), ("Vannes", 47.6582, -2.7608), ("Albi", 43.9298, 2.1480),
    ("Perigueux", 45.1840, 0.7214), ("Roanne", 46.0356, 4.0680),
    ("Montauban", 44.0181, 1.3549), ("Charleville-Mezieres", 49.7719, 4.7161),
]

_TR = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
_INV = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)


def _to_latlon(point):
    lon, lat = _INV.transform(point.x, point.y)
    return (lat, lon)

OSRM_CALLS = 0


# --------------------------------------------------------------------------- data

def load_gates(conn):
    rows = conn.execute(
        "SELECT gare_id, canonical_name, lat, lon, primary_route FROM gates WHERE lat IS NOT NULL"
    ).fetchall()
    out = []
    for gid, name, lat, lon, route in rows:
        x, y = _TR.transform(lon, lat)
        out.append({"id": gid, "name": name, "lat": lat, "lon": lon, "x": x, "y": y,
                    "route": route or ""})
    return out


def build_aliases(gates):
    """gare_id -> tuple of gate ids that are the same physical point, itself included.

    `gare_master.csv` holds several records per interchange, and they do not carry the same
    fares. On Calais->Amboise the A10 section snapped `LA FOLIE-B/PARIS` (192 fares) and
    `AMBOISE CH.RENAULT` (192 fares) - records with no fare between them - while `PARIS (LA
    FOLIE BESSIN)` 0 m away (400 fares) and `CHATEAU-RENAULT` 386 m away (321 fares) price
    that exact journey at EUR 22.40. Without alias resolution the whole A10 leg was crossed
    as an unpriced boundary and charged EUR 0.

    Matched within ALIAS_RADIUS_M *and* on a compatible route tag (equal, or blank on either
    side). The route condition is what keeps this from merging the genuinely separate
    carriageway barriers that sit 50-100 m apart, which `cluster_gates` warns about.
    """
    aliases = {}
    for g in gates:
        group = [g["id"]]
        for other in gates:
            if other["id"] == g["id"]:
                continue
            if math.hypot(g["x"] - other["x"], g["y"] - other["y"]) > ALIAS_RADIUS_M:
                continue
            ra, rb = (g.get("route") or ""), (other.get("route") or "")
            if ra and rb and ra != rb:
                continue
            group.append(other["id"])
        aliases[g["id"]] = tuple(group)
    return aliases


def load_fares(conn):
    """(from_gare_id, to_gare_id) -> price for VEHICLE_CLASS. Keeps the cheapest row when a
    pair appears more than once (time-banded rows exist in the source).

    Honours the same row-level quarantine as `tollroute/graph.py`, so the tree and the engine
    price from one fare set - otherwise `compare_engine.py` measures two pricing models
    disagreeing rather than two search strategies.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(fares)")}
    where = " WHERE quarantined = 0" if "quarantined" in columns else ""
    fares = {}
    for a, b, price in conn.execute(
        f"SELECT from_gare_id, to_gare_id, {VEHICLE_CLASS} FROM fares{where}"
    ):
        if price is None or price == "":
            continue
        try:
            p = float(price)
        except (TypeError, ValueError):
            continue
        k = (a, b)
        if k not in fares or p < fares[k]:
            fares[k] = p
    return fares


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def sample_pairs():
    rng = random.Random(SEED)
    cands = []
    for i in range(len(CITIES)):
        for j in range(i + 1, len(CITIES)):
            a, b = CITIES[i], CITIES[j]
            d = haversine_km((a[1], a[2]), (b[1], b[2]))
            if DIST_MIN_KM <= d <= DIST_MAX_KM:
                cands.append((a, b, d))
    rng.shuffle(cands)
    return cands[:N_PAIRS]


# --------------------------------------------------------------------------- OSRM

_leg_cache: dict[tuple, dict | None] = {}


def _fetch_leg(client, key):
    (lat1, lon1), (lat2, lon2), exclude = key
    url = f"/route/v1/car/{lon1},{lat1};{lon2},{lat2}?overview=false"
    if exclude:
        url += "&exclude=toll"
    global OSRM_CALLS
    OSRM_CALLS += 1
    for attempt in range(2):
        try:
            d = client.get(url, timeout=60).json()
            if d.get("code") != "Ok":
                return None
            r = d["routes"][0]
            return {"duration": r["duration"], "distance": r["distance"]}
        except Exception:
            if attempt:
                return None
            time.sleep(0.5)
    return None


def fetch_legs(client, keys):
    todo = [k for k in dict.fromkeys(keys) if k not in _leg_cache]
    if not todo:
        return
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for k, v in zip(todo, ex.map(lambda k: _fetch_leg(client, k), todo)):
            _leg_cache[k] = v


def leg(a, b, exclude):
    if a == b:
        return {"duration": 0.0, "distance": 0.0}
    return _leg_cache.get((a, b, exclude))


def alternatives(client, a, b):
    url = (f"/route/v1/car/{a[1]},{a[0]};{b[1]},{b[0]}"
           "?alternatives=3&overview=full&geometries=geojson")
    global OSRM_CALLS
    OSRM_CALLS += 1
    d = client.get(url, timeout=120).json()
    if d.get("code") != "Ok":
        return []
    return d["routes"]


def notoll_route(client, a, b):
    return leg(a, b, True)


# --------------------------------------------------------------------------- snapping

def route_line(coords):
    """Projected LineString for a GeoJSON coordinate list."""
    return LineString([_TR.transform(lon, lat) for lon, lat in coords])


def snap_gates(coords, gates):
    """Ordered [(fraction_along, gate)] for gates within GATE_SNAP_M of the polyline."""
    pts = [_TR.transform(lon, lat) for lon, lat in coords]
    line = LineString(pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs) - GATE_SNAP_M, max(xs) + GATE_SNAP_M
    miny, maxy = min(ys) - GATE_SNAP_M, max(ys) + GATE_SNAP_M
    hits = []
    for g in gates:
        if not (minx <= g["x"] <= maxx and miny <= g["y"] <= maxy):
            continue
        p = Point(g["x"], g["y"])
        if line.distance(p) <= GATE_SNAP_M:
            hits.append((line.project(p), g))
    hits.sort(key=lambda t: t[0])
    # de-duplicate gates snapping to nearly the same point (clustered gantries)
    out = []
    for frac, g in hits:
        if out and frac - out[-1][0] < 200:
            continue
        out.append((frac, g))
    return out


def sections(snapped):
    """Group snapped gates into toll sections by contiguity along the route.

    Heuristic (flagged): a gap of more than GAP_KM between consecutive snapped gates ends
    the section. Fare-table adjacency cannot be used for this - it shatters a single
    continuous motorway run at every operator boundary and open-system barrier.
    """
    secs, cur, prev = [], [], None
    for frac, g in snapped:
        if cur and frac - prev > GAP_KM * 1000:
            if len(cur) >= 2:
                secs.append(cur)
            cur = []
        cur.append(g)
        prev = frac
    if len(cur) >= 2:
        secs.append(cur)
    return secs


def leg_geometry(client, a, b, exclude_toll):
    """Projected LineString for a route between two (lat, lon) points, or None."""
    url = f"/route/v1/car/{a[1]},{a[0]};{b[1]},{b[0]}?overview=full&geometries=geojson"
    if exclude_toll:
        url += "&exclude=toll"
    global OSRM_CALLS
    OSRM_CALLS += 1
    try:
        data = client.get(url, timeout=60).json()
    except Exception:
        return None
    if data.get("code") != "Ok":
        return None
    coords = data["routes"][0]["geometry"]["coordinates"]
    return route_line(coords) if len(coords) >= 2 else None


def drop_untolled_sections(client, line, snapped, secs):
    """Discard sections whose gates the route passes *beside* rather than *through*.

    Snapping proves proximity, not use. Where a free road parallels a tolled motorway its
    gates snap to a toll-free route and get charged anyway: an `exclude=toll` Abbeville ->
    Amboise route snaps ROUEN LES ESSARTS (35.5 m) and INCARVILLE (215.9 m) and was billed
    EUR 2.40 for an A13 it cannot legally have used.

    Test: take two points *on the driven line*, PROBE_MARGIN_M outside the section, and route
    between them with tolls excluded. If that toll-free line nearly coincides with the driven
    line (Hausdorff below FREE_ROAD_MAX_SEPARATION_M) then the driven road was reachable
    without paying, so the section is not a toll section.

    Anchoring the probe on the *line* rather than on the two gates is what makes this work.
    Gate coordinates sit on tolled tarmac, so a gate-to-gate toll-free route always has to
    detour around them and always looks divergent - measured 2.42 km even for a section the
    route genuinely drove toll-free. Measured with line anchoring: genuine toll sections give
    2.42 km, 6.98 km, 35.39 km or no toll-free route at all; the phantom gives 0.00 km.
    """
    frac_of = {id(g): frac for frac, g in snapped}
    kept = []
    for sec in secs:
        a, b = frac_of.get(id(sec[0])), frac_of.get(id(sec[-1]))
        if a is None or b is None or b <= a:
            kept.append(sec)
            continue
        lo, hi = max(a - PROBE_MARGIN_M, 0.0), min(b + PROBE_MARGIN_M, line.length)
        p1, p2 = line.interpolate(lo), line.interpolate(hi)
        free = leg_geometry(client, _to_latlon(p1), _to_latlon(p2), exclude_toll=True)
        if free is None:
            kept.append(sec)  # no toll-free route at all: certainly a toll section
            continue
        if free.hausdorff_distance(substring(line, lo, hi)) > FREE_ROAD_MAX_SEPARATION_M:
            kept.append(sec)
    return kept


def chain_prices(sec, fares, aliases=None):
    """Return (prices, n_cuts) for a section.

    prices[(i, j)] is the fare for travelling from the section's i-th to j-th gate.

    A section can span more than one concession. Where the fares table has no priced link
    at all spanning a gate boundary, that boundary is a *cut*: the route stays on the
    motorway but a new ticket starts, so crossing it costs nothing extra. Within each run
    between cuts, the price is the cheapest sum of available fare links (a single
    through-fare wins whenever the table has one). n_cuts is reported because each cut is
    a place where a genuinely-missing fare would be silently priced at EUR 0.

    **A cut touching either end of the requested span makes that span unpriceable, not
    free.** An interior cut is a real concession boundary - two tickets, no extra charge for
    the crossing - but a cut at the entry or exit means the fare for that end of the journey
    is simply missing, and charging EUR 0 for it silently loses real money. This is what hid
    EUR 8.00 of A10 toll on Calais->Amboise.

    `aliases` (from `build_aliases`) resolves duplicate records for one physical point;
    without it, a section endpoint can land on the record that happens to carry no fares.
    Where several alias pairs price the same movement the highest is taken: they describe one
    physical journey, and under-charging is the failure mode being fixed here.
    """
    ids = [g["id"] for g in sec]

    def fare_between(a, b):
        if aliases is None:
            return fares.get((a, b))
        best = None
        for x in aliases.get(a, (a,)):
            for y in aliases.get(b, (b,)):
                p = fares.get((x, y))
                if p is not None and (best is None or p > best):
                    best = p
        return best
    n = len(ids)
    spans = [0] * max(n - 1, 1)
    for i in range(n):
        for j in range(i + 1, n):
            if fare_between(ids[i], ids[j]) is not None:
                for k in range(i, j):
                    spans[k] += 1
    cuts = {k for k in range(n - 1) if spans[k] == 0}
    runs, start = [], 0
    for k in range(n - 1):
        if k in cuts:
            runs.append((start, k))
            start = k + 1
    runs.append((start, n - 1))

    chain = {}
    for lo, hi in runs:
        for i in range(lo, hi + 1):
            best = {i: 0.0}
            for a in range(i, hi + 1):
                if a not in best:
                    continue
                for b in range(a + 1, hi + 1):
                    pr = fare_between(ids[a], ids[b])
                    if pr is not None and best[a] + pr < best.get(b, float("inf")):
                        best[b] = best[a] + pr
            for b, v in best.items():
                if b > i:
                    chain[(i, b)] = v

    # A published through-fare always wins over a sum of shorter hops. In a closed system you
    # pay the entry->exit fare; you only pay the sum of the hops if you physically leave and
    # re-enter at each junction, which a through route does not do. Without this, Calais->
    # Amboise priced A16 Boulogne Est -> Abbeville Nord at EUR 7.70 by chaining
    # 1.10 + 1.70 + 3.10 + 1.80, against the EUR 9.30 through fare that exists for that exact
    # span - a EUR 1.60 under-price on one section. Chaining stays as the fallback for spans
    # the table has no through fare for (concession boundaries, cross-motorway pairs).
    for i in range(n):
        for j in range(i + 1, n):
            direct = fare_between(ids[i], ids[j])
            if direct is not None:
                chain[(i, j)] = direct

    out = {}
    for i in range(n):
        for j in range(i + 1, n):
            if i in cuts or (j - 1) in cuts:
                continue  # missing fare at an end of the span: unpriceable, never free
            total, ok, touched = 0.0, True, 0
            for lo, hi in runs:
                a, b = max(i, lo), min(j, hi)
                if a > hi or b < lo:
                    continue
                touched += 1
                if a >= b:
                    continue
                v = chain.get((a, b))
                if v is None:
                    ok = False
                    break
                total += v
            # a leg spanning a cut that prices at exactly EUR 0 is an artefact of the
            # free-boundary-crossing model (both run segments collapsed to zero length),
            # not a free road - treat it as unpriceable
            if ok and not (touched > 1 and total == 0.0):
                out[(i, j)] = total
    return out, len(cuts)


def section_price(prices, sec):
    """Price the whole section end to end; None when the fares table cannot cover it."""
    return prices.get((0, len(sec) - 1))


def thin_idx(sec):
    """<= MAX_SECTION_GATES gate indices: both endpoints plus evenly spaced intermediates."""
    if len(sec) <= MAX_SECTION_GATES:
        return list(range(len(sec)))
    return sorted({round(i * (len(sec) - 1) / (MAX_SECTION_GATES - 1))
                   for i in range(MAX_SECTION_GATES)})


def build_candidates(secs, all_prices):
    """Per section: list of (entry_gate, exit_gate, toll_eur) over a thinned gate set.
    `skip` is handled by the DP."""
    out = []
    for sec, prices in zip(secs, all_prices):
        idx = thin_idx(sec)
        cands = []
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                p = prices.get((idx[a], idx[b]))
                if p is None:
                    continue
                cands.append((sec[idx[a]], sec[idx[b]], p))
        out.append(cands)
    return out


def pt(g):
    return (g["lat"], g["lon"])


def needed_legs(origin, dest, cands):
    """Every OSRM leg the DP can ask for, so they can be fetched in one concurrent batch."""
    keys = []
    positions = [origin]
    for stage in cands:
        entries = {pt(e) for e, _, _ in stage}
        for p in positions:
            for e in entries:
                keys.append((p, e, True))       # connector: toll-free
        for e, x, _ in stage:
            keys.append((pt(e), pt(x), False))  # section leg: tolled
        positions = positions + [pt(x) for _, x, _ in stage]
    for p in positions:
        keys.append((p, dest, True))
    keys.append((origin, dest, True))
    return keys


def dp(origin, dest, cands, vot, allow_skip=True):
    """Shortest generalised cost over (stage, position). Returns (G, eur, seconds, choices)."""
    INF = float("inf")
    # position -> (G, eur, seconds, choices)
    state = {origin: (0.0, 0.0, 0.0, ())}
    for k, stage in enumerate(cands):
        # skipping this section keeps the current position untouched
        nxt = dict(state) if allow_skip else {}
        for p, (g, eur, sec, ch) in state.items():
            for e, x, toll in stage:
                conn = leg(p, pt(e), True)
                inner = leg(pt(e), pt(x), False)
                if conn is None or inner is None:
                    continue
                sec2 = sec + conn["duration"] + inner["duration"]
                eur2 = eur + toll
                g2 = eur2 + vot * sec2 / 3600.0
                key = pt(x)
                if key not in nxt or g2 < nxt[key][0]:
                    nxt[key] = (g2, eur2, sec2, ch + ((k, e["id"], x["id"], toll),))
        state = nxt
    best = None
    for p, (g, eur, sec, ch) in state.items():
        tail = leg(p, dest, True)
        if tail is None:
            continue
        sec2 = sec + tail["duration"]
        g2 = eur + vot * sec2 / 3600.0
        if best is None or g2 < best[0]:
            best = (g2, eur, sec2, ch)
    return best if best else (INF, INF, INF, ())


# --------------------------------------------------------------------------- main

def main():
    conn = sqlite3.connect(DB)
    gates = load_gates(conn)
    fares = load_fares(conn)
    aliases = build_aliases(gates)
    pairs = sample_pairs()
    print(f"{len(pairs)} OD pairs, {len(gates)} gates, {len(fares)} priced gate pairs, "
          f"{sum(1 for v in aliases.values() if len(v) > 1)} gates with a co-located alias",
          file=sys.stderr)

    rows = []
    diag = []
    client = httpx.Client(base_url=OSRM)

    for n, (a, b, gc_km) in enumerate(pairs, 1):
        t0 = time.time()
        calls0 = OSRM_CALLS
        origin, dest = (a[1], a[2]), (b[1], b[2])
        routes = alternatives(client, origin, dest)
        if not routes:
            diag.append({"pair": f"{a[0]}->{b[0]}", "error": "no_route"})
            continue

        fetch_legs(client, [(origin, dest, True)])
        nt = notoll_route(client, origin, dest)

        per_alt = []
        for ai, r in enumerate(routes):
            snapped = snap_gates(r["geometry"]["coordinates"], gates)
            secs = sections(snapped)
            secs = drop_untolled_sections(
                client, route_line(r["geometry"]["coordinates"]), snapped, secs
            )
            priced_cuts = [chain_prices(sec, fares, aliases) for sec in secs]
            all_prices = [pc[0] for pc in priced_cuts]
            n_cuts = sum(pc[1] for pc in priced_cuts)
            priced = [section_price(pr, sec) for pr, sec in zip(all_prices, secs)]
            unpriced = sum(1 for p in priced if p is None)
            toll_total = sum(p for p in priced if p is not None)
            cands = build_candidates(secs, all_prices)
            fetch_legs(client, needed_legs(origin, dest, cands))
            full_only = [[c for c in stage if c[0]["id"] == secs[i][0]["id"]
                          and c[1]["id"] == secs[i][-1]["id"]]
                         for i, stage in enumerate(cands)]  # diagnostic: reconstruction gap
            fetch_legs(client, needed_legs(origin, dest, full_only))
            per_alt.append({
                "idx": ai,
                "full_only": full_only,
                "duration": r["duration"], "distance": r["distance"],
                "gates": len(snapped), "sections": len(secs),
                "unpriced_sections": unpriced, "toll_eur": toll_total,
                "n_cuts": n_cuts,
                "cands": cands,
            })

        fastest = per_alt[0]
        for vot in VOTS:
            base_fast_g = fastest["toll_eur"] + vot * fastest["duration"] / 3600.0
            base_nt_g = vot * nt["duration"] / 3600.0 if nt else float("inf")
            base_g = min(base_fast_g, base_nt_g)
            base_name = "fastest" if base_fast_g <= base_nt_g else "notoll"

            best = None
            for alt in per_alt:
                # the unmodified alternative is a candidate ("keep the original"), but
                # only when every one of its sections could be priced
                if alt["unpriced_sections"] == 0:
                    asis = (alt["toll_eur"] + vot * alt["duration"] / 3600.0,
                            alt["toll_eur"], alt["duration"], (), alt["idx"],
                            "asis" if alt["idx"] == 0 else "other_alt")
                    if best is None or asis[0] < best[0]:
                        best = asis
                g, eur, sec, ch = dp(origin, dest, alt["cands"], vot)
                if best is None or g < best[0]:
                    best = (g, eur, sec, ch, alt["idx"],
                            "surgery" if ch else "all_skip")
            rows.append({
                "pair": f"{a[0]}->{b[0]}", "gc_km": round(gc_km, 1), "vot": vot,
                "fastest_min": round(fastest["duration"] / 60, 1),
                "fastest_km": round(fastest["distance"] / 1000, 1),
                "fastest_eur": round(fastest["toll_eur"], 2),
                "fastest_sections": fastest["sections"],
                "fastest_unpriced": fastest["unpriced_sections"],
                "notoll_min": round(nt["duration"] / 60, 1) if nt else "",
                "notoll_km": round(nt["distance"] / 1000, 1) if nt else "",
                "baseline": base_name, "baseline_G": round(base_g, 2),
                "tree_min": round(best[2] / 60, 1), "tree_eur": round(best[1], 2),
                "tree_G": round(best[0], 2), "tree_alt": best[4],
                "tree_kind": best[5],
                "gain_vs_baseline_G": round(base_g - best[0], 2),
                "eur_saved_vs_fastest": round(fastest["toll_eur"] - best[1], 2),
                "min_added_vs_fastest": round((best[2] - fastest["duration"]) / 60, 1),
                "n_choices": len(best[3]),
            })
        elapsed = time.time() - t0
        recon = dp(origin, dest, fastest["full_only"], 20.0, allow_skip=False)
        diag.append({"pair": f"{a[0]}->{b[0]}", "osrm_calls": OSRM_CALLS - calls0,
                     "recon_full_min": round(recon[2] / 60, 1) if recon[2] != float("inf") else None,
                     "actual_fastest_min": round(fastest["duration"] / 60, 1),
                     "n_alternatives": len(per_alt),
                     "alts_unpriced": sum(1 for x in per_alt if x["unpriced_sections"] > 0),
                     "fastest_cuts": fastest["n_cuts"],
                     "seconds": round(elapsed, 1),
                     "alt_sections": [x["sections"] for x in per_alt],
                     "alt_toll_eur": [round(x["toll_eur"], 2) for x in per_alt],
                     "alt_unpriced": [x["unpriced_sections"] for x in per_alt]})
        print(f"[{n}/{len(pairs)}] {a[0]}->{b[0]} "
              f"{OSRM_CALLS - calls0} calls {elapsed:.1f}s "
              f"sections={[x['sections'] for x in per_alt]}", file=sys.stderr)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (OUT_DIR / "diagnostics.json").write_text(json.dumps(diag, indent=1))

    summarise(rows, diag)


def summarise(rows, diag):
    def med(xs):
        xs = [x for x in xs if isinstance(x, (int, float))]
        return round(statistics.median(xs), 2) if xs else float("nan")

    print("\n=== SUMMARY ===")
    per_pair = {}
    for r in rows:
        per_pair.setdefault(r["pair"], r)
    zero_price = sum(1 for r in per_pair.values() if r["fastest_eur"] == 0)
    print(f"pairs: {len(per_pair)}   fastest route already zero-price: {zero_price}")
    print(f"median OSRM calls/pair: {med([d.get('osrm_calls') for d in diag])}  "
          f"median seconds/pair: {med([d.get('seconds') for d in diag])}")
    print(f"pairs with >=1 unpriced section on fastest: "
          f"{sum(1 for r in per_pair.values() if r['fastest_unpriced'] > 0)}")
    print()
    hdr = f"{'VoT':>5} {'beats baseline':>15} {'med gain G':>11} {'med EUR saved':>14} {'med min added':>14}"
    print(hdr)
    for vot in VOTS:
        rs = [r for r in rows if r["vot"] == vot and r["fastest_unpriced"] == 0]
        wins = [r for r in rs if r["gain_vs_baseline_G"] > 0.01]
        surg = [r for r in wins if r["tree_kind"] == "surgery"]
        print(f"{vot:>5} {f'{len(wins)}/{len(rs)} ({len(surg)} surgery)':>15} "
              f"{med([r['gain_vs_baseline_G'] for r in rs]):>11} "
              f"{med([r['eur_saved_vs_fastest'] for r in rs]):>14} "
              f"{med([r['min_added_vs_fastest'] for r in rs]):>14}")


if __name__ == "__main__":
    main()
