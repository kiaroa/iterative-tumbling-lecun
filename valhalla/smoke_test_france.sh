#!/usr/bin/env bash
# Smoke tests for both Valhalla instances.
#
# Assumes both services are running:
#   VALHALLA_DATA_DIR=... docker compose up -d
#
# Tests:
#   - /status responds on both instances
#   - /route returns a valid route (Lille → Marseille) on the full instance
#   - /sources_to_targets returns a valid matrix on the full instance
#   - /locate snaps a Paris coordinate on the full instance
#   - The notoll instance returns a materially LONGER route Lille → Marseille
#     than the full instance (detour around motorways)
set -euo pipefail

FULL_URL="${VALHALLA_FULL_URL:-http://localhost:8002}"
NOTOLL_URL="${VALHALLA_NOTOLL_URL:-http://localhost:8003}"

pass=0
fail=0

check() {
    local desc="$1"
    local result="$2"
    local expected="$3"
    if echo "$result" | grep -q "$expected"; then
        echo "  PASS  $desc"
        pass=$((pass + 1))
    else
        echo "  FAIL  $desc"
        echo "        expected to find: $expected"
        echo "        got: $(echo "$result" | head -c 200)"
        fail=$((fail + 1))
    fi
}

require_gt() {
    local desc="$1"
    local val="$2"
    local threshold="$3"
    if python3 -c "import sys; sys.exit(0 if float('$val') > float('$threshold') else 1)" 2>/dev/null; then
        echo "  PASS  $desc ($val > $threshold)"
        pass=$((pass + 1))
    else
        echo "  FAIL  $desc ($val not > $threshold)"
        fail=$((fail + 1))
    fi
}

# Lille (50.6292, 3.0573) → Marseille (43.2965, 5.3698) — genuine north-south crossing
LILLE='{"lat":50.6292,"lon":3.0573}'
MARSEILLE='{"lat":43.2965,"lon":5.3698}'

echo "=== Full instance (${FULL_URL}) ==="

status=$(curl -sf "${FULL_URL}/status")
check "/status responds" "$status" "version\|tileset_last_modified"

route_full=$(curl -sf -X POST "${FULL_URL}/route" \
    -H 'Content-Type: application/json' \
    -d "{\"locations\":[${LILLE},${MARSEILLE}],\"costing\":\"auto\",\"format\":\"osrm\"}")
check "/route Lille→Marseille returns Ok" "$route_full" '"code":"Ok"'

full_distance=$(echo "$route_full" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['routes'][0]['distance'])")
require_gt "/route distance > 700 km (real crossing, not degenerate)" "$full_distance" 700000

matrix=$(curl -sf -X POST "${FULL_URL}/sources_to_targets" \
    -H 'Content-Type: application/json' \
    -d "{\"sources\":[${LILLE}],\"targets\":[${MARSEILLE}],\"costing\":\"auto\",\"units\":\"km\"}")
check "/sources_to_targets responds" "$matrix" "sources_to_targets"

matrix_time=$(echo "$matrix" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['sources_to_targets'][0][0]['time'])")
require_gt "/sources_to_targets time > 3600 s (real journey)" "$matrix_time" 3600

locate=$(curl -sf -X POST "${FULL_URL}/locate" \
    -H 'Content-Type: application/json' \
    -d '{"locations":[{"lat":48.8566,"lon":2.3522}],"costing":"auto"}')
check "/locate Paris returns edges" "$locate" '"edges"'

echo ""
echo "=== Notoll instance (${NOTOLL_URL}) ==="

status_notoll=$(curl -sf "${NOTOLL_URL}/status")
check "/status responds" "$status_notoll" "version\|tileset_last_modified"

route_notoll=$(curl -sf -X POST "${NOTOLL_URL}/route" \
    -H 'Content-Type: application/json' \
    -d "{\"locations\":[${LILLE},${MARSEILLE}],\"costing\":\"auto\",\"format\":\"osrm\"}")
check "/route Lille→Marseille returns Ok" "$route_notoll" '"code":"Ok"'

notoll_distance=$(echo "$route_notoll" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['routes'][0]['distance'])")
require_gt "Notoll route longer than full (avoids motorways)" "$notoll_distance" "$full_distance"

echo ""
if [ "$fail" -eq 0 ]; then
    echo "All ${pass} smoke tests passed."
else
    echo "${fail} of $((pass+fail)) tests FAILED."
    exit 1
fi
