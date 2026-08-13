"""Gate validation orchestrator.

Run from project root:
    python3 analysis/gate_validation/run_all.py [options]

Options:
    --limit N        Restrict API phases (2-5) to first N gates by gare_id (default: 20).
                     Pass --limit 0 for the full 956-gate run.
    --skip-osrm      Skip Phase 2 (OSRM snap check).
    --skip-overpass  Skip Phase 3 (Overpass toll booth check).
    --skip-google    Skip Phase 4 (Google Places check).
    --skip-decompose Skip Phase 5 (on-route gate detection).

Phases 1 (classify) and 6 (report) always run.
Results are cached — a phase is skipped if its output CSV already exists.
Delete the CSV to force a re-run of that phase.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# run from project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from analysis.gate_validation import classify, osrm_snap, overpass_check, google_check, route_decompose, report

VALIDATION_DIR = Path("analysis/gate_validation")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20,
                        help="Max gates for API phases (0 = all, default: 20)")
    parser.add_argument("--skip-osrm", action="store_true")
    parser.add_argument("--skip-overpass", action="store_true")
    parser.add_argument("--skip-google", action="store_true")
    parser.add_argument("--skip-decompose", action="store_true")
    args = parser.parse_args()

    limit = args.limit  # 0 means no limit

    print("=" * 60)
    print("Gate validation suite")
    print(f"  API limit: {'all gates' if limit == 0 else f'first {limit} gates'}")
    print("=" * 60)

    # Phase 1 — always run on all gates (free)
    classify_out = VALIDATION_DIR / "gate_classification.csv"
    if classify_out.exists():
        print(f"\nPhase 1: using cached {classify_out.name}")
    else:
        print("\n--- Phase 1: static classification ---")
        classify.classify()

    # Phase 2 — OSRM snap
    osrm_out = VALIDATION_DIR / "osrm_snap.csv"
    if args.skip_osrm:
        print("\nPhase 2: skipped (--skip-osrm)")
    elif osrm_out.exists():
        print(f"\nPhase 2: using cached {osrm_out.name}")
    else:
        print("\n--- Phase 2: OSRM snap check ---")
        try:
            osrm_snap.check_snap(limit=limit)
        except Exception as exc:
            print(f"  Phase 2 failed: {exc} (is OSRM running?)")

    # Phase 3 — Overpass
    overpass_out = VALIDATION_DIR / "overpass_check.csv"
    if args.skip_overpass:
        print("\nPhase 3: skipped (--skip-overpass)")
    elif overpass_out.exists():
        print(f"\nPhase 3: using cached {overpass_out.name}")
    else:
        print("\n--- Phase 3: Overpass toll booth check ---")
        try:
            overpass_check.check_overpass(limit=limit)
        except Exception as exc:
            print(f"  Phase 3 failed: {exc}")

    # Phase 4 — Google Places
    google_out = VALIDATION_DIR / "google_check.csv"
    if args.skip_google:
        print("\nPhase 4: skipped (--skip-google)")
    elif google_out.exists():
        print(f"\nPhase 4: using cached {google_out.name}")
    else:
        print("\n--- Phase 4: Google Places check ---")
        try:
            google_check.check_google(limit=limit)
        except Exception as exc:
            print(f"  Phase 4 failed: {exc}")

    # Phase 5 — route decomposition
    decompose_out = VALIDATION_DIR / "route_decomposition.csv"
    if args.skip_decompose:
        print("\nPhase 5: skipped (--skip-decompose)")
    elif decompose_out.exists():
        print(f"\nPhase 5: using cached {decompose_out.name}")
    else:
        print("\n--- Phase 5: on-route gate detection ---")
        try:
            route_decompose.decompose(limit=limit if limit else 200)
        except Exception as exc:
            print(f"  Phase 5 failed: {exc} (is OSRM running?)")

    # Phase 6 — synthesis report (always)
    print("\n--- Phase 6: synthesis report ---")
    report.build_report()

    print("\n" + "=" * 60)
    print("Done. Outputs in analysis/gate_validation/")
    print("  gate_scores.csv")
    print("  suspect_gate_candidates.csv")
    print("  report.html")


if __name__ == "__main__":
    main()
