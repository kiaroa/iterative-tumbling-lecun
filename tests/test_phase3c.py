"""End-to-end smoke test for the Phase 3c orchestrator
(tollroute/validation/phase3c.py) - requires the live national OSRM instance.
"""

import httpx
import pytest

from tollroute.routing_engine import DEFAULT_FULL_URL
from tollroute.validation import phase3c


def _osrm_reachable() -> bool:
    try:
        httpx.get(f"{DEFAULT_FULL_URL}/status", timeout=2.0)
        return True
    except Exception:
        return False


requires_osrm = pytest.mark.skipif(
    not _osrm_reachable(), reason="live Valhalla instance not reachable on DEFAULT_FULL_URL"
)


@requires_osrm
def test_run_writes_a_combined_report(tmp_path):
    db_path = tmp_path / "full.sqlite"
    report_path = tmp_path / "phase3c.md"
    phase3c.run(db_path=db_path, report_path=report_path)

    assert report_path.exists()
    text = report_path.read_text()
    assert "# Phase 3c" in text
    assert "## 1. Snap quality" in text
    assert "## 2. OSRM distance vs `distance_km`" in text
    assert "## 3. Toll-tagging audit" in text
    assert "## Exit criterion" in text
