"""Terrain textures for the 1-35 km context ring (no geometry overlaps: roads are painted, not modelled).

Per 5 km terrain tile: Sentinel-2 summer true colour (10 m, Copernicus open licence) resampled to the
tile, with OSM roads / railways / water painted on top at the right widths.
 - tiles within ~12 km of the site: 2.5 m/px (2048 px); further out: 10 m/px (512 px)
Output: textures/terrain/T_Terrain_<ix>_<iy>.png  (UV = (x - x0)/5000, (y - y0)/5000)
Runs with plain python (numpy + Pillow), no bpy.
"""
import os, sys, json, math, time
import numpy as np
ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "pylibs")):
    if p not in sys.path:
        sys.path.append(p)
from PIL import Image, ImageDraw
import geo

TILE = 5000.0
R = geo.RADIUS
S2 = os.environ.get("BISHKEK_S2", os.path.join(ROOT, "data", "s2_20260716_crop.npz"))
OUT = os.path.join(ROOT, "textures", "terrain")
os.makedirs(OUT, exist_ok=True)
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


ROAD_W = {"motorway": 22, "trunk": 20, "primary": 15, "secondary": 14, "tertiary": 8, "unclassified": 6,
          "residential": 5.5, "living_street": 4.5, "road": 6, "service": 4, "busway": 7, "track": 3.5,
          "motorway_link": 6, "trunk_link": 6, "primary_link": 6, "secondary_link": 6, "tertiary_link": 6,
          "pedestrian": 4, "footway": 1.8, "cycleway": 2, "path": 1.2, "steps": 2}
ROAD_COL = {"track": (128, 112, 86), "path": (150, 138, 118), "footway": (150, 145, 138), "pedestrian": (150, 145, 138),
            "steps": (150, 145, 138), "cycleway": (95, 60, 55)}
ASPHALT = (58, 58, 60)


def num(v):
    import re
    if v is None:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


def load_s2():
    z = np.load(S2)
    tci = z["TCI"]
    E_ul, N_ul, px = [float(v) for v in z["TCI_geo"]]
    return tci, E_ul, N_ul, px


def sample_rgb(tci, E_ul, N_ul, px, X, Y):
    """Bilinear sample of the S2 true-colour grid at local coords X, Y (arrays)."""
    E = geo.E0 + X * geo.KS; N = geo.N0 + Y * geo.KS
    fc = (E - E_ul) / px - 0.5; fr = (N_ul - N) / px - 0.5
    h, w = tci.shape[:2]
    c0 = np.clip(np.floor(fc).astype(np.int64), 0, w - 2); r0 = np.clip(np.floor(fr).astype(np.int64), 0, h - 2)
    tx = np.clip(fc - c0, 0, 1)[..., None]; ty = np.clip(fr - r0, 0, 1)[..., None]
    a = tci.astype(np.float32)
    v = (a[r0, c0] * (1 - tx) * (1 - ty) + a[r0, c0 + 1] * tx * (1 - ty) + a[r0 + 1, c0] * (1 - tx) * ty + a[r0 + 1, c0 + 1] * tx * ty)
    return v


def grade(rgb):
    """S2 TCI is dark and hazy: lift levels, gentle gamma, slight desaturation of the haze."""
    x = np.clip(rgb / 255.0, 0, 1)
    x = np.clip((x - 0.03) / 0.80, 0, 1) ** 0.95
    lum = x.mean(-1, keepdims=True)
    x = lum + (x - lum) * 1.20
    return np.clip(x * 255, 0, 255).astype(np.uint8)


