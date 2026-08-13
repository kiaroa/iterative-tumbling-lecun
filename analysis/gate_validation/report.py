"""Phase 6: synthesise all signal CSVs into a scored gate report.

Reads whichever phase CSVs exist and scores each gate. Writes:
  gate_scores.csv
  suspect_gate_candidates.csv
  report.html
"""

from __future__ import annotations

import csv
from pathlib import Path

SCORES = {
    "VIRTUAL": 4,
    "ADMIN_BOUNDARY": 3,
    "OSM_NO_TOLL_INFRA": 2,
    "GOOGLE_NO_MATCH": 2,
    "SNAP_NOT_TOLL": 2,
    "SNAP_FAR": 2,
    "OD_SINK_ONLY": 1,
    "OD_SOURCE_ONLY": 1,
    "MANUAL_OVERRIDE": 1,
    "LOW_CONFIDENCE": 1,
    "CONFLICTED": 1,
}

VALIDATION_DIR = Path("analysis/gate_validation")


def _load_latest() -> list[dict]:
    """Return per-gate rows from the most advanced phase CSV available."""
    for candidate in [
        "google_check.csv",
        "overpass_check.csv",
        "osrm_snap.csv",
        "gate_classification.csv",
    ]:
        path = VALIDATION_DIR / candidate
        if path.exists():
            print(f"Report: reading from {path.name}")
            return list(csv.DictReader(open(path)))
    raise FileNotFoundError("No gate validation phase CSV found. Run classify first.")


def build_report(out_dir: Path = VALIDATION_DIR) -> list[dict]:
    gates = _load_latest()

    rows_out = []
    for g in gates:
        active_flags: list[str] = []
        score = 0

        # name/role flags from classify
        for flag in (g.get("name_flags") or "").split("|"):
            flag = flag.strip()
            if not flag:
                continue
            if flag in SCORES:
                score += SCORES[flag]
                active_flags.append(flag)
            elif flag in ("BRETELLE", "BARRIERE", "PEAGE_EN", "LOW_CONFIDENCE", "CONFLICTED", "MANUAL_OVERRIDE", "OD_SINK_ONLY", "OD_SOURCE_ONLY"):
                s = SCORES.get(flag, 0)
                score += s
                active_flags.append(flag)

        # snap signals
        snap_dist = g.get("snap_distance_m", "")
        if snap_dist and snap_dist != "skipped":
            try:
                if float(snap_dist) > 200:
                    score += SCORES["SNAP_FAR"]
                    active_flags.append("SNAP_FAR")
            except ValueError:
                pass
        if g.get("snap_toll") == "0" and g.get("snap_error") == "":
            score += SCORES["SNAP_NOT_TOLL"]
            active_flags.append("SNAP_NOT_TOLL")

        # overpass
        if g.get("osm_no_toll_infra") == "1":
            score += SCORES["OSM_NO_TOLL_INFRA"]
            active_flags.append("OSM_NO_TOLL_INFRA")

        # google
        if g.get("google_place_found") == "0" and g.get("google_error") in ("", None):
            score += SCORES["GOOGLE_NO_MATCH"]
            active_flags.append("GOOGLE_NO_MATCH")

        # classification
        if score >= 4:
            verdict = "LIKELY_INVALID"
        elif score >= 2:
            verdict = "UNCERTAIN"
        else:
            verdict = "LIKELY_VALID"

        # duplicate coord is a flag only, not scored
        is_dup = g.get("is_duplicate_coord", "0") == "1"
        if is_dup:
            active_flags.append("DUPLICATE_COORD")

        rows_out.append({
            "gare_id": g["gare_id"],
            "canonical_name": g.get("canonical_name", ""),
            "operators": g.get("operators", ""),
            "match_tier": g.get("match_tier", ""),
            "lat": g.get("lat", ""),
            "lon": g.get("lon", ""),
            "score": score,
            "verdict": verdict,
            "flags": "|".join(active_flags),
        })

    rows_out.sort(key=lambda r: -r["score"])

    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "gate_scores.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    suspects = [r for r in rows_out if r["verdict"] == "LIKELY_INVALID"]
    with open(out_dir / "suspect_gate_candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(suspects)

    _write_html(rows_out, out_dir / "report.html")

    print(f"Phase 6: {len(rows_out)} gates scored")
    print(f"  LIKELY_INVALID : {len(suspects)}")
    print(f"  UNCERTAIN      : {sum(1 for r in rows_out if r['verdict'] == 'UNCERTAIN')}")
    print(f"  LIKELY_VALID   : {sum(1 for r in rows_out if r['verdict'] == 'LIKELY_VALID')}")
    return rows_out


def _write_html(rows: list[dict], path: Path) -> None:
    COLOURS = {"LIKELY_INVALID": "#fca5a5", "UNCERTAIN": "#fde68a", "LIKELY_VALID": "#bbf7d0"}
    html_rows = ""
    for r in rows:
        bg = COLOURS.get(r["verdict"], "")
        style = f' style="background:{bg}"' if bg else ""
        html_rows += (
            f'<tr{style}>'
            f'<td>{r["gare_id"]}</td>'
            f'<td>{r["canonical_name"]}</td>'
            f'<td>{r["operators"]}</td>'
            f'<td>{r["match_tier"]}</td>'
            f'<td>{r["score"]}</td>'
            f'<td>{r["verdict"]}</td>'
            f'<td style="font-size:0.8em">{r["flags"].replace("|","<br>")}</td>'
            f'</tr>\n'
        )

    total = len(rows)
    invalid_n = sum(1 for r in rows if r["verdict"] == "LIKELY_INVALID")
    uncertain_n = sum(1 for r in rows if r["verdict"] == "UNCERTAIN")
    valid_n = total - invalid_n - uncertain_n

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Gate Validation Report</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9em; }}
th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; }}
th {{ background: #e5e7eb; }}
.summary {{ display: flex; gap: 2em; margin-bottom: 1.5em; }}
.stat {{ background: #f3f4f6; padding: 1em 2em; border-radius: 6px; }}
</style>
</head>
<body>
<h1>Gate Validation Report</h1>
<div class="summary">
  <div class="stat"><strong>{total}</strong><br>Total gates</div>
  <div class="stat" style="background:#fca5a5"><strong>{invalid_n}</strong><br>Likely invalid</div>
  <div class="stat" style="background:#fde68a"><strong>{uncertain_n}</strong><br>Uncertain</div>
  <div class="stat" style="background:#bbf7d0"><strong>{valid_n}</strong><br>Likely valid</div>
</div>
<table>
<thead>
<tr><th>ID</th><th>Name</th><th>Operators</th><th>Tier</th><th>Score</th><th>Verdict</th><th>Flags</th></tr>
</thead>
<tbody>
{html_rows}
</tbody>
</table>
</body>
</html>"""
    path.write_text(html)
    print(f"  report: {path}")
