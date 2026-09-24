"""Stage 16 - city-wide QA report after the tile run (plain python).

Collects for every finished tile (data/city/T_I_J):
  - the QA gates (LAST_RUN.json from 13) and the geometric / rule issue counts
  - SHEF landscape check: in apartment-block yards (30 m around blocks of >= 350 m2, minus buildings) the share of
    green ground in the model (Lawn, Trees_Ground, Street_Green) against the share that is really green on the
    Sentinel-2 September scene (NDVI > 0.30, 10 m pixels) -> yard_green_excess (percentage points).
    Large excess = yards modelled green where the satellite sees asphalt / paving / parking / bare ground.
  - parking and playground area in those yards
Writes data/city/city_report.json and logs/CITY_REPORT.md (worst tiles first).
"""
import os, sys, json, math, glob, time
import numpy as np
ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "pylibs")):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)
import shapely
from shapely.geometry import Polygon
from shapely.ops import unary_union
import geo

GREEN = ("Lawn", "Trees_Ground", "Street_Green")
HARDY = ("Yard_Hard", "Parking_Asphalt", "Forecourt_Paving", "Entrance_Paving", "Path_Paving", "Apron_Concrete",
         "Playground", "Sport_Pitch", "Asphalt_Road", "Sidewalk_Paving", "Dirt_Track", "Bare_Soil")


def s2_loader():
    p = os.path.join(ROOT, "data", "s2_city.npz")
    if not os.path.exists(p):
        return None
    z = np.load(p)
    E_ul, N_ul, px = [float(v) for v in z["geo"]]
    b4 = z["20260914_B04"].astype(np.float32); b8 = z["20260914_B08"].astype(np.float32)
    nd = (b8 - b4) / (b8 + b4 + 1e-6)

    def green_share(poly):
        """fraction of 10 m pixels (centres inside poly) with September NDVI > 0.30"""
        if poly.is_empty:
            return None, 0
        x0, y0, x1, y1 = poly.bounds
        E0 = geo.E0 + x0 * geo.KS; E1 = geo.E0 + x1 * geo.KS
        N0 = geo.N0 + y0 * geo.KS; N1 = geo.N0 + y1 * geo.KS
        c0 = max(0, int((E0 - E_ul) / px)); c1 = min(nd.shape[1], int((E1 - E_ul) / px) + 1)
        r0 = max(0, int((N_ul - N1) / px)); r1 = min(nd.shape[0], int((N_ul - N0) / px) + 1)
        if c1 <= c0 or r1 <= r0:
            return None, 0
        cc, rr = np.meshgrid(np.arange(c0, c1), np.arange(r0, r1))
        E = E_ul + (cc + 0.5) * px; N = N_ul - (rr + 0.5) * px
        x = (E - geo.E0) / geo.KS; y = (N - geo.N0) / geo.KS
        inside = shapely.contains_xy(poly, x.ravel(), y.ravel())
        if inside.sum() < 5:
            return None, int(inside.sum())
        v = nd[r0:r1, c0:c1].ravel()[inside]
        return float((v > 0.30).mean()), int(inside.sum())
    return green_share


def tile_metrics(d, green_share):
    z = np.load(os.path.join(d, "zone_partition.npz"), allow_pickle=True)
    V = z["V"][:, :2]; T = z["T"]; TC = z["TC"]
    names = {int(c[0]): c[1] for c in json.loads(str(z["classes"]))}
    P = V[T]
    area = 0.5 * np.abs((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1]) - (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1]))
    cen = P.mean(1)
    cls = np.array([names[int(c)] for c in TC])
    ring = Polygon(np.asarray(json.load(open(os.path.join(d, "zone_ring.json"))), float)[:, :2]).buffer(0)
    fp = json.load(open(os.path.join(d, "zone_footprints_local.json")))
    B = [Polygon(f["outer"]).buffer(0) for f in fp]
    apt = [b for b in B if b.area >= 350]
    m = {"ground_m2": round(float(area.sum())), "buildings": len(B), "apartment_blocks": len(apt)}
    tot = float(area.sum()) or 1.0
    m["green_share_model"] = round(float(area[np.isin(cls, GREEN)].sum()) / tot, 3)
    gs, n = green_share(ring.difference(unary_union(B))) if green_share else (None, 0)
    m["green_share_s2"] = None if gs is None else round(gs, 3)
    if apt:
        yard = unary_union([b.buffer(30) for b in apt]).difference(unary_union(B)).intersection(ring)
        inside = shapely.contains_xy(yard, cen[:, 0], cen[:, 1])
        ya = float(area[inside].sum()) or 1.0
        m["yard_m2"] = round(ya)
        m["yard_green_model"] = round(float(area[inside & np.isin(cls, GREEN)].sum()) / ya, 3)
        m["yard_parking_m2"] = round(float(area[inside & (cls == "Parking_Asphalt")].sum()))
        m["yard_playground_m2"] = round(float(area[inside & (cls == "Playground")].sum()))
        m["yard_hard_share"] = round(float(area[inside & np.isin(cls, HARDY)].sum()) / ya, 3)
        gs, n = green_share(yard) if green_share else (None, 0)
        m["yard_green_s2"] = None if gs is None else round(gs, 3)
        if gs is not None:
            m["yard_green_excess"] = round(100 * (m["yard_green_model"] - gs), 1)
    return m


