import os, sys, json, math, re
from collections import Counter, defaultdict
ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
sys.path.append(os.path.join(ROOT, "scripts")); sys.path.append(os.path.join(ROOT, "pylibs"))
import numpy as np
import geo

ex = os.path.join(ROOT, "data", "osm", "extract")
L = lambda n: json.load(open(os.path.join(ex, n + ".json"), encoding="utf-8"))
RINGS = [0.5, 1, 3, 5, 10, 20, 35]


def num(v):
    if v is None: return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(v)); return float(m.group(0).replace(",", ".")) if m else None


def ring_bucket(d):
    for r in RINGS:
        if d <= r * 1000: return f"<={r}km"
    return ">35km"


S = {}
# ---------------- buildings
B = L("buildings")
bt = Counter(); lv_cov = Counter(); lv_hist = Counter(); ring_cnt = Counter(); ring_lv = Counter()
area_tot = 0.0; near = []
for b in B:
    t = b["tags"]; o = np.asarray(b["polys"][0]["outer"])
    x, y = geo.to_local(o[:, 0], o[:, 1])
    cx, cy = float(x.mean()), float(y.mean()); d = math.hypot(cx, cy)
    if d > 35000: continue
    a = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    area_tot += a
    bt[t.get("building", "yes")] += 1
    lv = num(t.get("building:levels")); h = num(t.get("height"))
    src = "height" if h else ("levels" if lv else "none")
    lv_cov[src] += 1
    rb = ring_bucket(d); ring_cnt[rb] += 1
    if src != "none": ring_lv[rb] += 1
    L_ = lv or (h / 3.0 if h else None)
    if L_:
        k = "1" if L_ < 1.5 else "2" if L_ < 2.5 else "3-5" if L_ < 5.5 else "6-9" if L_ < 9.5 else "10-16" if L_ < 16.5 else "17+"
        lv_hist[k] += 1
    if d <= 300:
        near.append({"d_m": round(d), "dir": round((math.degrees(math.atan2(cx, cy)) + 360) % 360), "type": t.get("building"),
                     "levels": t.get("building:levels"), "height": t.get("height"), "name": t.get("name"),
                     "addr": " ".join(filter(None, [t.get("addr:street"), t.get("addr:housenumber")])), "area_m2": round(a)})
S["buildings"] = {"count": sum(bt.values()), "footprint_km2": round(area_tot / 1e6, 2), "types_top": bt.most_common(15),
                  "height_info": dict(lv_cov), "levels_hist": dict(lv_hist),
                  "by_ring": {k: {"n": ring_cnt[k], "with_levels_or_height": ring_lv[k]} for k in sorted(ring_cnt, key=lambda s: float(s[2:-2]) if s.startswith("<=") else 99)},
                  "near_300m": sorted(near, key=lambda r: r["d_m"])}
# ---------------- highways
H = L("highways")
length = Counter(); lanes_cov = Counter(); width_cov = Counter(); sw_cov = Counter(); surf = Counter(); names_near = {}
cls_all = Counter()
for w in H:
    t = w["tags"]; c = t.get("highway"); p = np.asarray(w["pts"])
    x, y = geo.to_local(p[:, 0], p[:, 1])
    seg = float(np.hypot(np.diff(x), np.diff(y)).sum())
    if min(math.hypot(x[0], y[0]), math.hypot(x[-1], y[-1])) > 35000: continue
    key = c + ("(sidewalk)" if c == "footway" and t.get("footway") == "sidewalk" else "")
    length[key] += seg; cls_all[c] += 1
    if c in ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"):
        lanes_cov["lanes" if "lanes" in t else "no_lanes"] += seg
        width_cov["width" if "width" in t else "no_width"] += seg
        sw = t.get("sidewalk") or t.get("sidewalk:both") or ("lr" if ("sidewalk:left" in t or "sidewalk:right" in t) else None)
        sw_cov[sw or "untagged"] += seg
        surf[t.get("surface", "untagged")] += seg
    dmin = float(np.min(np.hypot(x, y)))
    if dmin <= 500 and t.get("name"):
        n = t["name"]
        r = names_near.setdefault(n, {"class": c, "min_dist_m": round(dmin), "lanes": t.get("lanes"), "width": t.get("width"),
                                      "oneway": t.get("oneway"), "sidewalk": t.get("sidewalk"), "surface": t.get("surface"), "maxspeed": t.get("maxspeed")})
        r["min_dist_m"] = min(r["min_dist_m"], round(dmin))
