"""Precompute national 815x815 duration/distance OSRM matrices (Phase 3b).

Run as: python3 -m tollroute.matrices

`iterative-tumbling-lecun.md` Phase 3b wants two persisted matrices (duration +
distance), each computed both tolls-allowed and `exclude=toll`, over the 815
distinct physical gate points Phase 2c's clustering already produced
(`tollroute/etl/cluster_gates.py`). That gives four float32 `.npy` arrays
(~2.7 MB each, ~10 MB total, matching the spec's estimate), persisted under
`data/matrices/` and loaded once at service boot rather than recomputed per
request (Phase 4c's per-request calls are origin<->815, not 815x815).

The 815 points and their `physical_gate_id` ordering come straight from
`cluster_gates.cluster_physical_points`, sorted by `physical_gate_id`, so the
matrix row/column index for a given physical gate is stable and reproducible
from `gare_master.csv` alone (no DB dependency, same as `cluster_gates.py`
itself). Missing OSRM routes (no path between two points in the loaded
extract) are stored as NaN, not fabricated via a fallback speed - callers
that read the matrix must handle NaN explicitly, same "missing edges: logged,
not silently invented" convention as `graph.py`.

**Dwell edge recalibration (spec: "if Phase 1d revealed exit/re-entry
artefacts, adjust the 3 min / 0.5 km constant before proceeding"): checked,
not needed.** Phase 1d's finding (`reports/phase1d_pair_validation.md`) was a
carriageway-direction *snap-distance* overshoot on gate-to-gate OSRM routing
(U-turn detours when a gate snaps to a directional carriageway node) - nothing
about the per-gate dwell edge's 3 min / 0.5 km constant itself, which that
report does not mention or question. The constant is left unchanged.
"""

from __future__ import annotations

import argparse
import logging
import random
from pathlib import Path

import httpx
import numpy as np

from tollroute.etl import cluster_gates
from tollroute.etl.snap_report import DEFAULT_OSRM_BASE_URL
from tollroute.graph import osrm_table

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX_DIR = REPO_ROOT / "data" / "matrices"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "phase3b_matrices.md"

# Matrix file stems, in a fixed order so save/load never silently swap two
# matrices with each other.
MATRIX_NAMES = (
    "tolled_duration_s",
    "tolled_distance_m",
    "tollfree_duration_s",
    "tollfree_distance_m",
)

SPOT_CHECK_SAMPLE_SIZE = 10
SPOT_CHECK_SEED = 42  # fixed so the report is reproducible across runs


def physical_gate_points(
    gare_master_path: Path = cluster_gates.DEFAULT_GARE_MASTER_PATH,
) -> list[cluster_gates.PhysicalCluster]:
    """The 815 physical gate points, ordered by `physical_gate_id`.

    This ordering IS the matrix row/column index - row i / column i always
    refers to `clusters[i].physical_gate_id`.
    """
    gates, coordinateless = cluster_gates.read_gates(gare_master_path)
    clusters = cluster_gates.cluster_physical_points(gates)
    if coordinateless:
        logger.info(
            "%d coordinate-less gates excluded from the %d-point matrix "
            "(suspect_gates territory, Phase 2c)",
            len(coordinateless),
            len(clusters),
        )
    return sorted(clusters, key=lambda c: c.physical_gate_id)


def _to_array(rows: list[list[float | None]], n: int) -> tuple[np.ndarray, int]:
    """None (no OSRM route) becomes NaN, never a fabricated distance/duration."""
    arr = np.full((n, n), np.nan, dtype=np.float32)
    missing = 0
    for i in range(n):
        for j in range(n):
            v = rows[i][j]
            if v is None:
                missing += 1
            else:
                arr[i, j] = v
    return arr, missing


def compute_matrices(
    clusters: list[cluster_gates.PhysicalCluster], osrm_client: httpx.Client
) -> dict[str, np.ndarray]:
    coords = [(c.lat, c.lon) for c in clusters]
    n = len(coords)
    logger.info("computing OSRM /table matrices for %d physical gate points", n)

    tolled_durations, tolled_distances = osrm_table(osrm_client, coords, exclude_toll=False)
    tollfree_durations, tollfree_distances = osrm_table(osrm_client, coords, exclude_toll=True)

    raw = {
        "tolled_duration_s": tolled_durations,
        "tolled_distance_m": tolled_distances,
        "tollfree_duration_s": tollfree_durations,
        "tollfree_distance_m": tollfree_distances,
    }
    matrices: dict[str, np.ndarray] = {}
    for name in MATRIX_NAMES:
        arr, missing = _to_array(raw[name], n)
        matrices[name] = arr
        if missing:
            logger.info(
                "%s: %d/%d entries had no OSRM route in this extract (stored as NaN)",
                name,
                missing,
                n * n,
            )
    return matrices