class TileGround:
    """point lookup on a tile's top ground surface: class name and height"""
    def __init__(self, d):
        from shapely import STRtree
        z = np.load(os.path.join(d, "zone_partition.npz"), allow_pickle=True)
        self.V = z["V"]; self.T = z["T"]; self.names = {int(c[0]): c[1] for c in json.loads(str(z["classes"]))}
        self.TC = z["TC"]
        self.tri = shapely.polygons(self.V[self.T][:, :, :2])
        self.tree = STRtree(self.tri)

    def sample(self, xy):
        pts = shapely.points(xy)
        pi, ti = self.tree.query(pts, predicate="intersects")
        cls = np.full(len(xy), None, object); zz = np.full(len(xy), np.nan)
        for p, t in zip(pi, ti):
            if cls[p] is not None:
                continue
            A, B, C = self.V[self.T[t]]
            n = np.cross(B - A, C - A)
            if abs(n[2]) < 1e-9:
                continue
            x, y = xy[p]
            zz[p] = A[2] - (n[0] * (x - A[0]) + n[1] * (y - A[1])) / n[2]
            cls[p] = self.names[int(self.TC[t])]
        return cls, zz


def seam_checks(done_dirs, step=1.0, eps=0.05):
    """adjacent tiles (and tiles against the 1 km zone) must meet: same surface class and height at the shared edge"""
    cache = {}

    def get(k):
        if k not in cache:
            d = os.path.join(ROOT, "data", "city", k) if k != "ZONE" else os.path.join(ROOT, "data")
            cache[k] = TileGround(d)
            if len(cache) > 12:
                cache.pop(next(iter(cache)))
        return cache[k]
    have = set(done_dirs)
    out = []
    for k in sorted(have):
        i, j = [int(v) for v in k[2:].split("_")]
        for di, dj in ((1, 0), (0, 1)):
            k2 = f"T_{i + di}_{j + dj}"
            if k2 not in have:
                continue
            if di:   # shared vertical edge x = (i + 0.5) * 1000
                x = (i + 0.5) * 1000.0; ys = np.arange((j - 0.5) * 1000 + step / 2, (j + 0.5) * 1000, step)
                a = np.c_[np.full(len(ys), x - eps), ys]; b = np.c_[np.full(len(ys), x + eps), ys]
            else:
                y = (j + 0.5) * 1000.0; xs = np.arange((i - 0.5) * 1000 + step / 2, (i + 0.5) * 1000, step)
                a = np.c_[xs, np.full(len(xs), y - eps)]; b = np.c_[xs, np.full(len(xs), y + eps)]
            ca, za = get(k).sample(a); cb, zb = get(k2).sample(b)
            both = np.array([p is not None and q is not None for p, q in zip(ca, cb)])
            if both.sum() < 10:
                continue
            cm = np.array([p != q for p, q in zip(ca, cb)]) & both
            dz = np.abs(za - zb); dz[~both] = 0
            out.append({"a": k, "b": k2, "samples": int(both.sum()), "class_mismatch_pct": round(100 * cm.sum() / both.sum(), 1),
                        "dz_over_5cm_pct": round(100 * (dz > 0.05).sum() / both.sum(), 1), "dz_max": round(float(np.nanmax(dz)), 2),
                        "gap_pct": round(100 * (1 - both.mean()), 1)})
    # tiles around the 1 km zone: along the zone circle (R = 1000 m)
    RZ = float(os.environ.get("BISHKEK_ZONE_R", "1000"))
    zfile = os.path.join(ROOT, "data", "zone_partition.npz")
    if os.path.exists(zfile):
        th = np.arange(0, 2 * np.pi, step / RZ)
        for k in sorted(have):
            i, j = [int(v) for v in k[2:].split("_")]
            cx, cy = np.cos(th) * RZ, np.sin(th) * RZ
            m = (cx > (i - 0.5) * 1000) & (cx < (i + 0.5) * 1000) & (cy > (j - 0.5) * 1000) & (cy < (j + 0.5) * 1000)
            if m.sum() < 10:
                continue
            a = np.c_[np.cos(th[m]) * (RZ - eps), np.sin(th[m]) * (RZ - eps)]
            b = np.c_[np.cos(th[m]) * (RZ + eps), np.sin(th[m]) * (RZ + eps)]
            ca, za = get("ZONE").sample(a); cb, zb = get(k).sample(b)
            both = np.array([p is not None and q is not None for p, q in zip(ca, cb)])
            if both.sum() < 10:
                continue
            cm = np.array([p != q for p, q in zip(ca, cb)]) & both
            dz = np.abs(za - zb); dz[~both] = 0
            out.append({"a": "ZONE_1km", "b": k, "samples": int(both.sum()), "class_mismatch_pct": round(100 * cm.sum() / both.sum(), 1),
                        "dz_over_5cm_pct": round(100 * (dz > 0.05).sum() / both.sum(), 1), "dz_max": round(float(np.nanmax(dz)), 2),
                        "gap_pct": round(100 * (1 - both.mean()), 1)})
    return out


