"""Stage 13 - QA gate + run report (plain python).
Reads data/qa_geometry.json, compares issue counts with the gates below, writes logs/LAST_RUN.json and
logs/RUN_<date>.json and prints a short table. Exit code 1 if a gate fails (the .bat marks the run FAILED).
"""
import os, sys, json, time

ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
_CT = os.environ.get("BISHKEK_TILE")   # city mode: per-tile data dir data/city/T_I_J
DATADIR = os.path.join(ROOT, "data", "city", "T_%s_%s" % tuple(_CT.split(","))) if _CT else os.path.join(ROOT, "data")
GATES = {  # issue type -> max allowed
    "hole": 0,
    "open_chain_long": 0,
    "terrain_seam_uncovered": 0,
    "overlap_zfight": 0,
    "tree_on_hard": 0,
    "tree_in_building": 0,
    "building_overlap": 0,
    "building_on_road": 0,
    "building_floating": 10,
    "nonmanifold_edge": 30,
    "sliver": 100,
    "road_fragment": 10,
    # SHEF review points (12b_qa_rules.py)
    "path_dead_end": 5,
    "house_without_wall": 150,
    "marking_gap_main": 3,
    "wall_on_street": 0,
}


def main():
    q = json.load(open(os.path.join(DATADIR, "qa_geometry.json")))
    counts = dict(q.get("summary") or q.get("issue_counts", {}))
    gb = q.get("ground_boundary", {}); ts = q.get("terrain_seam", {})
    counts["hole"] = int(gb.get("holes", counts.get("hole", 0)))
    counts["open_chain_long"] = int(gb.get("open_chains_long", 0))
    counts["nonmanifold_edge"] = int(gb.get("nonmanifold_edges", counts.get("nonmanifold_edge", 0)))
    counts["terrain_seam_uncovered"] = int(ts.get("uncovered_samples", 0))
    rp_ = os.path.join(DATADIR, "qa_rules.json")
    qg_ = os.path.join(DATADIR, "qa_geometry.json")
    if not os.path.exists(rp_) or os.path.getmtime(rp_) < os.path.getmtime(qg_) - 600:
        counts["qa_rules_missing"] = 1   # 12b did not run on this build -> the run cannot pass
        GATES["qa_rules_missing"] = 0
    if os.path.exists(rp_):
        for k, v in json.load(open(rp_)).get("summary", {}).items():
            counts[k] = int(v)
    verdict = {}
    ok = True
    for k, mx in GATES.items():
        n = int(counts.get(k, 0))
        verdict[k] = {"count": n, "max": mx, "ok": n <= mx}
        ok &= n <= mx
    prev = None
    lp = os.path.join(DATADIR if _CT else os.path.join(ROOT, "logs"), "LAST_RUN.json")
    if os.path.exists(lp):
        try:
            prev = json.load(open(lp)).get("issue_counts")
        except Exception:
            prev = None
    rep = {"when": time.strftime("%Y-%m-%d %H:%M"), "ok": ok, "gates": verdict, "issue_counts": counts,
           "previous_counts": prev, "ground_objects": q.get("objects", {})}
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    json.dump(rep, open(lp, "w"), indent=1)
    if not _CT:
        json.dump(rep, open(os.path.join(ROOT, "logs", time.strftime("RUN_%Y%m%d_%H%M.json")), "w"), indent=1)
    print(f"{'issue':28s} {'now':>7s} {'before':>7s}  gate")
    for k in sorted(set(counts) | set(GATES)):
        g = GATES.get(k)
        before = "" if not prev else str(prev.get(k, 0))
        mark = "" if g is None else ("OK" if counts.get(k, 0) <= g else f"FAIL (max {g})")
        print(f"{k:28s} {counts.get(k, 0):7d} {before:>7s}  {mark}")
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
