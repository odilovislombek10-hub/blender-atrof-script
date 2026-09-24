"""query model: west_q.py x,y [x,y ...] -> partition class at point + nearest footprint distance"""
import sys, os, json, pickle
HERE = os.path.dirname(os.path.abspath(__file__)); DEV = os.path.dirname(HERE)
sys.path.insert(0, HERE); os.chdir(DEV)
import numpy as np
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree
z = np.load("data/zone_partition.npz", allow_pickle=True)
V, T, TC = z["V"][:, :2], z["T"], z["TC"]
names = {int(c[0]): c[1] for c in json.loads(str(z["classes"]))}
fp = [Polygon(f["outer"]) for f in json.load(open("data/zone_footprints_local.json"))]
tree = STRtree(fp)
cent = V[T].mean(axis=1)
def cls(x, y):
    d = np.hypot(cent[:, 0] - x, cent[:, 1] - y); idx = np.argsort(d)[:30]
    for i in idx:
        tri = V[T[i]]
        if Polygon(tri).buffer(1e-6).contains(Point(x, y)):
            return names.get(int(TC[i]), TC[i])
    return "?"
for a in sys.argv[1:]:
    x, y = map(float, a.split(","))
    p = Point(x, y); j = tree.nearest(p); d = fp[j].distance(p)
    print(a, cls(x, y), "fp_dist=%.1f" % d, "fp_area=%.0f" % fp[j].area)