def main():
    t0 = time.time()
    green_share = s2_loader()
    rows = {}
    for d in sorted(glob.glob(os.path.join(ROOT, "data", "city", "T_*"))):
        if not os.path.exists(os.path.join(d, "DONE")):
            if os.path.isdir(d):
                rows[os.path.basename(d)] = {"status": "not_done"}
            continue
        k = os.path.basename(d)
        st = json.load(open(os.path.join(d, "DONE")))
        r = {"status": st.get("status"), "gates_failed": st.get("gates_failed", {}), "t": st.get("t")}
        c = st.get("counts", {})
        for key in ("hole", "open_chain_long", "overlap_zfight", "building_overlap", "wall_on_street", "house_without_wall",
                    "path_dead_end", "marking_gap_main", "sliver", "nonmanifold_edge", "playground_no_path",
                    "parking_no_access", "path_dead_island"):
            if key in c:
                r[key] = c[key]
        try:
            r.update(tile_metrics(d, green_share))
        except Exception as e:
            r["metrics_error"] = repr(e)
        rows[k] = r
    done = {k: v for k, v in rows.items() if v.get("status") in ("done", "qa_fail")}
    seams = []
    try:
        seams = seam_checks([k for k in done])
    except Exception as e:
        print("seam check failed", e)
    json.dump(rows, open(os.path.join(ROOT, "data", "city", "city_report.json"), "w"), indent=1)
    json.dump(seams, open(os.path.join(ROOT, "data", "city", "city_seams.json"), "w"), indent=1)
    # ---- markdown summary
    L = [f"# City run report  {time.strftime('%Y-%m-%d %H:%M')}", ""]
    by = {}
    for v in rows.values():
        by[v.get("status")] = by.get(v.get("status"), 0) + 1
    L.append("tiles: " + ", ".join(f"{k} {n}" for k, n in sorted(by.items(), key=lambda kv: str(kv[0]))))
    gf = {}
    for v in done.values():
        for g in v.get("gates_failed", {}):
            gf[g] = gf.get(g, 0) + 1
    L.append("QA gates failed (tiles): " + (", ".join(f"{k} {n}" for k, n in sorted(gf.items(), key=lambda kv: -kv[1])) or "none"))
    tot = {}
    for v in done.values():
        for k in ("hole", "open_chain_long", "building_overlap", "wall_on_street", "house_without_wall", "path_dead_end",
                  "marking_gap_main", "playground_no_path", "parking_no_access", "buildings", "apartment_blocks",
                  "yard_parking_m2", "yard_playground_m2", "ground_m2"):
            tot[k] = tot.get(k, 0) + (v.get(k) or 0)
    L.append("totals: " + ", ".join(f"{k} {v}" for k, v in tot.items()))
    ex = [(k, v) for k, v in done.items() if v.get("yard_green_excess") is not None]
    if ex:
        e = np.array([v["yard_green_excess"] for k, v in ex])
        L += ["", f"## Apartment yards: model green share minus Sentinel-2 September green share",
              f"tiles {len(ex)}; mean {e.mean():.1f} pp; median {np.median(e):.1f} pp; tiles with > 20 pp: {int((e > 20).sum())}", "",
              "| tile | yard m2 | model green | S2 green | excess pp | parking m2 | playground m2 |", "|---|---|---|---|---|---|---|"]
        for k, v in sorted(ex, key=lambda kv: -kv[1]["yard_green_excess"])[:25]:
            L.append(f"| {k} | {v['yard_m2']} | {v['yard_green_model']:.0%} | {v['yard_green_s2']:.0%} | {v['yard_green_excess']} | "
                     f"{v['yard_parking_m2']} | {v['yard_playground_m2']} |")
    if seams:
        cm = np.array([q["class_mismatch_pct"] for q in seams]); dzp = np.array([q["dz_over_5cm_pct"] for q in seams])
        L += ["", "## Tile seams (shared 1 km edges: surface class and height must match on both sides)",
              f"edges {len(seams)}; class mismatch mean {cm.mean():.1f} % (max {cm.max():.1f} %); "
              f"height step > 5 cm mean {dzp.mean():.1f} % (max {dzp.max():.1f} %)", ""]
        for q in sorted(seams, key=lambda q: -(q["class_mismatch_pct"] + q["dz_over_5cm_pct"]))[:10]:
            L.append(f"- {q['a']} | {q['b']}: class mismatch {q['class_mismatch_pct']} %, dz>5cm {q['dz_over_5cm_pct']} %, "
                     f"dz max {q['dz_max']} m, gap {q['gap_pct']} %")
    bad = [(k, v) for k, v in rows.items() if v.get("status") in ("failed", "qa_fail")]
    if bad:
        L += ["", "## Tiles with problems", ""]
        for k, v in bad:
            L.append(f"- {k}: {v.get('status')} {v.get('gates_failed', '')}")
    open(os.path.join(ROOT, "logs", "CITY_REPORT.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:12]))
    print("REPORT DONE", len(rows), "tiles", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main()
