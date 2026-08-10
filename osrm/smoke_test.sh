#!/usr/bin/env bash
# Phase 1a smoke test: /nearest, /route, /table respond; exclude=toll changes the
# Dijon->Lyon route. Assumes `docker compose up -d` is already running osrm-routed
# on localhost:5000 for the Bourgogne-Franche-Comte + Auvergne-Rhone-Alpes extract.
set -euo pipefail

BASE_URL="${OSRM_BASE_URL:-http://localhost:5000}"

# Dijon and Lyon centre coordinates (lon,lat).
DIJON="5.0415,47.3220"
LYON="4.8357,45.7640"

echo "== /nearest =="
curl -sf "${BASE_URL}/nearest/v1/car/${DIJON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['code'] == 'Ok', d
print('OK:', d['waypoints'][0]['name'], d['waypoints'][0]['location'])
"

echo "== /table =="
curl -sf "${BASE_URL}/table/v1/car/${DIJON};${LYON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['code'] == 'Ok', d
print('OK: durations matrix', d['durations'])
"

echo "== /route (tolls allowed) =="
ROUTE_TOLL=$(curl -sf "${BASE_URL}/route/v1/car/${DIJON};${LYON}?overview=false")
echo "$ROUTE_TOLL" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['code'] == 'Ok', d
print('OK: distance', d['routes'][0]['distance'], 'duration', d['routes'][0]['duration'])
"

echo "== /route (exclude=toll) =="
ROUTE_NOTOLL=$(curl -sf "${BASE_URL}/route/v1/car/${DIJON};${LYON}?overview=false&exclude=toll")
echo "$ROUTE_NOTOLL" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['code'] == 'Ok', d
print('OK: distance', d['routes'][0]['distance'], 'duration', d['routes'][0]['duration'])
"

echo "== compare toll vs toll-free =="
python3 -c "
import json
toll = json.loads('''$ROUTE_TOLL''')['routes'][0]
notoll = json.loads('''$ROUTE_NOTOLL''')['routes'][0]
print(f\"toll route:    distance={toll['distance']:.0f}m duration={toll['duration']:.0f}s\")
print(f\"toll-free route: distance={notoll['distance']:.0f}m duration={notoll['duration']:.0f}s\")
if toll['distance'] == notoll['distance'] and toll['duration'] == notoll['duration']:
    raise SystemExit('FAIL: exclude=toll returned an identical route to the default')
print('PASS: exclude=toll returns a different route')
"
