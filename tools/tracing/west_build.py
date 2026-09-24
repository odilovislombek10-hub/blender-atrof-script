"""agent-west: assemble data/tiles/T_i_j.json from per-view pixel traces in data/tiles_src/T_i_j/*.json
View file: {"ll":[lon,lat],"z":19,"feats":[
   ["fence",[[sx,sy],...]], ["alley",[[sx,sy],...],width,surface], ["footpath",[[sx,sy],...],width,surface],
   ["area",surface,use,[[sx,sy],...]], ["bmiss",[[sx,sy],...],levels], ["bgone",[sx,sy]],
   ["L", <feature dict in local metres>] ]}
usage: west_build.py I J [source] [notes] [complete]
"""
import sys, os, json, glob
HERE = os.path.dirname(os.path.abspath(__file__)); DEV = os.path.dirname(HERE)
sys.path.insert(0, HERE); os.chdir(DEV)
import scr2local

i, j = int(sys.argv[1]), int(sys.argv[2])
src = sys.argv[3] if len(sys.argv) > 3 else "Yandex z18/z19"
notes = sys.argv[4] if len(sys.argv) > 4 else ""
complete = (sys.argv[5].lower() == "true") if len(sys.argv) > 5 else False
feats = []
r2 = lambda p: [round(p[0], 2), round(p[1], 2)]
for fn in sorted(glob.glob(f"data/tiles_src/T_{i}_{j}/*.json")):
    V = json.load(open(fn))
    s2l, _ = scr2local.make(V["ll"][0], V["ll"][1], V["z"])
    cv = lambda pts: [r2(s2l(*p)) for p in pts]
    for f in V["feats"]:
        t = f[0]
        if t == "fence":
            feats.append({"type": "fence", "line": cv(f[1])})
        elif t in ("alley", "footpath"):
            feats.append({"type": t, "line": cv(f[1]), "width": float(f[2]), "surface": f[3]})
        elif t == "area":
            feats.append({"type": "area", "surface": f[1], "use": f[2], "poly": cv(f[3])})
        elif t == "bmiss":
            feats.append({"type": "building_missing", "poly": cv(f[1]), "levels": f[2]})
        elif t == "bgone":
            feats.append({"type": "building_gone", "at": r2(s2l(*f[1]))})
        elif t == "L":
            feats.append(f[1])
        else:
            raise SystemExit("bad feature " + t)
out = {"tile": [i, j], "bounds": [300 * i - 150, 300 * j - 150, 300 * i + 150, 300 * j + 150], "source": src,
       "traced_by": "agent-west", "complete": complete, "features": feats, "notes": notes}
os.makedirs("data/tiles", exist_ok=True)
json.dump(out, open(f"data/tiles/T_{i}_{j}.json", "w"), indent=1)
from collections import Counter
print(f"T_{i}_{j}:", dict(Counter(f["type"] for f in feats)))
