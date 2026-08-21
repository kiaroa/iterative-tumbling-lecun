"""Benchmark the sub-route search tree against the existing overlay-graph engine.

Runs `tollroute.pareto.pareto_sweep` (single-step, fixed VoT) over the same 25 OD pairs and
the same VoT values as `explore.py`, then compares generalised cost. Cost is recomputed from
toll and duration only, so both sides are measured on the same metric (the engine's own
generalised cost also charges running cost per km, which the tree never modelled).

Run: venv/bin/python3 analysis/subroute_search/compare_engine.py
"""

from __future__ import annotations

import csv
import sqlite3
import statistics as st
import sys
import time
from pathlib import Path

import httpx

from analysis.subroute_search.explore import DB, OSRM, VOTS, sample_pairs
from tollroute import graph as graph_mod
from tollroute import routing
from tollroute.cost import load_class_config
from tollroute.pareto import pareto_sweep

OUT = Path("analysis/subroute_search/engine_vs_tree.csv")
VEHICLE_CLASS = 1


def main():
    conn = sqlite3.connect(DB)
    cfg = load_class_config(conn)
    tree = {}
    for r in csv.DictReader(open("analysis/subroute_search/results.csv")):
        tree[(r["pair"], float(r["vot"]))] = r

    rows = []
    with httpx.Client(base_url=OSRM, timeout=60.0) as client:
        for n, (a, b, _) in enumerate(sample_pairs(), 1):
            pair = f"{a[0]}->{b[0]}"
            t0 = time.time()
            # rebuilt per pair: add_access_edges mutates the graph with per-query nodes
            g = graph_mod.build_graph(conn)
            o_node, d_node = graph_mod.add_access_edges(g, client, (a[1], a[2]), (b[1], b[2]))
            build_s = time.time() - t0

            for vot in VOTS:
                t1 = time.time()
                sweep = pareto_sweep(g, o_node, d_node, VEHICLE_CLASS, cfg,
                                     vot_min=vot, vot_max=vot, steps=1)
                solve_s = time.time() - t1
                if not sweep:
                    continue
                best = min(sweep, key=lambda x: x.route.toll_eur + vot * x.route.duration_s / 3600)
                eng_eur = best.route.toll_eur
                eng_s = best.route.duration_s
                eng_g = eng_eur + vot * eng_s / 3600.0
                t = tree.get((pair, vot))
                if t is None:
                    continue
                rows.append({
                    "pair": pair, "vot": vot,
                    "engine_eur": round(eng_eur, 2), "engine_min": round(eng_s / 60, 1),
                    "engine_G": round(eng_g, 2),
                    "tree_eur": t["tree_eur"], "tree_min": t["tree_min"],
                    "tree_G": t["tree_G"], "tree_kind": t["tree_kind"],
                    "fastest_unpriced": t["fastest_unpriced"],
                    "engine_minus_tree_G": round(eng_g - float(t["tree_G"]), 2),
                    "engine_solve_s": round(solve_s, 2),
                })
            print(f"[{n}] {pair} build {build_s:.1f}s", file=sys.stderr)

    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    summarise(rows)


def summarise(rows):
    print("\n=== ENGINE vs TREE (generalised cost, lower is better) ===")
    ok = [r for r in rows if r["fastest_unpriced"] == "0"]
    print(f"comparable results: {len(ok)} of {len(rows)}")
    print(f"{'VoT':>5} {'engine wins':>12} {'tree wins':>10} {'tie':>5} {'med diff G':>11} {'med engine EUR':>15} {'med tree EUR':>13}")
    for vot in VOTS:
        rs = [r for r in ok if r["vot"] == vot]
        if not rs:
            continue
        ew = sum(1 for r in rs if r["engine_minus_tree_G"] < -0.01)
        tw = sum(1 for r in rs if r["engine_minus_tree_G"] > 0.01)
        print(f"{vot:>5} {ew:>12} {tw:>10} {len(rs)-ew-tw:>5} "
              f"{st.median([r['engine_minus_tree_G'] for r in rs]):>11.2f} "
              f"{st.median([r['engine_eur'] for r in rs]):>15.2f} "
              f"{st.median([float(r['tree_eur']) for r in rs]):>13.2f}")
    print(f"\nmedian engine solve time: {st.median([r['engine_solve_s'] for r in rows]):.2f}s")


if __name__ == "__main__":
    main()
