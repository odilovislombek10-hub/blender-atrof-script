"""Detail-zone ground partition for the Bishkek site (archviz grade, no overlapping surfaces).

Produces one planar partition of the ground inside a circle (default R = 1000 m) around the
site: every square metre belongs to exactly one surface class (asphalt, curb, sidewalk paving,
aryk, lawn, ...). Shared borders use identical vertices, height steps between classes get
exactly one vertical wall, so the result is watertight and z-fight free.

Inputs : data/osm/extract/*.json, data/dtm_crop.npz, data/s2_zone_2500m.npz, scripts/street_profiles.json
Output : data/zone_partition.npz  (vertices, triangles, walls, classes, tree points)
Pure python + numpy + shapely (no bpy) so it can run outside Blender.
"""
import os, sys, json, math, time
import numpy as np

ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "pylibs")):
    if p not in sys.path:
        sys.path.append(p)
import shapely
from shapely.geometry import LineString, Polygon, Point, MultiPolygon, box
from shapely.ops import unary_union, polygonize
from shapely.strtree import STRtree
import geo

# ---- robust overlay (city run: GEOS TopologyException "non-noded intersection" / "side location conflict" on some
# OSM inputs). Every shapely set operation retries on failure: 1) with make_valid inputs, 2) snapped to a 1 mm grid,
# 3) to a 1 cm grid. Results are unchanged wherever GEOS succeeds the first time (the 1 km zone builds identically).
ROBUST_FIXES = {"n": 0}


def _robust(fn):
    def _mv(x):
        try:
            return shapely.make_valid(np.asarray(x, dtype=object) if isinstance(x, (list, tuple)) else x)
        except Exception:
            return x

    def w(*a, **k):
        try:
            return fn(*a, **k)
        except shapely.errors.GEOSException:
            ROBUST_FIXES["n"] += 1
            a2 = [_mv(x) for x in a]
            for gs in (None, 1e-3, 1e-2):
                k2 = dict(k)
                if gs is not None:
                    k2["grid_size"] = max(gs, k.get("grid_size") or 0.0)
                try:
                    return fn(*a2, **k2)
                except shapely.errors.GEOSException:
                    continue
            raise
    w._bishkek_robust = True
    return w


for _n in ("intersection", "difference", "union", "symmetric_difference", "union_all", "intersection_all"):
    if hasattr(shapely, _n) and not getattr(getattr(shapely, _n), "_bishkek_robust", False):
        setattr(shapely, _n, _robust(getattr(shapely, _n)))

RZ = float(os.environ.get("BISHKEK_ZONE_R", "1000"))
# ---- city mode (SHEF: run the same system over the whole city, 1 x 1 km tiles, one .blend per tile)
CITY = tuple(int(v) for v in os.environ["BISHKEK_TILE"].split(",")) if os.environ.get("BISHKEK_TILE") else None
TS = 1000.0
if CITY:
    CX, CY = CITY[0] * TS, CITY[1] * TS
    TBOX = (CX - TS / 2, CY - TS / 2, CX + TS / 2, CY + TS / 2)
    OUTDIR = os.path.join(ROOT, "data", "city", f"T_{CITY[0]}_{CITY[1]}")
else:
    CX = CY = 0.0
    TBOX = (-RZ, -RZ, RZ, RZ)
    OUTDIR = os.path.join(ROOT, "data")
os.makedirs(OUTDIR, exist_ok=True)


def in_work_xy(x, y):
    return TBOX[0] - MARGIN_ <= x <= TBOX[2] + MARGIN_ and TBOX[1] - MARGIN_ <= y <= TBOX[3] + MARGIN_


MARGIN_ = 150.0
XW_LINES = []
ALL_LINES = []
# SHEF rule: parking, playgrounds etc. only where seen on close satellite imagery (manual_edits.json).
# Generated guesses are OFF by default.
MAN_PARKING = None
GEN_PARKING_LANES = os.environ.get("BISHKEK_GEN_PARKING_LANES", "0") == "1"
GEN_YARD_PARKING = os.environ.get("BISHKEK_GEN_YARD_PARKING", "0") == "1"
GEN_PLAYGROUNDS = os.environ.get("BISHKEK_GEN_PLAYGROUNDS", "1") == "1"  # kept only where they clash with nothing (see yard_details)
CHAN_G = None
CHAN_OUT = None
BANK_W = 4.0
CHAN_DEPTH = 2.5
ZONE_BPOLYS = []
MARGIN = 150.0
# QA: all layer borders are noded with snap rounding on this grid (m). Near-coincident borders (kerb ring vs carriageway,
# OSM areas vs buffers) used to leave sub-mm slivers -> needle triangles, t-junctions, non-manifold edges and holes.
GRID = float(os.environ.get("BISHKEK_ZONE_GRID", "0.002"))
# vertical skirt at the outer ring: off by default, the seam to the 35 km terrain is closed by Z1_Seam_Ribbon (07)
ZONE_SKIRT = os.environ.get("BISHKEK_ZONE_SKIRT", "0") == "1"
PG_CONNECT_MAX = 15.0   # m: playground path connector only if a hard pedestrian surface is this close
PG_CONNECT_W = 1.5
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


# ------------------------------------------------------------------ surface classes
# id, name, height offset above DTM (m), priority (lower = wins)
CLASSES = [
    (1, "Crosswalk", 0.00),
    (2, "Asphalt_Road", 0.00),
    (3, "Curb", 0.15),
    (4, "Sidewalk_Paving", 0.15),
    (5, "Aryk", -0.45),
    (6, "Path_Paving", 0.15),
    (7, "Cycleway", 0.15),
    (8, "Parking_Asphalt", 0.00),
    (9, "Water", -0.35),
    (10, "Playground", 0.15),
    (11, "Sport_Pitch", 0.15),
    (12, "Street_Green", 0.15),
    (13, "Lawn", 0.15),
    (14, "Trees_Ground", 0.15),
    (15, "Yard_Hard", 0.15),
    (16, "Private_Plot", 0.15),
    (17, "Dirt_Track", 0.00),
    (18, "Bare_Soil", 0.15),
    (19, "Road_Marking", 0.00),
    (20, "Parking_Lane", 0.00),
    (21, "Entrance_Paving", 0.15),
    (22, "Apron_Concrete", 0.15),
    (23, "Forecourt_Paving", 0.15),
    (24, "Water_Channel", -2.30),
    (25, "Channel_Bank", 0.15),
]
CID = {n: i for i, n, _ in CLASSES}
COFF = {i: o for i, _, o in CLASSES}
BUILDING = 99


def num(v):
    import re
    if v is None:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


# ------------------------------------------------------------------ street profiles
DEFAULT_PROFILES = {
    # calibrated on Yandex satellite (z18-19) around the site, 24 Sep 2026:
    #   residential corridors (wall to wall) ~9.5-10 m with ~5.5 m carriageway; Toktonalieva carriageway ~18 m
    # cw = carriageway; strip = green strip with aryk + trees; sw = sidewalk; outer = green beyond sidewalk
    "primary":      {"cw": 15.0, "curb": 0.2, "strip": 3.0, "aryk": 0.8, "sw": 3.0, "outer": 2.0},
    "secondary":    {"cw": 14.0, "curb": 0.2, "strip": 1.5, "aryk": 0.6, "sw": 2.5, "outer": 1.5},
    "tertiary":     {"cw": 8.0,  "curb": 0.2, "strip": 1.5, "aryk": 0.6, "sw": 2.0, "outer": 1.0},
    "unclassified": {"cw": 6.0,  "curb": 0.2, "strip": 0.8, "aryk": 0.5, "sw": 1.2, "outer": 0.0},
    "residential":  {"cw": 5.5,  "curb": 0.2, "strip": 0.8, "aryk": 0.5, "sw": 1.2, "outer": 0.0},
    "living_street": {"cw": 4.5, "curb": 0.2, "strip": 0.6, "aryk": 0.4, "sw": 1.0, "outer": 0.0},
    "service":      {"cw": 4.0,  "curb": 0.15, "strip": 0.0, "aryk": 0.0, "sw": 0.0, "outer": 0.0},
    "track":        {"cw": 3.5,  "curb": 0.0, "strip": 0.0, "aryk": 0.0, "sw": 0.0, "outer": 0.0},
}
for k, v in list(DEFAULT_PROFILES.items()):
    if k in ("primary", "secondary", "tertiary"):
        DEFAULT_PROFILES[k + "_link"] = dict(v, strip=0.0, aryk=0.0, sw=0.0, outer=0.0, cw=6.0)
DEFAULT_PROFILES["trunk"] = dict(DEFAULT_PROFILES["primary"], cw=18.0)
DEFAULT_PROFILES["road"] = DEFAULT_PROFILES["residential"]
DEFAULT_PROFILES["busway"] = dict(DEFAULT_PROFILES["service"], cw=7.0)

PATHS = {"footway": ("Path_Paving", 2.0), "path": ("Path_Paving", 1.5), "pedestrian": ("Path_Paving", 5.0),
         "steps": ("Path_Paving", 2.0), "cycleway": ("Cycleway", 2.0), "bridleway": ("Dirt_Track", 2.0),
         "corridor": ("Path_Paving", 2.0)}


