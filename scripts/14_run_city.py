"""Stage 14 - whole-city run: every 1x1 km tile through the same pipeline as the 1 km zone, several in parallel.

  per tile (env BISHKEK_TILE=I,J):  06 partition -> 07 Blender (+08 repair) -> 12 geometric QA -> 12b rules -> 13 gates
  outputs : city\\tile_I_J.blend            (one .blend per tile, linked into Bishkek_35km.blend by 15_integrate_city.py)
            data\\city\\T_I_J\\               (partition, footprints, qa_geometry.json, qa_rules.json, LAST_RUN.json, logs)
  status  : logs\\CITY_STATUS.txt (human readable, refreshed after every tile), data\\city\\city_status.json
            last line "CITY ALLDONE" when finished

usage   : python 14_run_city.py [jobs]          (default jobs = BISHKEK_CITY_JOBS or 8)
          env BISHKEK_CITY_FORCE=1 rebuilds tiles that are already done
          env BISHKEK_CITY_RERUN=qa_fail rebuilds only the tiles whose QA gates failed
          env BISHKEK_CITY_ONLY="3,2;4,2" runs only these tiles
"""
import os, sys, json, time, subprocess, threading
from concurrent.futures import ThreadPoolExecutor

ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
PY = os.environ.get("BISHKEK_PY", r"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe")
BL = os.environ.get("BISHKEK_BLENDER", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
S = os.path.join(ROOT, "scripts")
JOBS = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("BISHKEK_CITY_JOBS", "8"))
TIMEOUT = {"06": 3600, "07": 1800, "12": 1800, "12b": 900, "13": 300}
NOWIN = 0x08000000 if os.name == "nt" else 0

try:
    sys.path.append(S)
    from unthrottle import unthrottle as _unthrottle, unthrottle_self
    unthrottle_self()
except Exception:
    def _unthrottle(pid):
        return False
LOCK = threading.Lock()
STATE = {}          # "I,J" -> {"status", "stage", "t", "gates_failed", "counts"}
T0 = time.time()


def tdir(i, j):
    return os.path.join(ROOT, "data", "city", f"T_{i}_{j}")


def write_status(final=False):
    with LOCK:
        st = dict(STATE)
    json.dump(st, open(os.path.join(ROOT, "data", "city", "city_status.json"), "w"), indent=1)
    n = len(st)
    by = {}
    for v in st.values():
        by[v["status"]] = by.get(v["status"], 0) + 1
    lines = [f"CITY RUN  {time.strftime('%H:%M:%S')}  elapsed {int(time.time() - T0) // 60} min  jobs {JOBS}",
             "tiles " + str(n) + "  " + "  ".join(f"{k} {c}" for k, c in sorted(by.items())), ""]
    for k, v in sorted(st.items(), key=lambda kv: kv[1].get("order", 0)):
        if v["status"] in ("running", "failed", "qa_fail"):
            lines.append(f"  T_{k.replace(',', '_'):10s} {v['status']:8s} {v.get('stage', ''):4s} {v.get('msg', '')}")
    if final:
        lines.append("CITY ALLDONE")
    open(os.path.join(ROOT, "logs", "CITY_STATUS.txt"), "w").write("\n".join(lines) + "\n")


def run_tile(item):
    order, (i, j) = item
    key = f"{i},{j}"
    d = tdir(i, j); os.makedirs(d, exist_ok=True)
    blend = os.path.join(ROOT, "city", f"tile_{i}_{j}.blend")
    donef = os.path.join(d, "DONE")
    if os.path.exists(donef) and os.path.exists(blend) and os.environ.get("BISHKEK_CITY_FORCE") != "1":
        prev = json.load(open(donef))
        # BISHKEK_CITY_RERUN=qa_fail re-runs tiles whose QA gates failed (after an automation fix)
        if prev.get("status") not in [v for v in os.environ.get("BISHKEK_CITY_RERUN", "").split(",") if v]:
            with LOCK:
                STATE[key] = dict(prev, order=order)
            return
    env = dict(os.environ, BISHKEK_ROOT=ROOT, BISHKEK_TILE=key, PYTHONIOENCODING="utf-8")
    steps = [("06", [PY, "-u", os.path.join(S, "06_zone_partition.py")]),
             ("07", [BL, "-b", "--factory-startup", "--python-exit-code", "1", "--python", os.path.join(S, "07_zone_blender.py")]),
             ("12", [BL, "-b", blend, "--factory-startup", "--python-exit-code", "1", "--python", os.path.join(S, "12_qa_geometry.py")]),
             ("12b", [PY, "-u", os.path.join(S, "12b_qa_rules.py")]),
             ("13", [PY, "-u", os.path.join(S, "13_qa_report.py")])]
    t0 = time.time()
    with LOCK:
        STATE[key] = {"status": "running", "stage": "06", "order": order}
    for name, cmd in steps:
        with LOCK:
            STATE[key]["stage"] = name
        write_status()
        with open(os.path.join(d, f"log_{name}.txt"), "w", encoding="utf-8", errors="replace") as lf:
            pr = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT, creationflags=NOWIN)
            _unthrottle(pr.pid)     # Windows EcoQoS would keep a windowless job on the efficiency cores (3x slower)
            try:
                rc = pr.wait(timeout=TIMEOUT[name])
            except subprocess.TimeoutExpired:
                pr.kill(); rc = -9
        if rc != 0 and name != "13":
            tail = ""
            try:
                tail = open(os.path.join(d, f"log_{name}.txt"), encoding="utf-8", errors="replace").read()[-300:].replace("\n", " | ")
            except Exception:
                pass
            with LOCK:
                STATE[key].update(status="failed", msg=f"rc={rc} {tail[-160:]}", t=round(time.time() - t0))
            write_status()
            return
    rep = {}
    try:
        rep = json.load(open(os.path.join(d, "LAST_RUN.json")))
    except Exception:
        pass
    failed = {k: v["count"] for k, v in rep.get("gates", {}).items() if not v.get("ok")}
    res = {"status": "done" if not failed else "qa_fail", "stage": "", "t": round(time.time() - t0),
           "gates_failed": failed, "counts": rep.get("issue_counts", {}),
           "msg": " ".join(f"{k}={v}" for k, v in failed.items())}
    json.dump(res, open(donef, "w"), indent=1)
    with LOCK:
        STATE[key] = dict(res, order=order)
    write_status()


def main():
    tl = [tuple(t) for t in json.load(open(os.path.join(ROOT, "data", "city", "tile_list.json")))]
    only = os.environ.get("BISHKEK_CITY_ONLY")
    if only:
        want = {tuple(int(v) for v in s.split(",")) for s in only.split(";") if s.strip()}
        tl = [t for t in tl if t in want]
    os.makedirs(os.path.join(ROOT, "city"), exist_ok=True)
    for o, (i, j) in enumerate(tl):
        STATE[f"{i},{j}"] = {"status": "queued", "stage": "", "order": o}
    write_status()
    with ThreadPoolExecutor(JOBS) as ex:
        list(ex.map(run_tile, list(enumerate(tl))))
    write_status(final=True)


if __name__ == "__main__":
    main()