def main():
    tci, E_ul, N_ul, px = load_s2()
    ex = os.path.join(ROOT, "data", "osm", "extract")
    H = json.load(open(os.path.join(ex, "highways.json"), encoding="utf-8"))
    LN = json.load(open(os.path.join(ex, "lines.json"), encoding="utf-8"))
    AR = json.load(open(os.path.join(ex, "areas.json"), encoding="utf-8"))
    # project once
    roads = []
    for h in H:
        c = h["tags"].get("highway")
        if c not in ROAD_W or h["tags"].get("tunnel") == "yes":
            continue
        a = np.asarray(h["pts"]); x, y = geo.to_local(a[:, 0], a[:, 1])
        w = num(h["tags"].get("width")) or (num(h["tags"].get("lanes")) or 0) * 3.5 or ROAD_W[c]
        roads.append((c, max(w, ROAD_W[c] if c in ("primary", "secondary", "trunk") else 0), np.stack([x, y], 1)))
    rails, water_l = [], []
    for l in LN:
        t = l["tags"]; a = np.asarray(l["pts"]); x, y = geo.to_local(a[:, 0], a[:, 1]); xy = np.stack([x, y], 1)
        if t.get("railway") in ("rail", "tram", "light_rail", "narrow_gauge"):
            rails.append(xy)
        elif t.get("waterway") in ("river", "canal", "stream"):
            water_l.append((xy, num(t.get("width")) or {"river": 25, "canal": 10, "stream": 4}[t["waterway"]]))
    water_a = []
    for a_ in AR:
        t = a_["tags"]
        if t.get("natural") == "water" or t.get("waterway") == "riverbank" or t.get("landuse") in ("reservoir", "basin"):
            for pd in a_["polys"]:
                a = np.asarray(pd["outer"]); x, y = geo.to_local(a[:, 0], a[:, 1]); water_a.append(np.stack([x, y], 1))
    log("vectors", len(roads), len(rails), len(water_l), len(water_a))
    n = int(math.ceil(R / TILE))
    meta = {}
    for ix in range(-n, n):
        for iy in range(-n, n):
            x0, y0 = ix * TILE, iy * TILE
            if os.environ.get("ONLY_TILE") and os.environ["ONLY_TILE"] != f"{ix},{iy}":
                continue
            nx = min(max(0.0, x0), x0 + TILE); ny = min(max(0.0, y0), y0 + TILE)
            if math.hypot(nx, ny) > R:
                continue
            fine = math.hypot(x0 + TILE / 2, y0 + TILE / 2) - TILE * 0.71 < 12000
            res = 2.5 if fine else 10.0
            size = int(TILE / res)
            ss = 2 if fine else 1  # supersample vector overlay
            # base image
            c = (np.arange(size) + 0.5) * res
            X, Y = np.meshgrid(x0 + c, y0 + TILE - c)  # row 0 = north edge
            img = grade(sample_rgb(tci, E_ul, N_ul, px, X, Y))
            base = Image.fromarray(img, "RGB")
            if ss > 1:
                base = base.resize((size * ss, size * ss), Image.BICUBIC)
            dr = ImageDraw.Draw(base)
            k = ss / res

            def to_px(xy):
                return [(float((p[0] - x0) * k), float((y0 + TILE - p[1]) * k)) for p in xy]

            bb = (x0 - 50, y0 - 50, x0 + TILE + 50, y0 + TILE + 50)

            def inside(xy):
                return not (xy[:, 0].max() < bb[0] or xy[:, 0].min() > bb[2] or xy[:, 1].max() < bb[1] or xy[:, 1].min() > bb[3])

            for xy in water_a:
                if inside(xy) and len(xy) > 2:
                    dr.polygon(to_px(xy), fill=(38, 58, 66))
            for xy, w in water_l:
                if inside(xy):
                    dr.line(to_px(xy), fill=(38, 58, 66), width=max(1, int(round(w * k))), joint="curve")
            order = sorted(roads, key=lambda r: ROAD_W[r[0]])
            for cls, w, xy in order:
                if not inside(xy):
                    continue
                wp = max(1, int(round(w * k)))
                col = ROAD_COL.get(cls, ASPHALT)
                if cls not in ROAD_COL and wp >= 3:
                    dr.line(to_px(xy), fill=(150, 148, 142), width=wp + max(2, int(round(2.5 * k))), joint="curve")  # kerb/sidewalk rim
                dr.line(to_px(xy), fill=col, width=wp, joint="curve")
            for xy in rails:
                if inside(xy):
                    dr.line(to_px(xy), fill=(92, 80, 70), width=max(1, int(round(3.5 * k))), joint="curve")
            if ss > 1:
                base = base.resize((size, size), Image.LANCZOS)
            name = f"T_Terrain_{ix:+03d}_{iy:+03d}.png"
            base.save(os.path.join(OUT, name), optimize=False, compress_level=6)
            meta[f"{ix},{iy}"] = {"file": name, "res_m": res, "x0": x0, "y0": y0}
    json.dump(meta, open(os.path.join(OUT, "tiles.json"), "w"), indent=1)
    log("TEXTURES DONE", len(meta))


if __name__ == "__main__":
    main()