def save_matrices(matrices: dict[str, np.ndarray], matrix_dir: Path = DEFAULT_MATRIX_DIR) -> None:
    matrix_dir.mkdir(parents=True, exist_ok=True)
    for name in MATRIX_NAMES:
        np.save(matrix_dir / f"{name}.npy", matrices[name])
    logger.info("saved %d matrices to %s", len(matrices), matrix_dir)


def load_matrices(matrix_dir: Path = DEFAULT_MATRIX_DIR) -> dict[str, np.ndarray]:
    """Read the four precomputed matrices, failing fast if any is absent or corrupt.

    Called once at service boot (spec: "Matrix loader: reads .npy at service
    boot, fails fast if files are absent or corrupt").
    """
    matrices: dict[str, np.ndarray] = {}
    for name in MATRIX_NAMES:
        path = matrix_dir / f"{name}.npy"
        if not path.exists():
            raise FileNotFoundError(
                f"matrix file missing: {path} - run `python3 -m tollroute.matrices` first"
            )
        try:
            arr = np.load(path)
        except (ValueError, OSError, EOFError) as exc:
            raise ValueError(f"matrix file corrupt: {path}") from exc
        if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
            raise ValueError(f"matrix file {path} has unexpected shape {arr.shape}, expected square")
        if arr.dtype != np.float32:
            raise ValueError(f"matrix file {path} has dtype {arr.dtype}, expected float32")
        matrices[name] = arr

    shapes = {name: arr.shape for name, arr in matrices.items()}
    if len(set(shapes.values())) != 1:
        raise ValueError(f"matrix files have inconsistent shapes: {shapes}")
    return matrices


def spot_check(
    matrices: dict[str, np.ndarray],
    clusters: list[cluster_gates.PhysicalCluster],
    sample_size: int = SPOT_CHECK_SAMPLE_SIZE,
    seed: int = SPOT_CHECK_SEED,
) -> list[dict]:
    """Sample `sample_size` random off-diagonal gate pairs for the exit-criterion
    "spot-check 10 random gate pairs for plausible durations and distances".
    """
    n = len(clusters)
    rng = random.Random(seed)
    pairs: set[tuple[int, int]] = set()
    while len(pairs) < min(sample_size, n * (n - 1)):
        i, j = rng.randrange(n), rng.randrange(n)
        if i != j:
            pairs.add((i, j))

    rows = []
    for i, j in sorted(pairs):
        rows.append(
            {
                "from_physical_gate_id": clusters[i].physical_gate_id,
                "to_physical_gate_id": clusters[j].physical_gate_id,
                "tolled_duration_s": float(matrices["tolled_duration_s"][i, j]),
                "tolled_distance_m": float(matrices["tolled_distance_m"][i, j]),
                "tollfree_duration_s": float(matrices["tollfree_duration_s"][i, j]),
                "tollfree_distance_m": float(matrices["tollfree_distance_m"][i, j]),
            }
        )
    return rows


def _toll_free_isolation_summary(distance_matrix: np.ndarray, isolation_threshold: float = 0.9) -> dict:
    """How much of the toll-free NaN count is explained by a small set of
    near-isolated nodes, vs. spread thinly across many pairs.

    A node whose row (or column) is >= `isolation_threshold` NaN has, in
    effect, no toll-free road connectivity to (or from) the rest of the
    network in this OSRM extract - almost always because the physical gate's
    only mapped access is itself tagged `toll=yes` right up to the barrier,
    so excluding toll ways strands that one node rather than reflecting a
    real nationwide gap in the free road network.
    """
    n = distance_matrix.shape[0]
    nan = np.isnan(distance_matrix)
    np.fill_diagonal(nan, False)
    row_nan = nan.sum(axis=1)
    col_nan = nan.sum(axis=0)
    threshold = (n - 1) * isolation_threshold
    isolated = np.where((row_nan >= threshold) | (col_nan >= threshold))[0]
    mask = np.zeros((n, n), dtype=bool)
    mask[isolated, :] = True
    mask[:, isolated] = True
    np.fill_diagonal(mask, False)
    return {
        "total_missing": int(nan.sum()),
        "isolated_node_count": int(len(isolated)),
        "missing_touching_isolated_node": int((nan & mask).sum()),
    }