S["highways"] = {"ways": sum(cls_all.values()), "length_km": {k: round(v / 1000, 1) for k, v in length.most_common()},
                 "main_roads_lanes_tag_km": {k: round(v / 1000, 1) for k, v in lanes_cov.items()},
                 "main_roads_width_tag_km": {k: round(v / 1000, 1) for k, v in width_cov.items()},
                 "main_roads_sidewalk_tag_km": {k: round(v / 1000, 1) for k, v in sw_cov.most_common(8)},
                 "main_roads_surface_km": {k: round(v / 1000, 1) for k, v in surf.most_common(8)},
                 "named_streets_within_500m": dict(sorted(names_near.items(), key=lambda kv: kv[1]["min_dist_m"]))}
# ---------------- lines
LN = L("lines"); lk = Counter(); wnames = Counter()
for w in LN:
    t = w["tags"]; p = np.asarray(w["pts"]); x, y = geo.to_local(p[:, 0], p[:, 1])
    seg = float(np.hypot(np.diff(x), np.diff(y)).sum())
    k = ("railway=" + t["railway"]) if "railway" in t else ("waterway=" + t["waterway"]) if "waterway" in t else ("barrier=" + t["barrier"]) if "barrier" in t else ("power=" + t["power"]) if "power" in t else "other"
    lk[k] += seg
    if "waterway" in t and t.get("name"): wnames[t["name"] + f" ({t['waterway']})"] += seg
S["lines_km"] = {k: round(v / 1000, 1) for k, v in lk.most_common(20)}
S["waterways_named_km"] = {k: round(v / 1000, 1) for k, v in wnames.most_common(15)}
# ---------------- areas & nodes
A = L("areas"); ak = Counter()
for a in A:
    t = a["tags"]
    for k in ("landuse", "leisure", "natural", "amenity", "water", "aeroway"):
        if k in t: ak[f"{k}={t[k]}"] += 1; break
S["areas_top"] = ak.most_common(25)
S["nodes"] = Counter(n["t"] for n in L("nodes"))
# ---------------- DEM
z = np.load(os.path.join(ROOT, "data", "dtm_crop.npz")) if os.path.exists(os.path.join(ROOT, "data", "dtm_crop.npz")) else None
if z is not None:
    dem = geo.DEM(z["dtm"], float(z["lon_min_edge"]), float(z["lat_max_edge"]), float(z["d"]), float(z["d"]))
    dsm = geo.DEM(z["dsm"], float(z["lon_min_edge"]), float(z["lat_max_edge"]), float(z["d"]), float(z["d"]))
    kx = 111320 * math.cos(math.radians(geo.LAT0)); ky = 110574
    prof = {}
    for name, (dx, dy) in {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}.items():
        prof[name] = {f"{r}km": round(float(dem.sample(geo.LON0 + dx * r * 1000 / kx, geo.LAT0 + dy * r * 1000 / ky)), 1) for r in (0, 1, 3, 5, 10, 15, 20, 25, 30, 35)}
    g = np.linspace(-35000, 35000, 701); X, Y = np.meshgrid(g, g); m = np.hypot(X, Y) <= 35000
    zz = dem.sample(geo.LON0 + X[m] / kx, geo.LAT0 + Y[m] / ky)
    S["terrain"] = {"site_dtm_m": round(float(dem.sample(geo.LON0, geo.LAT0)), 1), "site_dsm_m": round(float(dsm.sample(geo.LON0, geo.LAT0)), 1),
                    "min_m": round(float(zz.min()), 1), "max_m": round(float(zz.max()), 1),
                    "pct_above_1500m": round(float((zz > 1500).mean() * 100), 1), "profiles": prof}
json.dump(S, open(os.path.join(ROOT, "data", "analysis_stats.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(S, ensure_ascii=False)[:200])
print("STATS DONE")
