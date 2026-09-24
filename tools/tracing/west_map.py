"""render model partition for a tile: west_map.py I J OUT.png [tile.json overlay]"""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__)); DEV = os.path.dirname(HERE)
sys.path.insert(0, HERE); os.chdir(DEV)
import numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from shapely.geometry import Polygon
i, j = int(sys.argv[1]), int(sys.argv[2]); out = sys.argv[3]
x0, y0 = 300 * i - 150, 300 * j - 150
z = np.load("data/zone_partition.npz", allow_pickle=True)
V, T, TC = z["V"][:, :2], z["T"], z["TC"]
C = {2: "#555555", 1: "#777777", 3: "#999999", 4: "#e0c060", 5: "#3060ff", 6: "#ffaa66", 8: "#aa33aa", 20: "#cc55cc", 10: "#ff2020", 11: "#ff8800",
     12: "#66bb66", 13: "#22dd22", 14: "#228822", 15: "#b0a090", 16: "#f0e0c0", 17: "#8b6b4b", 18: "#c89060", 21: "#c080ff", 22: "#dddddd", 23: "#b080e0",
     9: "#0000ff", 24: "#0000aa", 25: "#557755", 7: "#ff00ff", 19: "#ffffff"}
cen = V[T].mean(axis=1)
m = (cen[:, 0] > x0 - 20) & (cen[:, 0] < x0 + 320) & (cen[:, 1] > y0 - 20) & (cen[:, 1] < y0 + 320)
fig, ax = plt.subplots(figsize=(12, 12), dpi=80)
ax.add_collection(PolyCollection(V[T[m]], facecolors=[C.get(int(c), "#000") for c in TC[m]], edgecolors="none"))
fp = json.load(open("data/zone_footprints_local.json"))
for f in fp:
    p = np.array(f["outer"])
    if (p[:, 0].max() > x0 - 20) and (p[:, 0].min() < x0 + 320) and (p[:, 1].max() > y0 - 20) and (p[:, 1].min() < y0 + 320):
        ax.fill(p[:, 0], p[:, 1], fc="#00000040", ec="cyan", lw=0.8)
if len(sys.argv) > 4:
    D = json.load(open(sys.argv[4]))
    for f in D["features"]:
        t = f["type"]
        if t in ("fence", "alley", "footpath"):
            p = np.array(f["line"]); ax.plot(p[:, 0], p[:, 1], {"fence": "r-", "alley": "m-", "footpath": "k-"}[t], lw={"fence": 1, "alley": 3, "footpath": 1.5}[t])
        elif t in ("area", "building_missing"):
            p = np.array(f["poly"] + [f["poly"][0]]); ax.plot(p[:, 0], p[:, 1], "b-" if t == "area" else "w--", lw=1.5)
        elif t == "building_gone":
            ax.plot(*f["at"], "rx", ms=10)
ax.set_xlim(x0, x0 + 300); ax.set_ylim(y0, y0 + 300); ax.set_aspect("equal")
ax.set_xticks(range(x0, x0 + 301, 25)); ax.set_yticks(range(y0, y0 + 301, 25)); ax.grid(True, lw=0.3, color="k"); ax.tick_params(labelsize=7)
plt.tight_layout(); plt.savefig(out)