def load_profiles():
    p = os.path.join(ROOT, "scripts", "street_profiles.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def road_profile(tags, overrides):
    cls = tags.get("highway")
    prof = dict(DEFAULT_PROFILES.get(cls, DEFAULT_PROFILES["residential"]))
    if cls == "service":
        s = tags.get("service")
        prof["cw"] = {"parking_aisle": 6.0, "driveway": 3.5, "alley": 4.0}.get(s, 4.0)
    lanes = num(tags.get("lanes"))
    if lanes and 1 <= lanes <= 10 and cls not in ("service", "track"):
        prof["cw"] = lanes * 3.5 + (1.0 if lanes >= 4 else 0.0)
    w = num(tags.get("width"))
    if w and 2 <= w <= 60:
        prof["cw"] = w
    name = tags.get("name")
    oneway = tags.get("oneway") in ("yes", "1", "-1", "true")
    if oneway and cls in ("primary", "secondary", "tertiary", "trunk") and not lanes and not w:
        prof["cw"] = min(prof["cw"], 8.0)   # one half of a dual carriageway
    for key in (name, tags.get("name:ru"), tags.get("name:ky")):
        if key and key in overrides:
            ov = dict(overrides[key])
            if oneway:
                # QA: a street override describes the undivided street (Toktonalieva 18 m incl. kerbside parking);
                # applied to both one-way halves of its dual-carriageway section it made a ~26 m wide asphalt blob
                ov.pop("cw", None)
            prof.update(ov)
            break
    return prof


# ------------------------------------------------------------------ traced 300 m tiles (close satellite imagery)
TILE = {"areas": [], "paths": [], "alleys": [], "fences": [], "bld_add": [], "bld_gone": [], "tiles": []}
AREA_CLASS = {("parking", None): "Parking_Asphalt", ("playground", None): "Playground", ("sport", "soil"): "Bare_Soil",
              ("sport", None): "Sport_Pitch", ("garden", None): "Private_Plot"}
SURF_CLASS = {"asphalt": "Yard_Hard", "paving": "Forecourt_Paving", "concrete": "Apron_Concrete", "soil": "Bare_Soil",
              "gravel": "Bare_Soil", "grass": "Lawn", "rubber": "Playground", "turf": "Sport_Pitch"}


def load_tiles():
    """SHEF: the ground is traced from close (z18/z19) satellite imagery, tile by tile (data/tiles/T_i_j.json).
    Traced features win over OSM / Sentinel guesses where they overlap."""
    import glob
    d = os.environ.get("BISHKEK_TILES", os.path.join(ROOT, "data", "tiles"))
    for f in sorted(glob.glob(os.path.join(d, "T_*.json"))):
        try:
            t = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            log("tile unreadable", f, e); continue
        TILE["tiles"].append((os.path.basename(f), t.get("bounds")))
        if t.get("complete") and t.get("bounds"):
            TILE.setdefault("done", []).append(box(*t["bounds"]))
        for ft in t.get("features", []):
            ty = ft.get("type")
            try:
                if ty == "area" and len(ft.get("poly", [])) >= 3:
                    use = ft.get("use"); sf = ft.get("surface")
                    cls = AREA_CLASS.get((use, sf)) or AREA_CLASS.get((use, None)) or SURF_CLASS.get(sf)
                    if use == "yard" and sf == "soil":
                        cls = "Lawn"   # SHEF: ground under yard trees is lawn (green), not soil
                    if cls:
                        g = Polygon(ft["poly"]).buffer(0)
                        if not g.is_empty:
                            TILE["areas"].append((cls, g))
                elif ty in ("footpath", "alley") and len(ft.get("line", [])) >= 2:
                    ln = LineString(ft["line"]); w = float(ft.get("width") or (1.5 if ty == "footpath" else 4.0))
                    sf = ft.get("surface", "asphalt")
                    g = ln.buffer(w / 2, cap_style="flat", join_style="round")
                    if ty == "footpath":
                        cls = {"paving": "Path_Paving", "asphalt": "Path_Paving", "dirt": "Dirt_Track", "gravel": "Dirt_Track"}.get(sf, "Path_Paving")
                        # a path reaches what it joins: extend both ends by 0.6 m
                        g = ln.buffer(w / 2, cap_style="square", join_style="round") if ln.length > 2 else g
                        TILE["paths"].append((cls, g))
                    else:
                        cls = "Dirt_Track" if sf in ("dirt", "gravel", "soil") else "Asphalt_Road"
                        TILE["alleys"].append((cls, g))
                elif ty == "fence" and len(ft.get("line", [])) >= 2:
                    TILE["fences"].append(LineString(ft["line"]))
                elif ty == "building_missing" and len(ft.get("poly", [])) >= 3:
                    TILE["bld_add"].append((Polygon(ft["poly"]).buffer(0), ft.get("levels")))
                elif ty == "building_gone" and ft.get("at"):
                    TILE["bld_gone"].append(Point(ft["at"]))
            except Exception as e:
                log("tile feature skipped", f, ty, e)
    log("traced tiles", [n for n, _ in TILE["tiles"]], {k: len(v) for k, v in TILE.items() if k != "tiles"})


# ------------------------------------------------------------------ geometry helpers
def to_xy(pts):
    a = np.asarray(pts, dtype=np.float64)
    x, y = geo.to_local(a[:, 0], a[:, 1])
    return np.stack([x, y], 1)


def poly_from(pd):
    ext = to_xy(pd["outer"])
    holes = [to_xy(h) for h in pd.get("inner", []) if len(h) >= 4]
    p = Polygon(ext, holes)
    if not p.is_valid:
        p = shapely.make_valid(p)
    return p


def side_band(line, a, b, side):
    """Band between offsets a..b (a<b) on one side of a line. side=+1 left, -1 right."""
    if b <= a + 1e-3:
        return None
    outer = line.buffer(side * b, single_sided=True, cap_style="flat", join_style="round")
    inner = line.buffer(side * a, single_sided=True, cap_style="flat", join_style="round") if a > 1e-3 else None
    g = outer.difference(inner) if inner is not None else outer
    return g if not g.is_empty else None


def offset_line(line, d):
    try:
        g = line.offset_curve(d, join_style="round")
        return g if not g.is_empty else None
    except Exception:
        return None


CANOPY_G = None


def mask_to_poly(mask, g):
    """Raster mask (UTM 43N grid, 10 m) -> smoothed local-coordinate polygons."""
    E_ul, N_ul, px = g
    cells = []
    rows, cols = np.nonzero(mask)
    s = px / geo.KS
    for r, c in zip(rows, cols):
        x0 = (E_ul + c * px - geo.E0) / geo.KS; y1 = (N_ul - r * px - geo.N0) / geo.KS
        if (not CITY and math.hypot(x0, y1) > RZ + MARGIN + 20) or (CITY and not in_work_xy(x0, y1)):
            continue
        cells.append(box(x0, y1 - s, x0 + s, y1))
    if not cells:
        return Polygon()
    P = unary_union(cells)
    P = P.buffer(3.0, quad_segs=6).buffer(-5.0, quad_segs=6).buffer(2.0, quad_segs=6)
    return shapely.simplify(P, 0.8)


# ------------------------------------------------------------------ yard / street details
def _dashes(line, dash, gap):
    from shapely.ops import substring
    out = []
    for ln in getattr(line, "geoms", [line]):
        if ln.geom_type != "LineString":
            continue
        s_ = 0.0
        L = ln.length
        while s_ < L:
            seg = substring(ln, s_, min(s_ + dash, L))
            if seg.length > 0.2:
                out.append(seg)
            s_ += dash + gap
    return out


def yard_details(roads, overrides, CW, SW, HARDPATHS, GROUND_VEG, bpolys, A, XW, jpts_major, zone):
    """Procedural archviz detail following Soviet micro-district practice, driven by real data:
    apron around blocks, porches + paths at entrances (entrance side = side facing the driveway),
    yard parking where the July 2026 image shows hard ground next to driveways, playgrounds in
    courtyards without one, paved forecourts between blocks and main streets, kerbside parking
    lanes and road markings on the main streets."""
    from shapely.ops import nearest_points, polylabel
    svc = [LineString(xy) for t, xy in roads if t.get("highway") == "service" and len(xy) >= 2]
    svc_u = unary_union(svc) if svc else None
    apts = [p for p in bpolys if p.area >= 350 and p.geom_type == "Polygon"]
    APTU = unary_union(apts) if apts else Polygon()
    # 1) apron (otmostka) 1 m around blocks
    APRON = unary_union([p.buffer(1.0, join_style="mitre") for p in apts]).difference(APTU) if apts else Polygon()
    # 2) entrances: porch + path to the hard network
    hard = unary_union([g for g in (CW, SW, HARDPATHS) if g is not None and not g.is_empty])
    porches, epaths = [], []
    n_ent = 0
    for p in apts:
        mrr = p.minimum_rotated_rectangle
        if mrr.geom_type != "Polygon":
            continue
        cs = np.array(mrr.exterior.coords)[:4]
        e = [float(np.linalg.norm(cs[(i + 1) % 4] - cs[i])) for i in range(4)]
        i0 = int(np.argmax(e)); L = e[i0]; W = e[(i0 + 1) % 4]
        if L < 18:
            continue
        cands = []
        for sd in (i0, (i0 + 2) % 4):
            a, b = cs[sd], cs[(sd + 1) % 4]
            d = (b - a) / np.linalg.norm(b - a); nrm = np.array([d[1], -d[0]])
            mid = (a + b) / 2
            if p.buffer(0.5).contains(Point(*(mid + nrm * 3))):
                nrm = -nrm
            probe = Point(*(mid + nrm * 10))
            dist = svc_u.distance(probe) if svc_u is not None else 1e9
            cands.append((dist, a, b, nrm, d))
        cands.sort(key=lambda c: c[0])
        dist, a, b, nrm, d = cands[0]
        if L / max(W, 1.0) < 1.5:
            nent = 1
        else:
            nent = max(1, int(round(L / 18.0)))
        for k in range(nent):
            q = a + (b - a) * ((k + 0.5) / nent)
            ray = LineString([tuple(q + nrm * 8), tuple(q - nrm * 8)])
            hit = ray.intersection(p.exterior)
            pts = [hit] if hit.geom_type == "Point" else [g for g in getattr(hit, "geoms", []) if g.geom_type == "Point"]
            if not pts:
                continue
            hp = max(pts, key=lambda pp: pp.x * nrm[0] + pp.y * nrm[1])
            h = np.array([hp.x, hp.y])
            porch = Polygon([tuple(h - d * 1.5), tuple(h + d * 1.5), tuple(h + d * 1.5 + nrm * 2.4), tuple(h - d * 1.5 + nrm * 2.4)])
            porches.append(porch); n_ent += 1
            start = h + nrm * 2.4
            if hard.is_empty:
                continue
            ray2 = LineString([tuple(start), tuple(start + nrm * 45)])
            hi = ray2.intersection(hard)
            if not hi.is_empty:
                sp = Point(*start)
                tgt = min([g for g in getattr(hi, "geoms", [hi])], key=lambda g: g.distance(sp))
                end = nearest_points(sp, tgt)[1]
            else:
                end = nearest_points(Point(*start), hard)[1]
                if Point(*start).distance(end) > 40:
                    continue
            epaths.append(LineString([tuple(start), (end.x, end.y)]).buffer(1.0, cap_style="flat"))
    ENTR = unary_union(porches + epaths) if porches else Polygon()
    # QA: a porch / entrance path ends at the first hard surface it meets. Where a block stands right at the street,
    # the 2.4 m porch crossed the sidewalk and left paving islands on the green strip -> keep only the parts that
    # touch their building
    if not ENTR.is_empty and not hard.is_empty:
        cut = ENTR.difference(hard)
        atree = STRtree(apts)
        keep_e = [g for g in getattr(cut, "geoms", [cut])
                  if g.geom_type == "Polygon" and g.area > 0.05 and len(atree.query(g, predicate="dwithin", distance=0.05))]
        n_cut = len(getattr(cut, "geoms", [cut])) - len(keep_e)
        ENTR = unary_union(keep_e) if keep_e else Polygon()
        log("entrance paving pieces cut off by a sidewalk / road (not at a building) removed", n_cut)
    # 3) yard parking: bands along driveways near blocks, only where the ground is not green in the leaf-off image
    bands = []
    for l in svc:
        for sd in (+1, -1):
            g = side_band(l, 2.2, 7.5, sd)
            if g is not None:
                bands.append(g)
    PARK = Polygon()
    if bands and apts and GEN_YARD_PARKING:
        PARK = unary_union(bands).intersection(APTU.buffer(45)).difference(APTU.buffer(4.0))
        PARK = PARK.difference(GROUND_VEG).difference(ENTR.buffer(0.5)).difference(CW)
        PARK = PARK.buffer(-2.2, join_style="mitre").buffer(2.2, join_style="mitre")
        PARK = unary_union([g for g in getattr(PARK, "geoms", [PARK]) if g.area >= 35])
    # 4) playgrounds in courtyards that have none
    gen_pg = []
    if apts and GEN_PLAYGROUNDS:
        existing = A["Playground"]
        cand = APTU.buffer(45).intersection(zone).difference(CW.buffer(12)).difference(APTU.buffer(8))
        cand = cand.difference(PARK.buffer(2)).difference(ENTR.buffer(2))
        if not existing.is_empty:
            cand = cand.difference(existing.buffer(70))
        houses = [p for p in bpolys if p.area < 350]
        if houses:
            cand = cand.difference(unary_union(houses).buffer(15))
        polys = sorted([g for g in getattr(cand, "geoms", [cand]) if g.geom_type == "Polygon" and g.area >= 450], key=lambda g: -g.area)
        used = Polygon()
        for g in polys:
            g = g.difference(used)
            if g.is_empty or g.area < 450:
                continue
            gg = max(getattr(g, "geoms", [g]), key=lambda x: x.area)
            c = polylabel(gg, tolerance=1.0)
            if gg.exterior.distance(c) < 8.5:
                continue
            near_apt = min(apts, key=lambda p: p.distance(c))
            mr = np.array(near_apt.minimum_rotated_rectangle.exterior.coords)[:4]
            e0 = mr[1] - mr[0]; e1 = mr[2] - mr[1]
            ax = e0 if np.linalg.norm(e0) >= np.linalg.norm(e1) else e1
            ax = ax / np.linalg.norm(ax); ay = np.array([-ax[1], ax[0]])
            cc = np.array([c.x, c.y])
            rect = Polygon([tuple(cc - ax * 9 - ay * 7), tuple(cc + ax * 9 - ay * 7), tuple(cc + ax * 9 + ay * 7), tuple(cc - ax * 9 + ay * 7)])
            if rect.within(gg.buffer(0.5)):
                gen_pg.append(rect)
                used = used.union(Point(c.x, c.y).buffer(80))
    # 5) forecourts between blocks and main streets, 6) kerbside parking lanes, 7) road markings
    fore, plane, marks = [], [], []
    jdisc = unary_union([p.buffer(16.0) for p in jpts_major]) if jpts_major else Polygon()
    xwb = XW.buffer(1.5) if not XW.is_empty else Polygon()
    for t, xy in roads:
        cls = t.get("highway")
        if cls not in ("primary", "secondary", "tertiary", "trunk"):
            continue
        line = LineString(xy)
        if line.length < 5:
            continue
        prof = road_profile(t, overrides)
        half = prof["cw"] / 2
        hc = half + prof["curb"] + prof["strip"] + prof["sw"]
        oneway = t.get("oneway") in ("yes", "1", "-1", "true")
        # forecourts
        for p in apts:
            dd = p.distance(line)
            if dd > hc + 25 or dd < hc - 0.5:
                continue
            ring = shapely.segmentize(p.exterior, 2.0)
            facing = [c for c in ring.coords if line.distance(Point(c)) <= dd + 2.0]
            if len(facing) < 2:
                continue
            pts_ = []
            for c in facing:
                q = line.interpolate(line.project(Point(c)))
                v = np.array(c) - np.array([q.x, q.y]); nv = np.linalg.norm(v)
                if nv < 1e-6:
                    continue
                pts_.append(c); pts_.append(tuple(np.array([q.x, q.y]) + v / nv * hc))
            if len(pts_) >= 3:
                fore.append(shapely.MultiPoint(pts_).convex_hull)
        # kerbside parking lanes (observed on Toktonalieva) on secondary/tertiary streets with room
        if GEN_PARKING_LANES and cls in ("secondary", "tertiary") and prof["cw"] >= 10 and not oneway:
            for sd in (+1, -1):
                g = side_band(line, half - 2.5, half, sd)
                if g is not None:
                    plane.append(g)
    # markings (0.15 m paint): lines merged per street so dashes run continuously across OSM way splits and
    # side-street T-junctions; they stop only where two main streets cross and at zebra crossings (SHEF E6)
    from shapely.ops import linemerge
    msrc = {}
    for t, xy in roads:
        cls = t.get("highway")
        if cls not in ("primary", "secondary", "tertiary", "trunk"):
            continue
        if t.get("oneway") in ("yes", "1", "-1", "true"):
            continue
        prof = road_profile(t, overrides)
        key = (t.get("name") or t.get("ref") or ("way%d" % len(msrc)), cls)
        e = msrc.setdefault(key, {"lines": [], "lanes": []})
        e["lines"].append(LineString(xy))
        e["lanes"].append(int(num(t.get("lanes")) or (4 if prof["cw"] >= 13 else 2)))
    merged_main = {}
    for key, e in msrc.items():
        mg = shapely.line_merge(unary_union(e["lines"]))
        merged_main[key] = mg
        lanes = max(set(e["lanes"]), key=e["lanes"].count)
        for line in getattr(mg, "geoms", [mg]):
            if line.length < 5:
                continue
            if lanes >= 4:
                for off in (0.15, -0.15):
                    ol = offset_line(line, off)
                    if ol is not None:
                        marks.append(ol.buffer(0.075, cap_style="flat"))
                for k in range(1, int(lanes // 2)):
                    for sd in (+1, -1):
                        ol = offset_line(line, sd * 3.5 * k)
                        if ol is not None:
                            for dsh in _dashes(ol, 3.0, 6.0):
                                marks.append(dsh.buffer(0.075, cap_style="flat"))
            else:
                for dsh in _dashes(line, 3.0, 6.0):
                    marks.append(dsh.buffer(0.075, cap_style="flat"))
    # junction boxes only where two different main streets cross
    jx = []
    keys = list(merged_main)
    for a_ in range(len(keys)):
        for b_ in range(a_ + 1, len(keys)):
            if keys[a_][0] == keys[b_][0]:
                continue
            ip = merged_main[keys[a_]].intersection(merged_main[keys[b_]])
            for g in getattr(ip, "geoms", [ip]):
                if g.geom_type == "Point":
                    jx.append(g.buffer(13.0))
    jdisc = unary_union(jx) if jx else Polygon()
    FORE = unary_union(fore).difference(APTU) if fore else Polygon()
    # playgrounds: keep a generated one only if it touches no road, paving, path, entrance, forecourt,
    # parking, sport pitch or water; clashing candidates go to a list to be checked on close imagery
    clash = unary_union([g for g in (CW.buffer(2.0), SW, HARDPATHS, ENTR, FORE, APRON, A["Parking_Asphalt"], MAN_PARKING,
                                     A["Sport_Pitch"], A["Water"]) if g is not None and not g.is_empty])
    keep_pg, verify_pg = [], []
    for r_ in gen_pg:
        (verify_pg if r_.intersects(clash) else keep_pg).append(r_)
    PLAY = unary_union(keep_pg) if keep_pg else Polygon()
    try:
        json.dump([{"x": round(r_.centroid.x, 1), "y": round(r_.centroid.y, 1), "poly": [[round(a, 2), round(b, 2)] for a, b in r_.exterior.coords]} for r_ in verify_pg],
                  open(os.path.join(OUTDIR, "playgrounds_to_verify.json"), "w"), indent=1)
    except Exception:
        pass
    log("playgrounds kept", len(keep_pg), "to verify on imagery", len(verify_pg))
    PLANE = unary_union(plane).intersection(CW).difference(jdisc).difference(xwb) if plane else Polygon()
    MARK = unary_union(marks).intersection(CW).difference(jdisc).difference(xwb).difference(PLANE) if marks else Polygon()
    log("details: entrances", n_ent, "yard parking m2", round(PARK.area), "new playgrounds", len(gen_pg),
        "forecourt m2", round(FORE.area), "parking lane m2", round(PLANE.area), "markings m2", round(MARK.area))
    return {"APRON": APRON, "ENTR": ENTR, "PARK": PARK, "PLAY": PLAY, "FORE": FORE, "PLANE": PLANE, "MARK": MARK}


def _resolve_building_overlaps(polys, min_ov=0.5):
    if len(polys) < 2:
        return polys, 0, 0
    tree = STRtree(polys)
    cur = list(polys); alive = [True] * len(polys); done = [False] * len(polys)
    n_trim = n_drop = 0
    for i in sorted(range(len(polys)), key=lambda k: -polys[k].area):
        g = cur[i]
        nb = [j for j in tree.query(polys[i], predicate="intersects") if j != i and done[j] and alive[j]]
        if nb:
            other = unary_union([cur[j] for j in nb])
            if g.intersection(other).area > min_ov:
                r = g.difference(other)   # exact: the two share their wall line, no ground sliver between them (QA open_chain)
                r = max(getattr(r, "geoms", [r]), key=lambda q: q.area) if not r.is_empty else r
                if r.is_empty or r.geom_type != "Polygon" or r.area < max(4.0, 0.3 * g.area):
                    alive[i] = False; n_drop += 1
                else:
                    cur[i] = r; n_trim += 1
        done[i] = True
    return [cur[i] for i in range(len(polys)) if alive[i]], n_trim, n_drop


# ------------------------------------------------------------------ main build
def build():
    global CANOPY_G
    ex = os.path.join(ROOT, "data", "osm", "extract")
    zp = os.path.join(ROOT, "data", "zone_raw.json")
    if CITY:
        # tile square minus the central detail zone (radius RZ around the site), so nothing overlaps it
        zone = box(*TBOX).difference(Point(0, 0).buffer(RZ, quad_segs=64))
        zone = max(getattr(zone, "geoms", [zone]), key=lambda g: g.area)
        work = box(*TBOX).buffer(MARGIN, join_style="mitre")

        def near(xy):
            return bool(np.any((xy[:, 0] >= TBOX[0] - MARGIN) & (xy[:, 0] <= TBOX[2] + MARGIN) &
                               (xy[:, 1] >= TBOX[1] - MARGIN) & (xy[:, 1] <= TBOX[3] + MARGIN))) or \
                (LineString(xy).intersects(work) if len(xy) >= 2 else False)
    else:
        zone = Point(0, 0).buffer(RZ, quad_segs=64)
        work = Point(0, 0).buffer(RZ + MARGIN, quad_segs=64)

        def near(xy):
            return float(np.min(np.hypot(xy[:, 0], xy[:, 1]))) <= RZ + MARGIN
    globals()["ZONE_G"] = zone

    if CITY:
        tp_ = os.path.join(ROOT, "data", "city", "osm", f"T_{CITY[0]}_{CITY[1]}.json")
        zp = tp_ if os.path.exists(tp_) else "__none__"
    if os.path.exists(zp):
        D = json.load(open(zp, encoding="utf-8"))
    else:
        D = {n: json.load(open(os.path.join(ex, n + ".json"), encoding="utf-8"))
             for n in ("buildings", "highways", "lines", "areas", "nodes")}
    overrides = load_profiles()

    # --- buildings (holes in the ground)
    bpolys = []
    for b in D["buildings"]:
        for pd in b["polys"]:
            xy = to_xy(pd["outer"])
            if not near(xy):
                continue
            p = poly_from(pd)
            if p.area > 4:
                bpolys.append(p)
    # QA building_overlap (city run: OSM has buildings drawn over each other - a kiosk inside a mall, two versions of one
    # block). Larger footprints win; a smaller one keeps only its free part, or is dropped when little of it is free.
    bpolys, n_trim, n_drop = _resolve_building_overlaps(bpolys)
    if n_trim or n_drop:
        log("overlapping OSM buildings: trimmed", n_trim, "dropped", n_drop)
    load_tiles()
    if TILE["bld_gone"]:
        n0 = len(bpolys)
        bpolys = [p for p in bpolys if not any(p.buffer(1.0).contains(q) for q in TILE["bld_gone"])]
        log("buildings removed (not on imagery)", n0 - len(bpolys))
    TILE_BLD_TAGS = []
    for g, lv in TILE["bld_add"]:
        if g.area > 4 and not any(p.intersection(g).area > 0.5 * g.area for p in bpolys):
            # QA building_overlap: a traced building never overlaps a mapped one (keep only the free part)
            near_ = [p for p in bpolys if p.intersects(g)]
            if near_:
                g = g.difference(unary_union(near_).buffer(0.05))
                g = max(getattr(g, "geoms", [g]), key=lambda q: q.area) if not g.is_empty else g
            if g.is_empty or g.geom_type != "Polygon" or g.area < 4:
                continue
            bpolys.append(g)
            TILE_BLD_TAGS.append({"c": [round(g.centroid.x, 2), round(g.centroid.y, 2)], "levels": lv})
    json.dump(TILE_BLD_TAGS, open(os.path.join(OUTDIR, "tile_building_tags.json"), "w"))
    log("buildings added from imagery", len(TILE_BLD_TAGS))
    BUILD = unary_union(bpolys).intersection(work)
    log("buildings", len(bpolys))

    # --- roads
    cw_polys, curb_ext, strips, sws, outers, aryk_lines, crossings, junction_pts = [], [], [], [], [], [], [], []
    tracks = []
    vcount = {}
    roads = []
    for hw in D["highways"]:
        t = hw["tags"]; cls = t.get("highway")
        xy = to_xy(hw["pts"])
        if len(xy) < 2 or not near(xy):
            continue
        if cls in DEFAULT_PROFILES:
            roads.append((t, xy))
            for p in hw["pts"]:
                k = (round(p[0], 7), round(p[1], 7))
                vcount[k] = vcount.get(k, 0) + 1
    for t, xy in roads:
        line = LineString(xy)
        if line.length < 0.5:
            continue
        prof = road_profile(t, overrides)
        cls = t.get("highway")
        half = prof["cw"] / 2
        if cls == "track":
            tracks.append(line.buffer(half, cap_style="flat"))
            continue
        cw_polys.append(line.buffer(half, cap_style="flat", join_style="round"))
        oneway = t.get("oneway") in ("yes", "1", "-1", "true")
        sides = [+1, -1]
        if oneway and cls in ("primary", "secondary", "tertiary", "trunk"):
            # dual carriageway: only the traffic-right side is the kerbside
            sides = [-1] if t.get("oneway") != "-1" else [+1]
        c = prof["curb"]; s = prof["strip"]; w = prof["sw"]; o = prof["outer"]
        for sd in sides:
            b1 = half + c; b2 = b1 + s; b3 = b2 + w; b4 = b3 + o
            g = side_band(line, b1, b2, sd)
            if g is not None: strips.append(g)
            g = side_band(line, b2, b3, sd)
            if g is not None: sws.append(g)
            g = side_band(line, b3, b4, sd)
            if g is not None: outers.append(g)
            if prof["aryk"] > 0 and s >= prof["aryk"] + 0.2:
                al = offset_line(line, sd * (b1 + s / 2))
                if al is not None:
                    aryk_lines.append((al, prof["aryk"]))
    CW = unary_union(cw_polys)
    # junction fillets: closing only around shared nodes
    jpts = [Point(*to_xy([list(k)])[0]) for k, n in vcount.items() if n >= 2]
    fillet = []
    for p in jpts:
        disc = p.buffer(22.0, quad_segs=16)
        local = CW.intersection(disc)
        if local.is_empty:
            continue
        closed = local.buffer(5.0, quad_segs=8).buffer(-5.0, quad_segs=8)
        fillet.append(closed.intersection(disc.buffer(-1.0)))
    CW = unary_union([CW] + fillet)
    CURB = CW.buffer(0.2, quad_segs=8).difference(CW)
    SW = unary_union(sws)
    SWc = []
    for p in jpts:
        disc = p.buffer(30.0, quad_segs=16)
        local = SW.intersection(disc)
        if not local.is_empty:
            SWc.append(local.buffer(3.0, quad_segs=8).buffer(-3.0, quad_segs=8).intersection(disc.buffer(-1)))
    SW = unary_union([SW] + SWc)
    # corners: offset rings of the carriageway around junctions of real streets, so kerb, green strip and
    # sidewalk turn the corner continuously instead of ending at the road end
    street_lines = [(road_profile(t, overrides), LineString(xy)) for t, xy in roads if t.get("highway") not in ("service", "track")]
    st_tree = STRtree([l for _, l in street_lines]) if street_lines else None
    corner_sw, corner_st = [], []
    if st_tree is not None:
        for p in jpts:
            hit = st_tree.query(p.buffer(0.5), predicate="intersects")
            if len(hit) < 2:
                continue
            profs = [street_lines[i][0] for i in hit]
            s_ = min(pr["strip"] for pr in profs); w_ = min(pr["sw"] for pr in profs)
            if w_ <= 0:
                continue
            disc = p.buffer(max(pr["cw"] for pr in profs) / 2 + 14.0, quad_segs=16)
            loc = CW.intersection(disc.buffer(10))
            r1 = loc.buffer(0.2 + s_, quad_segs=12); r2 = loc.buffer(0.2 + s_ + w_, quad_segs=12)
            corner_st.append(r1.difference(loc.buffer(0.2, quad_segs=12)).intersection(disc))
            corner_sw.append(r2.difference(r1).intersection(disc))
    if corner_sw:
        SW = unary_union([SW] + corner_sw)
        strips = strips + corner_st
    STRIP = unary_union(strips)
    OUTER = unary_union(outers)
    ARYK = unary_union([l.buffer(w / 2, cap_style="flat") for l, w in aryk_lines]) if aryk_lines else Polygon()
    log("roads", len(roads), "junctions", len(jpts))

    HARD0 = unary_union([CW, SW])
    # --- paths, crossings, mapped sidewalks
    paths = {"Path_Paving": [], "Cycleway": [], "Dirt_Track": []}
    xw = []
    for hw in D["highways"]:
        t = hw["tags"]; cls = t.get("highway")
        xy = to_xy(hw["pts"])
        if len(xy) < 2 or not near(xy):
            continue
        line = LineString(xy)
        if cls == "footway" and t.get("footway") == "crossing":
            xw.append(line.buffer(2.0, cap_style="flat"))
            continue
        if cls == "footway" and t.get("footway") == "sidewalk":
            sws.append(line.buffer(1.25, cap_style="flat"))
            continue
        if cls in PATHS:
            cname, w = PATHS[cls]
            w = num(t.get("width")) or w
            paths[cname].append(line.buffer(w / 2, cap_style="round"))
            for end in (Point(xy[0]), Point(xy[-1])):
                dd = HARD0.distance(end)
                if 0.3 < dd <= 6.0:
                    from shapely.ops import nearest_points as _np
                    tgt = _np(end, HARD0)[1]
                    paths[cname].append(LineString([(end.x, end.y), (tgt.x, tgt.y)]).buffer(w / 2, cap_style="round"))
    # SHEF E2: a footpath never ends in the middle of a lawn - an end that touches no road, sidewalk, other path or
    # building is joined to the nearest of them (up to 15 m)
    try:
        from shapely.ops import nearest_points as _np2
        plines = []
        for hw in D["highways"]:
            t = hw["tags"]; cls = t.get("highway")
            if cls in PATHS and t.get("footway") not in ("crossing", "sidewalk"):
                xy = to_xy(hw["pts"])
                if len(xy) >= 2 and near(xy):
                    plines.append((LineString(xy), PATHS[cls], num(t.get("width"))))
        bnear = unary_union([b for b in bpolys]) if bpolys else Polygon()
        n_join = 0
        for i, (ln, (cname, w0), wtag) in enumerate(plines):
            w = wtag or w0
            others = unary_union([HARD0, bnear.boundary] + [l for j, (l, _, _) in enumerate(plines) if j != i and l.distance(ln) < 20])
            for end in (Point(ln.coords[0]), Point(ln.coords[-1])):
                d_ = others.distance(end)
                if 1.0 < d_ <= 15.0:
                    tgt = _np2(end, others)[1]
                    paths[cname].append(LineString([(end.x, end.y), (tgt.x, tgt.y)]).buffer(w / 2, cap_style="round"))
                    n_join += 1
        log("E2 dangling path ends joined", n_join)
    except Exception as e:
        log("E2 path join failed", e)
    for n in D["nodes"]:
        if n["t"] == "highway=crossing":
            q = to_xy([n["p"]])[0]
            if (math.hypot(*q) <= RZ + MARGIN) if not CITY else in_work_xy(*q):
                xw.append(Point(*q).buffer(0.01))  # marker, expanded below
    # node crossings: build zebra rectangle across the carriageway near the node
    xrects = []
    cw_lines = [LineString(xy) for t, xy in roads if t.get("highway") not in ("service", "track")]
    cw_half = [road_profile(t, overrides)["cw"] / 2 for t, xy in roads if t.get("highway") not in ("service", "track")]
    tree_cw = STRtree(cw_lines) if cw_lines else None
    shapely.prepare(CW)

    def _ray(px, py, dx_, dy_, maxd, border):
        """distance from (px,py) along (dx_,dy_) to the carriageway border (None if not within maxd)"""
        hit = LineString([(px, py), (px + dx_ * maxd, py + dy_ * maxd)]).intersection(border)
        if hit.is_empty:
            return None
        q = shapely.get_coordinates(hit)
        return float(np.min(np.hypot(q[:, 0] - px, q[:, 1] - py)))

    n_shift = n_drop = 0
    for g in xw:
        if g.area > 1:
            xrects.append(g)
            continue
        c = g.centroid
        if tree_cw is None:
            continue
        i = tree_cw.nearest(c)
        ln = cw_lines[i]
        if ln.distance(c) > 3:
            continue
        s = ln.project(c)
        # QA: the zebra must run kerb to kerb across its own street. Crossing nodes of a side street that sit inside
        # the wider carriageway of the main street (junction mouth) made zebras in the middle of the junction that
        # touched no sidewalk -> slide along the street (<= 15 m) to where both kerbs are within its half width.
        border = shapely.clip_by_rect(CW, c.x - 60, c.y - 60, c.x + 60, c.y + 60).boundary
        lim = cw_half[i] + 2.5
        best = None
        for sh in [0.0] + [float(v) for k in range(1, 16) for v in (k, -k)]:
            s2 = s + sh
            if s2 < 0 or s2 > ln.length:
                continue
            p1 = ln.interpolate(max(s2 - 0.5, 0)); p2 = ln.interpolate(min(s2 + 0.5, ln.length))
            dx, dy = p2.x - p1.x, p2.y - p1.y
            L = math.hypot(dx, dy) or 1
            ux, uy = dx / L, dy / L
            nx, ny = -uy, ux
            pc = ln.interpolate(s2)
            if not CW.contains(pc):
                continue
            dp = _ray(pc.x, pc.y, nx, ny, 25.0, border); dm = _ray(pc.x, pc.y, -nx, -ny, 25.0, border)
            if dp is None or dm is None or dp > lim or dm > lim:
                continue
            best = (pc, ux, uy, nx, ny, dp + 0.3, dm + 0.3, sh)
            break
        if best is None:
            n_drop += 1
            continue
        pc, ux, uy, nx, ny, hp, hm, sh = best
        n_shift += sh != 0
        rect = Polygon([(pc.x - ux * 2 + nx * hp, pc.y - uy * 2 + ny * hp), (pc.x + ux * 2 + nx * hp, pc.y + uy * 2 + ny * hp),
                        (pc.x + ux * 2 - nx * hm, pc.y + uy * 2 - ny * hm), (pc.x - ux * 2 - nx * hm, pc.y - uy * 2 - ny * hm)])
        xrects.append(rect)
    XW = unary_union(xrects).intersection(CW) if xrects else Polygon()
    log("crossings", len(xrects), "node zebras moved to their kerb line", n_shift, "dropped (no kerb within reach)", n_drop)
    SW = unary_union([SW] + sws) if sws else SW
    global XW_LINES, ALL_LINES
    XW_LINES = cw_lines
    ALL_LINES = [LineString(xy) for t, xy in roads if len(xy) >= 2]

    # --- areas from OSM
    A = {k: [] for k in ("Parking_Asphalt", "Water", "Playground", "Sport_Pitch", "Lawn", "Trees_Ground", "Bare_Soil")}
    for ar in D["areas"]:
        t = ar["tags"]
        cname = None
        if t.get("amenity") == "parking" and t.get("parking") not in ("underground", "multi-storey"):
            cname = "Parking_Asphalt"
        elif t.get("natural") == "water" or t.get("leisure") == "swimming_pool" or t.get("amenity") == "fountain" or "water" in t:
            cname = "Water"
        elif t.get("leisure") == "playground":
            cname = "Playground"
        elif t.get("leisure") in ("pitch", "track"):
            cname = "Sport_Pitch"
        elif t.get("landuse") in ("grass", "flowerbed", "village_green") or t.get("leisure") in ("park", "garden"):
            cname = "Lawn"
        elif t.get("natural") in ("wood", "scrub") or t.get("landuse") == "forest":
            cname = "Trees_Ground"
        elif t.get("landuse") == "construction":
            cname = "Bare_Soil"
        if cname is None:
            continue
        for pd in ar["polys"]:
            xy = to_xy(pd["outer"])
            if not near(xy):
                continue
            p = poly_from(pd)
            if p.area > 2:
                A[cname].append(p)
    A = {k: unary_union(v) if v else Polygon() for k, v in A.items()}
    # other waterways (outside street corridors)
    wlines = []
    for ln in D["lines"]:
        t = ln["tags"]; ww = t.get("waterway")
        if ww in ("canal", "river", "ditch", "drain", "stream") and t.get("tunnel") not in ("culvert", "yes"):
            xy = to_xy(ln["pts"])
            if len(xy) < 2 or not near(xy):
                continue
            w = num(t.get("width")) or {"river": 12, "canal": 6, "stream": 3, "drain": 1.2, "ditch": 0.8}[ww]
            wlines.append((LineString(xy), w, ww))
    street_corr = unary_union([CW.buffer(6.0)]) if not CW.is_empty else Polygon()
    chan = []
    for l, w, ww in wlines:
        g = l.buffer(w / 2, cap_style="flat")
        if ww in ("ditch", "drain"):
            g = g.difference(street_corr)
            ARYK = ARYK.union(g)
        else:
            chan.append(g)
    # riverbank / water areas touching a river or canal line belong to the channel as well
    CHAN = unary_union(chan) if chan else Polygon()
    if not CHAN.is_empty and not A["Water"].is_empty:
        parts_w = [g for g in getattr(A["Water"], "geoms", [A["Water"]])]
        on_chan = [g for g in parts_w if g.intersects(CHAN.buffer(2))]
        off_chan = [g for g in parts_w if not g.intersects(CHAN.buffer(2))]
        CHAN = unary_union([CHAN] + on_chan)
        A["Water"] = unary_union(off_chan) if off_chan else Polygon()
    if not CHAN.is_empty:
        # clean outline (OSM line buffers + riverbank polygons are ragged), then a trapezoid section:
        # sloped concrete lining inside the outline, water in the middle
        CHAN = shapely.simplify(CHAN.buffer(3.0, quad_segs=8).buffer(-3.0, quad_segs=8), 0.4)
    INNER = CHAN.buffer(-BANK_W, quad_segs=8) if not CHAN.is_empty else Polygon()
    BANK = CHAN.difference(INNER) if not CHAN.is_empty else Polygon()
    global CHAN_G, CHAN_OUT
    CHAN_OUT = CHAN
    CHAN = INNER
    CHAN_G = CHAN
    log("areas/paths done")

    # --- vegetation from Sentinel-2 (actual ground truth, separated from tree canopy)
    #   leaf-off scene (28 Mar 2026): deciduous trees bare, lawns already green -> ground vegetation
    #   summer scene (16 Jul 2026): lawns + canopy -> canopy = summer green that is not ground green
    GROUND_VEG = Polygon(); CANOPY = Polygon()
    s2s = os.path.join(ROOT, "data", "s2_zone_2500m.npz")
    s2p = os.path.join(ROOT, "data", "s2_zone_spring.npz")
    S2C = None
    if CITY and os.path.exists(os.path.join(ROOT, "data", "s2_city.npz")):
        # city tile: one 10 m stack for the whole city (05d), cropped to this tile + margin
        zc = np.load(os.path.join(ROOT, "data", "s2_city.npz"))
        E_ul, N_ul, pxs = [float(v) for v in zc["geo"]]
        m_ = MARGIN + 60
        c0 = max(0, int((geo.E0 + (TBOX[0] - m_) * geo.KS - E_ul) / pxs)); c1 = int((geo.E0 + (TBOX[2] + m_) * geo.KS - E_ul) / pxs) + 1
        r0 = max(0, int((N_ul - (geo.N0 + (TBOX[3] + m_) * geo.KS)) / pxs)); r1 = int((N_ul - (geo.N0 + (TBOX[1] - m_) * geo.KS)) / pxs) + 1
        S2C = {k: zc[k][r0:r1, c0:c1].astype(np.float32) for k in zc.files if k != "geo"}
        S2C_GEO = [E_ul + c0 * pxs, N_ul - r0 * pxs, pxs]
        nd = lambda b4, b8: (b8 - b4) / (b8 + b4 + 1e-6)
        n_sum = nd(S2C["20260716_B04"], S2C["20260716_B08"]); n_off = nd(S2C["20260328_B04"], S2C["20260328_B08"])
        GROUND_VEG = mask_to_poly(n_off > 0.22, S2C_GEO)
        CANOPY = mask_to_poly(n_sum > 0.42, S2C_GEO)
        CANOPY_G = CANOPY
        log("city S2: ground veg m2", round(GROUND_VEG.area), "canopy m2", round(CANOPY.area))
    elif os.path.exists(s2s) and os.path.exists(s2p):
        zs = np.load(s2s); zp_ = np.load(s2p)
        nd = lambda b4, b8: (b8.astype(np.float32) - b4.astype(np.float32)) / (b8.astype(np.float32) + b4.astype(np.float32) + 1e-6)
        n_sum = nd(zs["B04"], zs["B08"])
        n_off = nd(zp_["20260328_B04"], zp_["20260328_B08"])
        geo_ = [float(v) for v in zs["B04_geo"]]
        GROUND_VEG = mask_to_poly(n_off > 0.22, geo_)
        CANOPY = mask_to_poly(n_sum > 0.42, geo_)
        CANOPY_G = CANOPY
        log("ground veg m2", round(GROUND_VEG.area), "canopy m2", round(CANOPY.area))
    # SHEF: two seasons (September 2026 + January 2026 snow) decide lawn vs bare ground vs hard ground
    SEAS_SOIL = Polygon(); SEAS_HARD = Polygon()
    s2x = os.path.join(ROOT, "data", "s2_zone_seasons.npz")
    if S2C is not None or os.path.exists(s2x):
        try:
            if S2C is not None:
                gx = S2C_GEO
                ndv_sep = (S2C["20260914_B08"] - S2C["20260914_B04"]) / (S2C["20260914_B08"] + S2C["20260914_B04"] + 1e-6)
                b11 = S2C["20260124_B11"]; b03 = S2C["20260124_B03"]
            else:
                zx = np.load(s2x)
                f = lambda k: zx[k].astype(np.float32)
                gx = [float(v) for v in zx["20260914_B04_geo"]]
                ndv_sep = (f("20260914_B08") - f("20260914_B04")) / (f("20260914_B08") + f("20260914_B04") + 1e-6)
                b11 = f("20260124_B11"); b11 = np.kron(b11, np.ones((2, 2), np.float32))[:ndv_sep.shape[0], :ndv_sep.shape[1]]
                b03 = f("20260124_B03")[:b11.shape[0], :b11.shape[1]]
            ndsi_jan = (b03 - b11) / (b03 + b11 + 1e-6)
            ndv_sep = ndv_sep[:ndsi_jan.shape[0], :ndsi_jan.shape[1]]
            green_sep = ndv_sep > 0.30
            snow_jan = ndsi_jan > 0.40
            # lawn = green in September (or snow-covered soft ground that is green in September)
            SEP_GREEN = mask_to_poly(green_sep, gx)
            # not green in September: snow lay on it in January -> unpaved (soil / dry grass); snow-free -> hard
            SEAS_SOIL = mask_to_poly((~green_sep) & snow_jan, gx)
            SEAS_HARD = mask_to_poly((~green_sep) & (~snow_jan), gx)
            veg0 = GROUND_VEG.area
            SEPG = SEP_GREEN.buffer(5.0)
            # what was taken for lawn but is NOT green in September = dry / bare ground (dirt fields, pitches, lots)
            DRY = unary_union([GROUND_VEG, A["Lawn"]]).difference(SEPG)
            if not CANOPY.is_empty:
                DRY = DRY.difference(CANOPY)
            DRY = DRY.buffer(-2.0).buffer(2.0)
            SEAS_HARD = DRY.intersection(SEAS_HARD.buffer(3.0))      # snow-free in January -> hard ground
            SEAS_SOIL = DRY.difference(SEAS_HARD)                    # snow-covered in January -> soil
            GROUND_VEG = GROUND_VEG.intersection(SEPG)
            A["Lawn"] = A["Lawn"].difference(DRY)
            log("seasons Sep/Jan: lawn m2 before", round(veg0), "after", round(GROUND_VEG.area),
                "-> bare soil m2", round(SEAS_SOIL.area), "-> hard m2", round(SEAS_HARD.area))
        except Exception as e:
            log("seasons failed", e)
    VEG = GROUND_VEG
    TREEGROUND = CANOPY.difference(GROUND_VEG) if not CANOPY.is_empty else Polygon()

    # ------------------------------------------------------ manual edits traced from close imagery (tile pass)
    MAN = []
    mp = os.path.join(ROOT, "data", "manual_edits.json")
    if os.path.exists(mp):
        for e in json.load(open(mp, encoding="utf-8")).get("edits", []):
            if e.get("class") in CID and len(e.get("poly", [])) >= 3:
                g = Polygon(e["poly"]).buffer(0)
                if not g.is_empty:
                    MAN.append((e["class"], g))
        log("manual edits", len(MAN))

    # ------------------------------------------------------ yard / street details
    PATHS_U = unary_union(paths["Path_Paving"] + paths["Cycleway"]) if (paths["Path_Paving"] or paths["Cycleway"]) else Polygon()
    major_lines = [LineString(xy) for t, xy in roads if t.get("highway") not in ("service", "track")]
    jmaj = []
    if major_lines:
        tr_ = STRtree(major_lines)
        for p in jpts:
            if len(tr_.query(p.buffer(0.5), predicate="intersects")) >= 2:
                jmaj.append(p)
    global MAN_PARKING
    MAN_PARKING = unary_union([g for c, g in MAN if c in ("Parking_Asphalt", "Parking_Lane")]) if MAN else Polygon()
    DET = yard_details(roads, overrides, CW, SW, PATHS_U, GROUND_VEG, bpolys, A, XW, jmaj, zone)

    houses = [p for p in bpolys if p.area < 350]
    HOUSEBUF = unary_union([p.buffer(25) for p in houses]) if houses else Polygon()
    apt = [p for p in bpolys if p.area >= 350]
    APTBUF = unary_union([p.buffer(30) for p in apt]) if apt else Polygon()
    # SHEF E1 (corrected by SHEF): under the trees of apartment-block yards the ground is lawn (green), not soil.
    # The yard is too green only where hard surfaces (driveways, parking, paths, courts) were missed -> those come
    # from the close-imagery tiles (data/tiles), which win over this default.
    YARDZ = APTBUF.difference(HOUSEBUF) if not APTBUF.is_empty else Polygon()
    YARD_SOIL = Polygon()
    YARD_LAWN = CANOPY.intersection(YARDZ).buffer(0) if (not YARDZ.is_empty and not CANOPY.is_empty) else Polygon()
    if not YARD_LAWN.is_empty:
        TREEGROUND = TREEGROUND.difference(YARD_LAWN)
        log("E1 yard ground under canopy -> lawn m2", round(YARD_LAWN.area))
    # ------------------------------------------------------ priority partition
    # traced parking never covers a zebra (no parking on a crossing)
    order = [(c, g.difference(XW.buffer(0.3)) if c in ("Parking_Lane", "Parking_Asphalt") and not XW.is_empty else g)
             for c, g in MAN] + [
        ("Crosswalk", XW),
    ] + [(c, g) for c, g in TILE["alleys"] if c == "Dirt_Track"] + [
        ("Road_Marking", DET["MARK"]),
        ("Parking_Lane", DET["PLANE"]),
        ("Asphalt_Road", unary_union([CW] + [g for c, g in TILE["alleys"] if c == "Asphalt_Road"])),
        ("Curb", CURB),
        ("Sidewalk_Paving", SW),
        ("Entrance_Paving", DET["ENTR"]),
        ("Apron_Concrete", DET["APRON"]),
        ("Aryk", ARYK),
        ("Street_Green", STRIP),
        ("Path_Paving", unary_union(paths["Path_Paving"]) if paths["Path_Paving"] else Polygon()),
        ("Cycleway", unary_union(paths["Cycleway"]) if paths["Cycleway"] else Polygon()),
    ] + [(c, g) for c, g in TILE["paths"]] + [
        (c, g.difference(XW.buffer(0.3)) if c == "Parking_Asphalt" and not XW.is_empty else g)
        for c, g in sorted(TILE["areas"], key=lambda cg: 0 if cg[0] in ("Parking_Asphalt", "Playground", "Sport_Pitch") else 1)] + [
        ("Parking_Asphalt", unary_union([A["Parking_Asphalt"], DET["PARK"]])),
        ("Water_Channel", CHAN),
        ("Channel_Bank", BANK),
        ("Water", A["Water"]),
        # inside tiles traced from close imagery only the playgrounds seen there (traced areas) count
        ("Playground", unary_union([A["Playground"], DET["PLAY"].difference(unary_union(TILE.get("done", [])) if TILE.get("done") else Polygon())])),
        ("Forecourt_Paving", DET["FORE"].difference(GROUND_VEG) if not GROUND_VEG.is_empty else DET["FORE"]),
        ("Sport_Pitch", A["Sport_Pitch"]),
        ("Dirt_Track", unary_union(tracks + paths["Dirt_Track"]) if (tracks or paths["Dirt_Track"]) else Polygon()),
        ("Street_Green", OUTER),
        ("Lawn", unary_union([A["Lawn"], VEG, YARD_LAWN])),
        ("Bare_Soil", SEAS_SOIL),
        ("Yard_Hard", SEAS_HARD),
        ("Trees_Ground", unary_union([A["Trees_Ground"], TREEGROUND])),
        ("Bare_Soil", A["Bare_Soil"]),
    ]
    # SHEF E4: a house stays in its own private plot even when an apartment block is near: the plot area is
    # everything within 25 m of a house that is more than 12 m from an apartment block (was 30 m)
    APTBUF = unary_union([p.buffer(12) for p in apt]) if apt else Polygon()
    # robustness (GEOS on the PC is stricter): every layer is a valid, purely polygonal geometry
    def _clean(g):
        if g is None or g.is_empty:
            return Polygon()
        g = shapely.make_valid(g)
        polys = [p for p in getattr(g, "geoms", [g]) if p.geom_type in ("Polygon", "MultiPolygon")]
        polys = [q for p in polys for q in getattr(p, "geoms", [p]) if q.area > 0.01]
        if not polys:
            return Polygon()
        return unary_union(polys).buffer(0)
    order = [(n, _clean(g)) for n, g in order]
    order = playground_connectors(order, BUILD, HOUSEBUF.difference(APTBUF), zone)
    # SHEF E4: the private-plot zone is an explicit (lowest priority) layer, so a large block face is split at its
    # border instead of taking one class from a single interior point
    order = order + [("Private_Plot", HOUSEBUF.difference(APTBUF))]
    global ZONE_BPOLYS
    ZONE_BPOLYS = [p for p in bpolys if (p.centroid.distance(Point(0, 0)) <= RZ if not CITY else zone.contains(p.centroid))]
    return order, BUILD, zone, D, HOUSEBUF, APTBUF



def _safe_clip(g, w):
    try:
        return shapely.clip_by_rect(g, *w)
    except Exception:
        return shapely.make_valid(g).intersection(box(*w))


def playground_connectors(order, BUILD, PRIV, zone):
    """QA: a playground must be reachable on a paved surface. Where a playground touches no hard pedestrian surface,
    a 1.5 m Path_Paving connector is laid to the nearest one (sidewalk, path, cycleway, entrance, forecourt, apron or
    unclassified hard yard) if it is closer than 15 m and the straight connector crosses nothing (building, road, kerb,
    green strip, parking, aryk, water, canal, pitch, private plot). Otherwise the playground stays as it is (QA info).
    Everything is evaluated on the priority-resolved layers around each playground, i.e. what the partition produces."""
    from shapely.ops import nearest_points
    HARDN = {"Sidewalk_Paving", "Path_Paving", "Cycleway", "Entrance_Paving", "Forecourt_Paving", "Apron_Concrete", "Yard_Hard"}
    TOUCHN = HARDN | {"Crosswalk", "Curb"}      # what QA accepts as access (a connector never leads to a kerb)
    BLOCKN = {"Asphalt_Road", "Road_Marking", "Parking_Lane", "Parking_Asphalt", "Aryk", "Street_Green", "Water",
              "Water_Channel", "Channel_Bank", "Sport_Pitch", "Private_Plot", "Playground"}
    layers = [(n, g) for n, g in order if g is not None and not g.is_empty]
    pls = [g for n, g in layers if n == "Playground"]
    PLAY = unary_union(pls).intersection(zone) if pls else Polygon()
    shapely.prepare(PRIV)
    conns = []; n_touch = n_far = n_block = 0; far_block = []
    for pg in [g for g in getattr(PLAY, "geoms", [PLAY]) if g.geom_type == "Polygon" and g.area > 20]:
        x0, y0, x1, y1 = pg.bounds
        w = (x0 - PG_CONNECT_MAX - 1, y0 - PG_CONNECT_MAX - 1, x1 + PG_CONNECT_MAX + 1, y1 + PG_CONNECT_MAX + 1)
        # priority-resolved layers inside the window (first layer wins, as in arrangement_mesh)
        acc = _safe_clip(BUILD, w); eff = {}
        for n, g in layers:
            gc = _safe_clip(g, w)
            if gc.is_empty:
                continue
            e = gc.difference(acc)
            acc = unary_union([acc, gc])
            if not e.is_empty:
                eff[n] = unary_union([eff[n], e]) if n in eff else e
        pge = eff.get("Playground", Polygon()).intersection(pg.buffer(0.01))
        if pge.is_empty:
            continue
        # unclassified ground = whole arrangement faces of no layer (150 m window): Private_Plot when the
        # representative point is near houses (PRIV), else Yard_Hard (hard)
        W2 = (x0 - 150, y0 - 150, x1 + 150, y1 + 150)
        cover = unary_union([_safe_clip(g, W2) for n, g in layers] + [_safe_clip(BUILD, W2)])
        free = box(*W2).intersection(zone).difference(cover)
        yard = [g for g in getattr(free, "geoms", [free]) if g.geom_type == "Polygon" and g.area >= 20
                and g.intersects(box(*w)) and not PRIV.contains(g.representative_point())]
        tg = [eff[n] for n in HARDN if n in eff] + [_safe_clip(g, w) for g in yard]
        tgt = unary_union([t for t in tg if not t.is_empty]) if tg else Polygon()
        tgt = unary_union([g for g in getattr(tgt, "geoms", [tgt]) if g.area >= 1.0]) if not tgt.is_empty else tgt
        if tgt.is_empty:
            n_far += 1; far_block.append((round(pg.centroid.x, 1), round(pg.centroid.y, 1), "none")); continue
        tch = [eff[n] for n in TOUCHN if n in eff]
        if pge.boundary.intersection(unary_union(tch + [tgt])).length > 0.3:
            n_touch += 1; continue
        a, b = nearest_points(pge, tgt)
        d = a.distance(b)
        if d > PG_CONNECT_MAX:
            n_far += 1; far_block.append((round(pg.centroid.x, 1), round(pg.centroid.y, 1), round(d, 1))); continue
        if d < 1e-3:
            # touches a hard surface in one point only (corner): short stub outwards through that point
            cc = pge.centroid; dd = math.hypot(a.x - cc.x, a.y - cc.y) or 1.0
            ux, uy = (a.x - cc.x) / dd, (a.y - cc.y) / dd
            b = Point(a.x + ux * 0.7, a.y + uy * 0.7); d = 0.7
        else:
            ux, uy = (b.x - a.x) / d, (b.y - a.y) / d
        blk = [eff[n] for n in BLOCKN if n in eff and n != "Playground"] + [_safe_clip(BUILD, w), _safe_clip(PRIV, w)]
        pl_other = eff.get("Playground", Polygon()).difference(pg.buffer(0.05))
        blk.append(pl_other)
        chk = LineString([(a.x + ux * 0.05, a.y + uy * 0.05), (b.x - ux * 0.05, b.y - uy * 0.05)]).buffer(PG_CONNECT_W / 2 - 0.05, cap_style="flat")
        if any(chk.intersects(g) for g in blk if not g.is_empty):
            n_block += 1; far_block.append((round(pg.centroid.x, 1), round(pg.centroid.y, 1), "blocked")); continue
        # start 0.6 m inside the playground and cut back to its outline, so the path shares a real edge with it
        # (the nearest point is often a corner: a flat cap there would touch the playground in one point only)
        c = LineString([(a.x - ux * 0.6, a.y - uy * 0.6), (b.x + ux * 0.3, b.y + uy * 0.3)]).buffer(PG_CONNECT_W / 2, cap_style="flat").difference(pg)
        if not c.is_empty:
            conns.append(c)
    log("playground connectors", len(conns), "already on a hard surface", n_touch, "no hard surface within",
        PG_CONNECT_MAX, "m", n_far, "blocked", n_block, far_block[:12])
    if not conns:
        return order
    C = unary_union(conns)
    out = []; done = False
    for n, g in order:
        if n == "Path_Paving" and not done:
            g = unary_union([g, C]) if g is not None and not g.is_empty else C; done = True
        out.append((n, g))
    if not done:
        out.append(("Path_Paving", C))
    return out


FAILED_FACES = []
THIN_OK = {"Curb", "Road_Marking", "Crosswalk", "Aryk", "Channel_Bank", "Water_Channel", "__BUILDING__"}


def _triangulate(f):
    """Constrained Delaunay; if GEOS refuses the face (self-touching ring etc.) repair and retry."""
    for g in (f, shapely.make_valid(f), f.buffer(0)):
        parts = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and p.area > 1e-7]
        if not parts:
            continue
        try:
            out = []
            for p in parts:
                out += list(shapely.constrained_delaunay_triangles(p).geoms)
            if out:
                return out
        except Exception:
            continue
    # last resort: fan triangulation of the exterior (convex-ish small faces)
    try:
        cc = list(f.exterior.coords)[:-1]
        if len(cc) >= 3:
            tris = [Polygon([cc[0], cc[i], cc[i + 1]]) for i in range(1, len(cc) - 1)]
            return [t for t in tris if t.area > 1e-9 and f.buffer(1e-6).contains(t.centroid)]
    except Exception:
        pass
    return []


def _merge_slivers(faces, cls, min_area=0.5):
    """QA: tiny category islands (<0.5 m2 lawn/paving crumbs) take the class of the neighbour they share most border with."""
    small = [i for i, f in enumerate(faces) if f.area < min_area and cls[i] not in THIN_OK]
    if not small:
        return cls
    tree = STRtree(faces)
    cls = list(cls)
    changed = 0
    for i in small:
        f = faces[i]
        best, bl = None, 0.0
        for j in tree.query(f, predicate="intersects"):
            j = int(j)
            if j == i or cls[j] == "__BUILDING__" or cls[j] == cls[i]:
                continue
            L = f.boundary.intersection(faces[j].boundary).length
            if L > bl:
                best, bl = cls[j], L
        # only merge if it is really an island of its own class (no same-class neighbour)
        same = any(cls[int(j)] == cls[i] and int(j) != i and f.boundary.intersection(faces[int(j)].boundary).length > 1e-3
                   for j in tree.query(f, predicate="intersects"))
        if best is not None and not same:
            cls[i] = best; changed += 1
    log("sliver faces merged into neighbours", changed, "of", len(small))
    return cls


def _classify(faces, geoms, names):
    """Class of each face = first (highest priority) layer containing its interior point."""
    tree = STRtree(geoms)
    # QA open_chain (city T_2_1): a face with a zero-width spike running along a building wall got its interior point
    # on the spike, inside the building -> classed as building -> 8 m2 hole in the ground. The point is now taken
    # from the face's core (5 mm inward), which has no spikes.
    rps = []
    if faces:
        core = shapely.buffer(np.array(faces, dtype=object), -0.005, join_style="mitre")
        for f, c in zip(faces, core):
            if c is None or c.is_empty:
                rps.append(f.representative_point())
            else:
                if c.geom_type != "Polygon":
                    c = max(getattr(c, "geoms", [c]), key=lambda g: g.area)
                rps.append(c.representative_point())
    hit = {}
    if rps:
        inp, tre = tree.query(rps, predicate="intersects")
        for i, j in zip(inp.tolist(), tre.tolist()):
            if i not in hit or j < hit[i]:
                hit[i] = j
    return [names[hit[i]] if i in hit else None for i in range(len(faces))], rps


def arrangement_mesh(order, BUILD, zone, HOUSEBUF, APTBUF):
    """One planar arrangement of every layer border (noded once, densified once).

    Each face of the arrangement gets the highest-priority layer containing it, so
    neighbouring faces always share identical vertices -> watertight, no overlaps.
    """
    layers = []
    for n, g in order:
        if g is None or g.is_empty:
            continue
        g = shapely.make_valid(g).intersection(zone)
        if not g.is_empty:
            layers.append((n, g))
    B = BUILD.intersection(zone)
    geoms = [B] + [g for _, g in layers]
    names = ["__BUILDING__"] + [n for n, _ in layers]
    grid = []
    gx0, gy0, gx1, gy1 = TBOX
    for k in range(int(gx0 // 250) - 1, int(gx1 // 250) + 2):
        grid.append(LineString([(k * 250.0, gy0 - 10), (k * 250.0, gy1 + 10)]))
    for k in range(int(gy0 // 250) - 1, int(gy1 // 250) + 2):
        grid.append(LineString([(gx0 - 10, k * 250.0), (gx1 + 10, k * 250.0)]))
    grid = unary_union(grid).intersection(zone)
    if GRID > 0:
        noded = shapely.union_all([zone.boundary, B.boundary] + [g.boundary for _, g in layers], grid_size=GRID)
    else:
        noded = unary_union([zone.boundary, B.boundary] + [g.boundary for _, g in layers])
    noded = shapely.segmentize(noded, 12.0)
    faces = [f for f in polygonize(noded) if f.area > 1e-6]
    cls, rps = _classify(faces, geoms, names)
    cls = [c if c is not None else ("Private_Plot" if (HOUSEBUF.contains(rp) and not APTBUF.contains(rp)) else "Yard_Hard")
           for c, rp in zip(cls, rps)]
    cls = _merge_slivers(faces, cls)
    verts = {}
    V = []

    def vid(x, y):
        # QA: vertices closer than ~2 mm are one vertex (rounding to a 1 mm grid alone split pairs that
        # straddle a grid line -> degenerate triangles and open wall ends)
        k = (round(x * 1000.0), round(y * 1000.0))
        i = verts.get(k)
        if i is not None:
            return i
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                j = verts.get((k[0] + dx, k[1] + dy))
                if j is not None:
                    verts[k] = j
                    return j
        i = len(V); verts[k] = i; V.append((x, y))
        return i

    tris, tcls = [], []
    areas = {}
    keep = {"Street_Green": [], "Trees_Ground": [], "Lawn": [], "Private_Plot": [], "Bare_Soil": []}
    for f, c, rp in zip(faces, cls, rps):
        if c == "__BUILDING__":
            continue
        areas[c] = areas.get(c, 0) + f.area
        if c in keep:
            keep[c].append(f)
        cid = CID[c]
        tr = _triangulate(f)
        if not tr:
            FAILED_FACES.append((round(f.area, 2), round(rp.x, 1), round(rp.y, 1), c))
            continue
        for t in tr:
            cc = list(t.exterior.coords)[:3]
            ids = [vid(*p) for p in cc]
            if len(set(ids)) < 3:
                continue
            (x0, y0), (x1, y1), (x2, y2) = V[ids[0]], V[ids[1]], V[ids[2]]
            cr = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
            if cr < 0:
                ids = [ids[0], ids[2], ids[1]]
            tris.append(ids); tcls.append(cid)
    log("arrangement faces", len(faces), {k: round(v) for k, v in areas.items()})
    if FAILED_FACES:
        log("WARNING untriangulated faces", len(FAILED_FACES), FAILED_FACES[:10])
    final = {k: unary_union(v) for k, v in keep.items() if v}
    return np.array(V, dtype=np.float64), np.array(tris, dtype=np.int64), np.array(tcls, dtype=np.int32), areas, final


def walls_and_heights(V, T, C, dtm_sampler):
    """Split vertices per surface class height and create one wall wherever neighbouring
    surfaces differ in height (kerbs, aryks, pools). Channel banks slope from the water level
    up to the ground, so they meet both sides without walls."""
    zg = dtm_sampler(V)
    bank_id = CID["Channel_Bank"]
    dist_chan = {}
    if CHAN_OUT is not None and not CHAN_OUT.is_empty:
        outer_edge = CHAN_OUT.boundary
        shapely.prepare(outer_edge)
        bv = np.unique(T[C == bank_id].ravel()) if (C == bank_id).any() else []
        for v in bv:
            dist_chan[int(v)] = outer_edge.distance(Point(V[v][0], V[v][1]))

    def off(v, c):
        if c == bank_id:
            t = min(max(dist_chan.get(int(v), 0.0) / BANK_W, 0.0), 1.0)   # 0 at the top edge, 1 at the water edge
            return 0.15 * (1 - t) - CHAN_DEPTH * t
        if c == CID["Water_Channel"]:
            return -CHAN_DEPTH + 0.2
        return COFF[c]

    de = {}
    for tri, c in zip(T, C):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            de[(a, b)] = c
    key = {}
    outV = []

    def vc(v, c):
        o = round(off(v, c), 4)
        k = (v, o)
        i = key.get(k)
        if i is None:
            i = len(outV); key[k] = i
            outV.append((V[v][0], V[v][1], zg[v] + o))
        return i

    outT = []
    for tri, c in zip(T, C):
        outT.append([vc(tri[0], c), vc(tri[1], c), vc(tri[2], c)])
    walls, wcls = [], []
    for (a, b), c in de.items():
        other = de.get((b, a))
        if other is None:
            ra = math.hypot(V[a][0], V[a][1]); rb = math.hypot(V[b][0], V[b][1])
            if not CITY and min(ra, rb) < RZ - 0.5:
                continue  # building footprint border: hidden inside the building
            if CITY and ZONE_G.exterior.distance(Point((V[a][0] + V[b][0]) / 2, (V[a][1] + V[b][1]) / 2)) > 0.5:
                continue  # building border (not on the tile edge)
            if not ZONE_SKIRT:
                continue  # outer ring: closed by the seam ribbon in 07 (a skirt here would z-fight with it)
            ta, tb = vc(a, c), vc(b, c)
            ia = len(outV); outV.append((V[a][0], V[a][1], zg[a] - 1.5))
            ib = len(outV); outV.append((V[b][0], V[b][1], zg[b] - 1.5))
            walls.append([ta, ia, ib, tb]); wcls.append(c)
            continue
        ha = off(a, c) - off(a, other); hb = off(b, c) - off(b, other)
        if max(ha, hb) <= 1e-3 or (ha + hb) <= 0:
            continue  # same height, or this side is the lower one (the other side makes the wall)
        ta, tb = vc(a, c), vc(b, c)
        ia, ib = vc(a, other), vc(b, other)
        # quad (a_top, a_low, b_low, b_top): normal points away from the higher face
        walls.append([ta, ia, ib, tb]); wcls.append(c)
    return (np.array(outV, dtype=np.float64), np.array(outT, dtype=np.int64),
            np.array(walls, dtype=np.int64).reshape(-1, 4), np.array(wcls, dtype=np.int32))


def tree_points(parts, D, rng):
    """Trunk positions: OSM trees, street trees where canopy exists, canopy trees in yards/parks.
    Trunks only on soft ground; crowns may overhang paving (as in reality)."""
    pts = []
    canopy = CANOPY_G if CANOPY_G is not None else Polygon()
    soft = unary_union([g for g in parts.values() if g is not None and not g.is_empty])
    for n in D["nodes"]:
        if n["t"] == "natural=tree":
            q = to_xy([n["p"]])[0]
            if (math.hypot(*q) <= RZ) if not CITY else ZONE_G.contains(Point(*q)):
                pts.append((q[0], q[1], 1))
    sg = parts.get("Street_Green")
    if sg is not None and not sg.is_empty:
        cz = canopy.buffer(4.0) if not canopy.is_empty else None
        for p in getattr(sg, "geoms", [sg]):
            if p.area < 6:
                continue
            ring = p.exterior
            L = ring.length / 2
            for s_ in np.arange(3.5, L, 7.0):
                a = ring.interpolate(s_); b = ring.interpolate(ring.length - s_)
                m = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
                if not p.contains(m):
                    continue
                if cz is not None and not cz.contains(m):
                    continue
                if rng.random() < 0.9:
                    pts.append((m.x + rng.normal(0, 0.25), m.y + rng.normal(0, 0.25), 2))
    if not canopy.is_empty:
        area = canopy.intersection(soft)
        for cname, spacing, prob in (("Trees_Ground", 6.5, 0.85), ("Bare_Soil", 6.5, 0.85), ("Lawn", 8.0, 0.6)):
            g = parts.get(cname)
            if g is None or g.is_empty:
                continue
            g = g.intersection(area).buffer(-1.0)
            if g.is_empty:
                continue
            minx, miny, maxx, maxy = g.bounds
            xs = np.arange(minx, maxx, spacing); ys = np.arange(miny, maxy, spacing)
            shapely.prepare(g)
            for x in xs:
                for y in ys:
                    c = Point(x + rng.uniform(-spacing / 3, spacing / 3), y + rng.uniform(-spacing / 3, spacing / 3))
                    if rng.random() < prob and g.contains(c):
                        pts.append((c.x, c.y, 3))
    # QA: trunks must stand on soft ground (lawn, street green strip, tree ground, private garden) at least
    # 0.35 m from its edge. Trunks that landed on asphalt / kerb / sidewalk are moved to the nearest soft
    # ground within 3 m, otherwise dropped.
    from shapely.ops import nearest_points
    inner = soft.buffer(-0.35)
    shapely.prepare(inner)
    out, moved, dropped = [], 0, 0
    for x, y, t in pts:
        p = Point(x, y)
        if inner.contains(p):
            out.append((x, y, t)); continue
        if inner.is_empty:
            dropped += 1; continue
        d = inner.distance(p)
        if d <= 3.0:
            q = nearest_points(inner, p)[0]
            out.append((q.x, q.y, t)); moved += 1
        else:
            dropped += 1
    # keep trunks at least 2.5 m apart after moving
    if out:
        arr = np.array(out)
        keep = np.ones(len(arr), bool)
        cell = {}
        for i, (x, y, t) in enumerate(arr):
            k = (int(x // 2.5), int(y // 2.5))
            clash = False
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in cell.get((k[0] + dx, k[1] + dy), []):
                        if (arr[j, 0] - x) ** 2 + (arr[j, 1] - y) ** 2 < 2.5 ** 2:
                            clash = True
            if clash:
                keep[i] = False
            else:
                cell.setdefault(k, []).append(i)
        out = [tuple(r) for r in arr[keep]]
    log("trees: moved onto soft ground", moved, "dropped", dropped, "kept", len(out))
    return np.array(out, dtype=np.float64).reshape(-1, 3)


def main():
    order, BUILD, zone, D, HB, AB = build()
    globals()["zone"] = zone
    V, T, C, areas, parts = arrangement_mesh(order, BUILD, zone, HB, AB)
    log("planar mesh", len(V), "verts", len(T), "tris")
    z = np.load(os.path.join(ROOT, "data", "dtm_crop.npz"))
    dem = geo.DEM(z["dtm"], float(z["lon_min_edge"]), float(z["lat_max_edge"]), float(z["d"]), float(z["d"]))
    kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0

    def sampler(XY):
        XY = np.asarray(XY)
        lon = geo.LON0 + XY[:, 0] / kx; lat = geo.LAT0 + XY[:, 1] / ky
        for _ in range(6):
            cx, cy = geo.to_local(lon, lat)
            lon = lon + (XY[:, 0] - cx) / kx; lat = lat + (XY[:, 1] - cy) / ky
        return dem.sample(lon, lat)

    OV, OT, W, WC = walls_and_heights(V, T, C, sampler)
    # --- private plot walls (duval) along the street side of private plots, with gate gaps
    street_side = {CID[n] for n in ("Sidewalk_Paving", "Street_Green", "Asphalt_Road", "Curb", "Path_Paving", "Aryk", "Dirt_Track")}
    de = {}
    for tri, c in zip(T, C):
        for a_, b_ in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            de[(a_, b_)] = c
    segs = []
    for (a_, b_), c in de.items():
        if c != CID["Private_Plot"]:
            continue
        o = de.get((b_, a_))
        if o is not None and o in street_side:
            segs.append((a_, b_))
    # chain segments so gates can be cut at realistic spacing
    rng = np.random.default_rng(11)
    PW = []
    for a_, b_ in segs:
        pa, pb = V[a_], V[b_]
        L = float(np.hypot(*(pb - pa)))
        if L < 0.3:
            continue
        # random gate: skip ~3.5 m every ~20 m on average
        n = max(1, int(L // 3.5))
        for k in range(n):
            t0, t1 = k / n, (k + 1) / n
            if rng.random() < 3.5 / 20.0 * (L / n) / 3.5 * 0.9:
                continue
            PW.append((*(pa + (pb - pa) * t0), *(pa + (pb - pa) * t1)))
    # SHEF E4: traced plot fences (duval) replace the generated street-side walls inside tiles that have fences
    if TILE["fences"]:
        fence_tiles = [box(*b) for n, b in TILE["tiles"] if b and any(box(*b).intersects(f) for f in TILE["fences"])]
        FT = unary_union(fence_tiles) if fence_tiles else Polygon()
        PW = [w for w in PW if not FT.contains(Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))]
        street = unary_union([g for n, g in order if n in ("Asphalt_Road", "Sidewalk_Paving", "Dirt_Track")])
        BLD = unary_union(ZONE_BPOLYS) if ZONE_BPOLYS else Polygon()
        for f in TILE["fences"]:
            f = f.difference(BLD.buffer(0.2))
            for ln in getattr(f, "geoms", [f]):
                if ln.geom_type != "LineString":
                    continue
                cc = list(ln.coords)
                for a_, b_ in zip(cc[:-1], cc[1:]):
                    seg = LineString([a_, b_]); L = seg.length
                    if L < 0.2:
                        continue
                    mid = seg.interpolate(0.5, normalized=True)
                    gate = L > 8 and street.distance(mid) < 4.0   # one 3.5 m gate on each street-facing fence side
                    if gate:
                        t0 = max(0.0, 0.5 - 1.75 / L); t1 = min(1.0, 0.5 + 1.75 / L)
                        parts_ = [(0.0, t0), (t1, 1.0)]
                    else:
                        parts_ = [(0.0, 1.0)]
                    for u0, u1 in parts_:
                        p0 = seg.interpolate(u0, normalized=True); p1 = seg.interpolate(u1, normalized=True)
                        if p0.distance(p1) > 0.2:
                            PW.append((p0.x, p0.y, p1.x, p1.y))
        log("traced fences -> wall segments; tiles with fences", len(fence_tiles))
    # SHEF E4: every private house gets its own walled plot: plot boundaries = Voronoi edges between the houses
    # of a block, clipped to the private-plot ground (traced fences take over inside tiles that have them)
    try:
        pid = CID["Private_Plot"]
        Tn = np.asarray(T); Cn = np.asarray(C); Vn = np.asarray(V)
        tri_pp = shapely.polygons(Vn[Tn[Cn == pid]]) if (Cn == pid).any() else []
        try:
            PRIV = shapely.coverage_union_all(tri_pp) if len(tri_pp) else Polygon()   # fast: triangles form a coverage
        except Exception:
            PRIV = unary_union([p.buffer(0.01) for p in tri_pp]).buffer(-0.01) if len(tri_pp) else Polygon()
        FTz = unary_union([box(*b) for n, b in TILE["tiles"] if b and any(box(*b).intersects(f) for f in TILE["fences"])]) if TILE["fences"] else Polygon()
        PRIV2 = PRIV.buffer(2.0); shapely.prepare(PRIV2)       # (was re-buffered for every building: slow)
        hs = [p for p in ZONE_BPOLYS if p.area < 350 and PRIV2.intersects(p)]
        n_before = len(PW)
        if len(hs) >= 2 and not PRIV.is_empty:
            cents = shapely.MultiPoint([p.centroid for p in hs])
            vor = shapely.voronoi_polygons(cents, extend_to=PRIV.envelope.buffer(50))
            edges = unary_union([g.boundary for g in vor.geoms])
            BLDU = unary_union(hs).buffer(0.6)
            inner = PRIV.buffer(-0.4)
            edges = edges.intersection(inner).difference(BLDU)
            if not FTz.is_empty:
                edges = edges.difference(FTz)
            for ln in getattr(edges, "geoms", [edges]):
                if ln.geom_type != "LineString" or ln.length < 1.5:
                    continue
                cc = list(ln.coords)
                for a_, b_ in zip(cc[:-1], cc[1:]):
                    if math.hypot(b_[0] - a_[0], b_[1] - a_[1]) > 0.2:
                        PW.append((a_[0], a_[1], b_[0], b_[1]))
        # close the plots: the outer border of the private-plot zone near houses also gets a wall where no wall
        # (street frontage or traced fence) is there yet
        if os.environ.get("BISHKEK_OUTER_WALLS") == "1" and len(hs) and not PRIV.is_empty:
            # (off by default - SHEF: landscape first, walls second) fast version: test ~2 m pieces of the plot-zone border with spatial indexes (no big unions)
            wall_lines = shapely.linestrings([[(w[0], w[1]), (w[2], w[3])] for w in PW]) if PW else np.array([])
            tW_ = STRtree(wall_lines) if len(wall_lines) else None
            st_geoms = [g for n, g in order if n in ("Asphalt_Road", "Sidewalk_Paving", "Street_Green", "Curb", "Aryk",
                                                    "Dirt_Track", "Path_Paving", "Crosswalk") and g is not None and not g.is_empty]
            st_parts = [p for g in st_geoms for p in getattr(g, "geoms", [g])]
            tS_ = STRtree(st_parts) if st_parts else None
            tH_ = STRtree(hs)
            border = PRIV.boundary
            if not FTz.is_empty:
                border = border.difference(FTz)
            pieces = []
            for ln in getattr(border, "geoms", [border]):
                if ln.geom_type != "LineString":
                    continue
                ln = shapely.segmentize(ln, 2.0)
                cc = list(ln.coords)
                pieces += [(a_, b_) for a_, b_ in zip(cc[:-1], cc[1:])]
            if pieces:
                mids = shapely.points([((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2) for a_, b_ in pieces])
                keep = np.ones(len(pieces), bool)
                near_house = np.zeros(len(pieces), bool)
                ii, _ = tH_.query(mids, predicate="dwithin", distance=25.0); near_house[ii] = True
                keep &= near_house
                ii, _ = tH_.query(mids, predicate="dwithin", distance=0.6); keep[ii] = False
                if tW_ is not None:
                    ii, _ = tW_.query(mids, predicate="dwithin", distance=1.0); keep[ii] = False
                if tS_ is not None:
                    ii, _ = tS_.query(mids, predicate="dwithin", distance=0.8); keep[ii] = False
                n_o = 0
                for k_ in np.nonzero(keep)[0]:
                    a_, b_ = pieces[k_]
                    if math.hypot(b_[0] - a_[0], b_[1] - a_[1]) > 0.2:
                        PW.append((a_[0], a_[1], b_[0], b_[1])); n_o += 1
            log("E4 outer plot border walls", n_o)
        log("E4 plot walls between houses: segments", len(PW) - n_before, "houses", len(hs))
    except Exception as e:
        log("E4 plot split failed", e)
    # SHEF: a wall never stands on a road, sidewalk, kerb, aryk or street green strip (traced lines can be a few
    # metres off) -> those parts are cut away from every wall segment
    try:
        NOWALL = unary_union([g for n, g in order if n in ("Asphalt_Road", "Road_Marking", "Crosswalk", "Parking_Lane", "Curb",
                                                          "Sidewalk_Paving", "Street_Green", "Aryk", "Dirt_Track", "Cycleway",
                                                          "Parking_Asphalt", "Water_Channel", "Channel_Bank") and g is not None and not g.is_empty])
        # + the FINAL street triangles (sliver merging / layer priority can move ground into a street class; QA 12b
        # checks the final mesh) - city run: wall_on_street
        st_ids = [CID[n] for n in ("Asphalt_Road", "Road_Marking", "Crosswalk", "Parking_Lane", "Curb", "Sidewalk_Paving",
                                   "Street_Green", "Aryk") if n in CID]
        # (checked per wall piece with a spatial index - a union of all street triangles was far too slow for the zone)
        tri_st = shapely.polygons(V[T[np.isin(C, st_ids)]][:, :, :2]) if len(T) else np.array([])
        tST = STRtree(tri_st) if len(tri_st) else None
        NOWALL = NOWALL.buffer(0.15)
        shapely.prepare(NOWALL)
        PW2 = []; n_cut = 0
        for w in PW:
            seg = LineString([(w[0], w[1]), (w[2], w[3])])
            hit = tST.query(seg, predicate="dwithin", distance=0.15) if tST is not None else []
            if not NOWALL.intersects(seg) and not len(hit):
                PW2.append(w); continue
            n_cut += 1
            cut_ = NOWALL
            if len(hit):
                cut_ = unary_union([NOWALL.intersection(seg.buffer(1.0))] + [t.buffer(0.15) for t in tri_st[hit]])
            rest = seg.difference(cut_)
            for ln in getattr(rest, "geoms", [rest]):
                if ln.geom_type == "LineString" and ln.length > 0.4:
                    c0, c1 = ln.coords[0], ln.coords[-1]
                    PW2.append((c0[0], c0[1], c1[0], c1[1]))
        PW = PW2
        log("walls cut where they touched a road / sidewalk / kerb / aryk / green strip:", n_cut)
    except Exception as e:
        log("E4 plot split failed", e)
    PW = np.array(PW, dtype=np.float64).reshape(-1, 4)
    if len(PW):
        za = sampler(PW[:, 0:2]) + 0.15; zb = sampler(PW[:, 2:4]) + 0.15
        PW = np.column_stack([PW, za, zb])
    log("plot wall segments", len(PW))
    ang = np.zeros(len(T), dtype=np.float32)
    for cname, lines_ in (("Crosswalk", XW_LINES), ("Parking_Lane", XW_LINES), ("Parking_Asphalt", ALL_LINES)):
        xi = np.nonzero(C == CID[cname])[0]
        if not len(xi) or not lines_:
            continue
        tr = STRtree(lines_)
        for i in xi:
            cx, cy = V[T[i]].mean(0)
            p = Point(cx, cy); ln = lines_[tr.nearest(p)]
            sp = ln.project(p); a = ln.interpolate(max(sp - 1, 0)); b = ln.interpolate(min(sp + 1, ln.length))
            ang[i] = math.atan2(b.y - a.y, b.x - a.x)
    log("with walls", len(OV), "verts", len(OT), "tris", len(W), "walls")
    rng = np.random.default_rng(7)
    TP = tree_points(parts, D, rng)
    if len(TP):
        TZ = sampler(TP[:, :2]) + 0.12
        TP = np.column_stack([TP[:, :2], TZ, TP[:, 2]])
    log("trees", len(TP))
    np.savez_compressed(os.path.join(OUTDIR, "zone_partition.npz"), V=OV, T=OT, TC=C, W=W, WC=WC, TREES=TP, XA=ang, PW=PW,
                        classes=json.dumps(CLASSES), rz=RZ)
    fp = []
    for p in ZONE_BPOLYS:
        for g in getattr(p, "geoms", [p]):
            if g.geom_type == "Polygon":
                fp.append({"outer": [list(c) for c in g.exterior.coords], "inner": [[list(c) for c in r.coords] for r in g.interiors]})
    json.dump(fp, open(os.path.join(OUTDIR, "zone_footprints_local.json"), "w"))
    # every opening the ground has for buildings (incl. buildings that cross the ring and keep their 35 km model):
    # QA / repair treat these outlines as intended boundaries
    holes = []
    Bz = BUILD.intersection(zone)
    for g in getattr(Bz, "geoms", [Bz]):
        if g.geom_type == "Polygon" and g.area > 0.01:
            holes.append({"outer": [[round(a, 4), round(b, 4)] for a, b in g.exterior.coords],
                          "inner": [[[round(a, 4), round(b, 4)] for a, b in r.coords] for r in g.interiors]})
    json.dump(holes, open(os.path.join(OUTDIR, "zone_ground_holes.json"), "w"))
    json.dump([list(c) for c in zone.exterior.coords], open(os.path.join(OUTDIR, "zone_ring.json"), "w"))
    areas = {k: round(v) for k, v in areas.items()}
    json.dump(areas, open(os.path.join(OUTDIR, "zone_partition_areas.json"), "w"), indent=1)
    log("robust overlay retries", ROBUST_FIXES["n"])
    log("DONE")


if __name__ == "__main__":
    main()
