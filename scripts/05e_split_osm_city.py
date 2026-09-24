"""Stage 05e - split the OSM extract into one small file per 1 km city tile (plain python).

The city run builds every 1x1 km tile with the same partition script as the 1 km zone (06 with BISHKEK_TILE=I,J).
Loading the whole 80 MB extract in each of ~250 tile processes is slow and memory hungry, so this writes
data/city/osm/T_I_J.json with only the features whose bounding box reaches the tile square + PAD metres.
Tile list: data/city/tile_list.json ([[I, J], ...], tile centre = (I*1000, J*1000) local metres).
"""
import os, sys, json, time
import numpy as np
ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "pylibs")):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)
import geo

TS = 1000.0
PAD = 260.0          # >= partition MARGIN (150) + S2 margin (60) + slack
NAMES = ("buildings", "highways", "lines", "areas", "nodes", "highway_areas", "building_parts")


def bbox_ll(f):
    if "pts" in f:
        a = np.asarray(f["pts"], float)
    elif "p" in f:
        a = np.asarray([f["p"]], float)
    else:
        a = np.concatenate([np.asarray(pd["outer"], float) for pd in f["polys"] if len(pd["outer"])])
    x, y = geo.to_local(a[:, 0], a[:, 1])
    return float(x.min()), float(y.min()), float(x.max()), float(y.max())


def main():
    t0 = time.time()
    tl = json.load(open(os.path.join(ROOT, "data", "city", "tile_list.json")))
    tiles = {(int(i), int(j)) for i, j in tl}
    out = {t: {n: [] for n in NAMES} for t in tiles}
    ex = os.path.join(ROOT, "data", "osm", "extract")
    for n in NAMES:
        p = os.path.join(ex, n + ".json")
        if not os.path.exists(p):
            continue
        D = json.load(open(p, encoding="utf-8"))
        k = 0
        for f in D:
            try:
                x0, y0, x1, y1 = bbox_ll(f)
            except Exception:
                continue
            i0 = int(np.floor((x0 - PAD + TS / 2) / TS)); i1 = int(np.floor((x1 + PAD + TS / 2) / TS))
            j0 = int(np.floor((y0 - PAD + TS / 2) / TS)); j1 = int(np.floor((y1 + PAD + TS / 2) / TS))
            if (i1 - i0 + 1) * (j1 - j0 + 1) > 4000:
                continue   # a huge polygon (admin boundary, etc.)
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    if (i, j) in tiles:
                        out[(i, j)][n].append(f); k += 1
        print(n, len(D), "features ->", k, "tile entries", round(time.time() - t0, 1), "s", flush=True)
    od = os.path.join(ROOT, "data", "city", "osm")
    os.makedirs(od, exist_ok=True)
    for (i, j), D in out.items():
        json.dump(D, open(os.path.join(od, f"T_{i}_{j}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("SPLIT DONE", len(out), "tiles", round(time.time() - t0, 1), "s", flush=True)


if __name__ == "__main__":
    main()