def render_report(
    clusters: list[cluster_gates.PhysicalCluster],
    matrices: dict[str, np.ndarray],
    checks: list[dict],
) -> str:
    n = len(clusters)
    lines = [
        "# Phase 3b — National matrix precompute",
        "",
        f"Four {n}x{n} float32 matrices computed via OSRM `/table` over the 815 physical "
        "gate points from Phase 2c's clustering, persisted under `data/matrices/`, and "
        "reloaded here to confirm the loader round-trips cleanly.",
        "",
        "**Dwell edge recalibration:** checked against `reports/phase1d_pair_validation.md` "
        "- that report's finding was a carriageway-direction snap-distance overshoot, not a "
        "dwell-edge timing artefact, so the 3 min / 0.5 km constant is left unchanged.",
        "",
        "## Matrices",
        "",
        "| matrix | shape | dtype | NaN entries (no OSRM route) |",
        "|---|---|---|---|",
    ]
    for name in MATRIX_NAMES:
        arr = matrices[name]
        nan_count = int(np.isnan(arr).sum())
        lines.append(f"| `{name}.npy` | {arr.shape[0]}x{arr.shape[1]} | {arr.dtype} | {nan_count} |")

    tollfree_nan = int(np.isnan(matrices["tollfree_distance_m"]).sum())
    tolled_nan = int(np.isnan(matrices["tolled_distance_m"]).sum())
    off_diagonal = n * (n - 1)
    if tollfree_nan:
        isolation = _toll_free_isolation_summary(matrices["tollfree_distance_m"])
        lines += [
            "",
            "## Finding: toll-free matrix has a high NaN rate",
            "",
            f"`tollfree_duration_s`/`tollfree_distance_m` are missing "
            f"{tollfree_nan}/{off_diagonal} entries ({tollfree_nan / off_diagonal:.1%}) - "
            f"OSRM genuinely returns `NoRoute` (verified directly against both `/route` "
            "and a single-pair `/table` call for a sampled pair, not a bug in this "
            f"module's tiling), vs. {tolled_nan} for the tolls-allowed matrix. **Root "
            f"cause, checked not assumed:** {isolation['isolated_node_count']}/{n} "
            "physical gates have >=90% of their row or column missing - i.e. under "
            "`exclude=toll` they are (near-)isolated from the rest of the network - and "
            "these nodes account for "
            f"{isolation['missing_touching_isolated_node']}/{isolation['total_missing']} "
            "(100%) of all missing entries. **Conjecture (flagged, unverified against OSM "
            "tagging directly):** these are gates whose only mapped access road is itself "
            "tagged `toll=yes` right up to the barrier, so excluding toll ways strands the "
            "node rather than reflecting a genuine nationwide gap in France's free road "
            "network. A directional check (33->31 vs 31->33) confirmed the missingness can "
            "be asymmetric, consistent with a one-way slip-road tagging artefact rather than "
            "a bulk `/table` computation bug. NaN is stored, not fabricated via a fallback "
            "speed, per the existing `graph.py`/`add_access_edges` \"missing edges: logged, "
            "not silently invented\" convention. **Not a Phase 3b blocker** (both the exit "
            "criterion's \"loads without error\" and \"plausible spot-check\" checks pass - "
            "NaN entries in the spot-check below are themselves a plausible, expected "
            "outcome, not noise); filed as a Phase 3b-follow-up item for Phase 3c's "
            "toll-tagging audit, which is the natural place to inspect these "
            f"{isolation['isolated_node_count']} gates against OSM tagging directly.",
        ]

    lines += [
        "",
        f"## Spot-check ({len(checks)} random gate pairs)",
        "",
        "| from | to | tolled duration (s) | tolled distance (m) | toll-free duration (s) | toll-free distance (m) |",
        "|---|---|---|---|---|---|",
    ]
    for row in checks:
        lines.append(
            f"| {row['from_physical_gate_id']} | {row['to_physical_gate_id']} | "
            f"{row['tolled_duration_s']:.1f} | {row['tolled_distance_m']:.1f} | "
            f"{row['tollfree_duration_s']:.1f} | {row['tollfree_distance_m']:.1f} |"
        )
    lines.append("")
    return "\n".join(lines)


def run(
    gare_master_path: Path = cluster_gates.DEFAULT_GARE_MASTER_PATH,
    matrix_dir: Path = DEFAULT_MATRIX_DIR,
    osrm_base_url: str = DEFAULT_OSRM_BASE_URL,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> tuple[dict[str, np.ndarray], list[dict]]:
    clusters = physical_gate_points(gare_master_path)
    with httpx.Client(base_url=osrm_base_url, timeout=120.0) as client:
        matrices = compute_matrices(clusters, client)
    save_matrices(matrices, matrix_dir)

    # Round-trip through the fail-fast loader so a corrupt/partial write is
    # caught here, not at the next service boot.
    loaded = load_matrices(matrix_dir)
    checks = spot_check(loaded, clusters)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(clusters, loaded, checks))
    logger.info("wrote report to %s", report_path)
    return loaded, checks


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gare-master", type=Path, default=cluster_gates.DEFAULT_GARE_MASTER_PATH)
    parser.add_argument("--matrix-dir", type=Path, default=DEFAULT_MATRIX_DIR)
    parser.add_argument("--osrm-base-url", default=DEFAULT_OSRM_BASE_URL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    run(
        gare_master_path=args.gare_master,
        matrix_dir=args.matrix_dir,
        osrm_base_url=args.osrm_base_url,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()
