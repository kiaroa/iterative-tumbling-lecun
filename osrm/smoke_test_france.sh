#!/usr/bin/env bash
# Phase 3a smoke test: the national France OSRM instance answers /nearest, /route and
# /table for points OUTSIDE the Phase 1 bfc-ara regional extract, and returns a valid
# north<->south crossing (Lille -> Marseille), with exclude=toll changing that route.
# Assumes `OSRM_NETWORK=france docker compose up -d` is serving osrm-routed on :5000.
set -euo pipefail

BASE_URL="${OSRM_BASE_URL:-http://localhost:5000}"

# Points well outside the Bourgogne-Franche-Comte + Auvergne-Rhone-Alpes extract (lon,lat).
LILLE="3.0573,50.6292"      # far north
MARSEILLE="5.3698,43.2965"  # far south (Mediterranean)
BREST="-4.4861,48.3904"     # far west (Brittany)
BORDEAUX="-0.5792,44.8378"  # south-west

echo "== /nearest (out-of-region points) =="
for pt in "$LILLE" "$MARSEILLE" "$BREST" "$BORDEAUX"; do
  curl -sf "${BASE_URL}/nearest/v1/car/${pt}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['code'] == 'Ok', d
print('  OK:', d['waypoints'][0]['name'] or '(unnamed)', d['waypoints'][0]['location'])
"
done

echo "== /table (Lille;Marseille;Brest;Bordeaux) =="
curl -sf "${BASE_URL}/table/v1/car/${LILLE};${MARSEILLE};${BREST};${BORDEAUX}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['code'] == 'Ok', d
n = len(d['durations'])
assert n == 4, d
# Every off-diagonal cell must be routable across the national extract.
for i in range(n):
    for j in range(n):
        if i != j:
            assert d['durations'][i][j] is not None, (i, j, d['durations'])
print('  OK: 4x4 durations matrix fully populated')
"

echo "== /route Lille -> Marseille (tolls allowed) =="
ROUTE_TOLL=$(curl -sf "${BASE_URL}/route/v1/car/${LILLE};${MARSEILLE}?overview=false")
echo "$ROUTE_TOLL" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['code'] == 'Ok', d
r = d['routes'][0]
# A genuine north-south crossing is ~1000 km; guard against a degenerate short route.
assert r['distance'] > 800_000, r['distance']
print(f\"  OK: distance {r['distance']:.0f}m duration {r['duration']:.0f}s\")
"

echo "== /route Lille -> Marseille (exclude=toll) =="
ROUTE_NOTOLL=$(curl -sf "${BASE_URL}/route/v1/car/${LILLE};${MARSEILLE}?overview=false&exclude=toll")
echo "$ROUTE_NOTOLL" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['code'] == 'Ok', d
print(f\"  OK: distance {d['routes'][0]['distance']:.0f}m duration {d['routes'][0]['duration']:.0f}s\")
"

echo "== compare toll vs toll-free =="
python3 -c "
import json
toll = json.loads('''$ROUTE_TOLL''')['routes'][0]
notoll = json.loads('''$ROUTE_NOTOLL''')['routes'][0]
print(f\"  toll route:      distance={toll['distance']:.0f}m duration={toll['duration']:.0f}s\")
print(f\"  toll-free route: distance={notoll['distance']:.0f}m duration={notoll['duration']:.0f}s\")
if toll['distance'] == notoll['distance'] and toll['duration'] == notoll['duration']:
    raise SystemExit('FAIL: exclude=toll returned an identical route to the default')
print('  PASS: exclude=toll returns a different route')
"

echo "ALL FRANCE SMOKE TESTS PASSED"
