"""Gate validity verdicts from the gate-validation suite.

`analysis/gate_validation/` scores every gate against several independent signals — name and
role flags, OSRM snap distance, Overpass toll infrastructure, Google place lookup — and writes
a `LIKELY_VALID` / `UNCERTAIN` / `LIKELY_INVALID` verdict per gate to `gate_scores.csv`.

**Why this module reads a CSV rather than recomputing the verdict:** two of the four signals
are external API calls (Google Places, Overpass). They cannot run inside an ETL build, so the
verdict is inherently a precomputed artefact — the same class of input as `gare_master.csv` and
`od_pairs.csv`, which this package already reads from the repo root. Re-implementing the
scoring here would produce a second, weaker verdict that silently disagrees with the one in
`analysis/gate_validation/report.html`.

Used by `tollroute.validation.distance_error` as the second of the two signals a gate must fail
before it is quarantined. See that module for why one signal is not enough.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GATE_SCORES_PATH = REPO_ROOT / "analysis" / "gate_validation" / "gate_scores.csv"

LIKELY_VALID = "LIKELY_VALID"
UNCERTAIN = "UNCERTAIN"
LIKELY_INVALID = "LIKELY_INVALID"


def load_verdicts(path: Path = DEFAULT_GATE_SCORES_PATH) -> dict[int, str]:
    """gare_id -> verdict. Empty dict (with a warning) if the artefact is absent, so a build
    on a checkout that has never run the validation suite degrades to "no verdict signal"
    rather than failing."""
    if not path.exists():
        logger.warning(
            "gate verdicts unavailable (%s not found); run analysis/gate_validation/run_all.py "
            "to regenerate. No gate will be quarantined on the verdict signal.",
            path,
        )
        return {}
    with path.open() as f:
        return {
            int(row["gare_id"]): row["verdict"]
            for row in csv.DictReader(f)
            if row.get("gare_id") and row.get("verdict")
        }


def invalid_gate_ids(path: Path = DEFAULT_GATE_SCORES_PATH) -> set[int]:
    """Gates the validation suite scored `LIKELY_INVALID`."""
    return {gid for gid, verdict in load_verdicts(path).items() if verdict == LIKELY_INVALID}


def non_physical_gate_ids(path: Path = DEFAULT_GATE_SCORES_PATH) -> set[int]:
    """Gates that are not a physical toll point at all, on evidence that needs neither the
    distance matrix nor a live route: scored `LIKELY_INVALID`, flagged `VIRTUAL` (the name
    describes a toll *system*, not a barrier) and `OD_SINK_ONLY` (it is never an origin, so
    no driver can enter the network there).

    **This currently matches exactly one gate — 844 "Système Ouvert"** — and the narrowness
    is the point. `LIKELY_INVALID` alone matches nine, of which eight are real toll points or
    real tariff endpoints carrying 418 fare rows between them: `Le Boulou` x3 (140 rows),
    `Tarare est` x2 (38), `Frontière Espagnole` (140), and two `limite de concession` markers
    (68). Those are odd *labels*, not fictions, and dropping them would delete A9 border and
    A89 prices. `VIRTUAL` alone matches six and would take the Le Boulou and Tarare est
    records with it. Requiring "never an origin" as well is what separates a system-wide
    label from a barrier with a strange name.
    """
    if not path.exists():
        return set()
    with path.open() as f:
        rows = list(csv.DictReader(f))
    return {
        int(row["gare_id"])
        for row in rows
        if row.get("verdict") == LIKELY_INVALID
        and "VIRTUAL" in (row.get("flags") or "")
        and "OD_SINK_ONLY" in (row.get("flags") or "")
    }
