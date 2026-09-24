"""Build the Bishkek 35 km LOD1 context model in (headless) Blender.

Run:  blender.exe -b --factory-startup --python 02_build_model.py
Inputs : ROOT/data/dem/*.tif (Copernicus GLO-30), ROOT/data/osm/extract/*.json
Output : ROOT/Bishkek_35km.blend, ROOT/data/dtm_local.npz, ROOT/logs/02_build.log
Units  : metres. X east, Y north, Z = metres above sea level.
CRS    : UTM 43N (EPSG:32643) shifted to the site and scale-corrected (see geo.py).
"""
import os, sys, json, math, time, re

ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "pylibs")):
    if p not in sys.path:
        sys.path.append(p)

import numpy as np
import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon
import geo

TEST_RADIUS = float(os.environ.get("BISHKEK_TEST_RADIUS", "0"))  # >0 = small test build
R = TEST_RADIUS or geo.RADIUS
TILE = 5000.0
FINE_R = 12000.0          # terrain at ~30 m inside this radius, ~60 m outside
LOG_PATH = os.path.join(ROOT, "logs", "02_build.log")
T0 = time.time()


def log(*a):
    msg = f"[{time.time() - T0:7.1f}s] " + " ".join(str(x) for x in a)
    print(msg, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


# ----------------------------------------------------------------------------- DEM
def load_dem():
    import tifffile
    d = 1.0 / 3600.0
    lon_a, lon_b = geo.LON0 - 0.5, geo.LON0 + 0.5
    lat_a, lat_b = geo.LAT0 - 0.37, geo.LAT0 + 0.37
    tiles = {}
    for lat in (42, 43):
        for lon in (74, 75):
            name = f"Copernicus_DSM_COG_10_N{lat}_00_E{lon:03d}_00_DEM"
            tiles[(lat, lon)] = tifffile.imread(os.path.join(ROOT, "data", "dem", name + ".tif"))
    mosaic = np.vstack([np.hstack([tiles[(43, 74)], tiles[(43, 75)]]),
                        np.hstack([tiles[(42, 74)], tiles[(42, 75)]])]).astype(np.float32)
    # PixelIsPoint: pixel (0,0) centre = (74.0, 44.0)
    c0 = int((lon_a - 74.0) / d); c1 = int((lon_b - 74.0) / d) + 1
    r0 = int((44.0 - lat_b) / d); r1 = int((44.0 - lat_a) / d) + 1
    dsm = mosaic[r0:r1, c0:c1].copy()
    lon_min_edge = 74.0 + c0 * d - 0.5 * d
    lat_max_edge = 44.0 - r0 * d + 0.5 * d
    log("DEM crop", dsm.shape, "min/max", float(dsm.min()), float(dsm.max()))
    dtm = geo.dsm_to_dtm(dsm)
    np.savez_compressed(os.path.join(ROOT, "data", "dtm_crop.npz"), dtm=dtm, dsm=dsm,
                        lon_min_edge=lon_min_edge, lat_max_edge=lat_max_edge, d=d)
    return geo.DEM(dtm, lon_min_edge, lat_max_edge, d, d), geo.DEM(dsm, lon_min_edge, lat_max_edge, d, d)


def local_to_lonlat(x, y):
    """Inverse of geo.to_local by fixed-point iteration (mm accuracy)."""
    x = np.asarray(x, dtype=np.float64); y = np.asarray(y, dtype=np.float64)
    kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0
    lon = geo.LON0 + x / kx; lat = geo.LAT0 + y / ky
    for _ in range(6):
        cx, cy = geo.to_local(lon, lat)
        lon = lon + (x - cx) / kx
        lat = lat + (y - cy) / ky
    return lon, lat


# ----------------------------------------------------------------------- scene utils
def get_col(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col


def get_mat(name, rgb, rough=0.8):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        if b:
            b.inputs["Base Color"].default_value = (*rgb, 1.0)
            b.inputs["Roughness"].default_value = rough
        m.diffuse_color = (*rgb, 1.0)
    return m


def make_obj(name, verts, faces, col, mat=None, face_attrs=None):
    if not faces:
        return None
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate(clean_customdata=False)
    if face_attrs:
        for an, (atype, vals) in face_attrs.items():
            if len(vals) != len(me.polygons):
                continue
            a = me.attributes.new(an, atype, "FACE")
            a.data.foreach_set("value", vals)
    me.update()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    if mat:
        me.materials.append(mat)
    return ob


def tile_key(x, y):
    return (int(math.floor(x / TILE)), int(math.floor(y / TILE)))


def tname(prefix, k):
    return f"{prefix}_{k[0]:+03d}_{k[1]:+03d}"


# --------------------------------------------------------------------------- terrain
def build_terrain(dtm):
    col = get_col("01_Terrain")
    mat = get_mat("M_Terrain", (0.34, 0.31, 0.26), 0.95)
    n = int(math.ceil(R / TILE))
    total = 0
    for ix in range(-n, n):
        for iy in range(-n, n):
            x0, y0 = ix * TILE, iy * TILE
            # nearest point of tile to origin
            nx = min(max(0.0, x0), x0 + TILE); ny = min(max(0.0, y0), y0 + TILE)
            if math.hypot(nx, ny) > R:
                continue
            cx, cy = x0 + TILE / 2, y0 + TILE / 2
            step = 30.0 if math.hypot(cx, cy) - TILE * 0.71 < FINE_R else 60.0
            m = int(round(TILE / step))
            xs = x0 + np.arange(m + 1) * step
            ys = y0 + np.arange(m + 1) * step
            gx, gy = np.meshgrid(xs, ys)
            lon, lat = local_to_lonlat(gx.ravel(), gy.ravel())
            z = dtm.sample(lon, lat).reshape(gx.shape)
            idx = np.arange((m + 1) * (m + 1)).reshape(m + 1, m + 1)
            a = idx[:-1, :-1].ravel(); b = idx[:-1, 1:].ravel(); c = idx[1:, 1:].ravel(); d = idx[1:, :-1].ravel()
            fcx = (gx[:-1, :-1] + step / 2).ravel(); fcy = (gy[:-1, :-1] + step / 2).ravel()
            keep = np.hypot(fcx, fcy) <= R + step
            quads = np.stack([a, b, c, d], 1)[keep]
            verts = np.stack([gx.ravel(), gy.ravel(), z.ravel()], 1)
            # skirt: drop the outer ring of the tile 25 m to hide cracks between resolutions
            border = np.concatenate([idx[0, :], idx[1:, -1], idx[-1, -2::-1], idx[-2:0:-1, 0]])
            nv = len(verts)
            sk = verts[border].copy(); sk[:, 2] -= 25.0
            verts = np.vstack([verts, sk])
            nb = len(border)
            skirt = [(int(border[i]), int(nv + i), int(nv + (i + 1) % nb), int(border[(i + 1) % nb])) for i in range(nb)]
            faces = [tuple(map(int, q)) for q in quads] + skirt
            make_obj(tname("Terrain", (ix, iy)), verts.tolist(), faces, col, mat)
            total += len(verts)
    log("terrain verts", total)


# ------------------------------------------------------------------------- buildings
LEVEL_H = 3.0
LOW = {"garage", "garages", "shed", "kiosk", "hut", "carport", "roof", "service", "toilets", "cabin",
       "greenhouse", "container", "barn", "stable", "shelter", "transformer_tower", "bunker", "sty", "gatehouse"}
HOUSE = {"house", "detached", "semidetached_house", "bungalow", "terrace", "farm", "villa", "dacha"}


def _num(v):
    if v is None:
        return None
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


def building_height(tags, area):
    """Return (height_m, min_height_m, levels, source) where source 0=height tag,1=levels,2=estimate."""
    h = _num(tags.get("height")); mh = _num(tags.get("min_height")) or 0.0
    lv = _num(tags.get("building:levels"))
    if mh == 0.0 and _num(tags.get("building:min_level")):
        mh = _num(tags.get("building:min_level")) * LEVEL_H
    if h and 1.5 <= h <= 400:
        return h, mh, (lv or max(1, round(h / LEVEL_H))), 0
    if lv and 0 < lv <= 100:
        rl = _num(tags.get("roof:levels")) or 0
        return lv * LEVEL_H + rl * 1.5 + 0.6, mh, lv, 1
    b = tags.get("building", "yes")
    if b in LOW:
        lv = 1; hh = 3.0
    elif b in HOUSE:
        lv = 1 if area < 220 else 2; hh = lv * LEVEL_H + 1.5
    elif b == "apartments":
        lv = 5 if area < 1800 else 9; hh = lv * LEVEL_H + 0.6
    elif b in ("industrial", "warehouse", "manufacture", "hangar"):
        lv = 1; hh = 8.0
    elif b in ("commercial", "retail", "office", "supermarket"):
        lv = 2 if area < 2500 else 3; hh = lv * 3.6
    elif b in ("school", "kindergarten"):
        lv = 3 if b == "school" else 2; hh = lv * 3.5
    elif b in ("university", "college", "hospital", "public", "civic", "government"):
        lv = 4; hh = lv * 3.5
    elif b in ("mosque", "church", "cathedral", "temple", "religious"):
        lv = 1; hh = 12.0
    elif b in ("construction",):
        lv = 1; hh = 3.0
    else:  # yes / residential / unknown
        if area < 150: lv = 1
        elif area < 400: lv = 2
        elif area < 1200: lv = 3
        else: lv = 5
        hh = lv * LEVEL_H + (1.2 if lv <= 2 else 0.6)
    return hh, mh, lv, 2


def ring_area(xy):
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def clean_ring(pts):
    a = np.asarray(pts, dtype=np.float64)
    if len(a) > 1 and np.allclose(a[0], a[-1]):
        a = a[:-1]
    if len(a) < 3:
        return None
    x, y = geo.to_local(a[:, 0], a[:, 1])
    xy = np.stack([x, y], 1)
    # drop consecutive duplicates
    keep = np.ones(len(xy), bool)
    keep[1:] = np.hypot(*(xy[1:] - xy[:-1]).T) > 0.01
    xy = xy[keep]
    if len(xy) < 3:
        return None
    return xy, a[keep]


def build_buildings(dtm, items, colname, prefix, mat):
    col = get_col(colname)
    buckets = {}
    n_ok = 0
    for b in items:
        tags = b.get("tags", {})
        for poly in b["polys"]:
            o = clean_ring(poly["outer"])
            if o is None:
                continue
            oxy, oll = o
            A = ring_area(oxy)
            if A < 0:
                oxy = oxy[::-1]; oll = oll[::-1]
            area = abs(A)
            if area < 4.0:
                continue
            c = oxy.mean(0)
            if math.hypot(c[0], c[1]) > R:
                continue
            inners = []
            for ir in poly.get("inner", []):
                q = clean_ring(ir)
                if q is None:
                    continue
                ixy, ill = q
                if ring_area(ixy) > 0:
                    ixy = ixy[::-1]; ill = ill[::-1]
                inners.append((ixy, ill))
            h, mh, lv, src = building_height(tags, area)
            if h - mh < 1.0:
                continue
            gz = dtm.sample(oll[:, 0], oll[:, 1])
            base = float(gz.min()) - 0.3
            top = float(gz.mean()) + h
            bot = base + mh if mh > 0 else base
            k = tile_key(c[0], c[1])
            bk = buckets.setdefault(k, {"v": [], "f": [], "h": [], "lv": [], "src": []})
            V, F = bk["v"], bk["f"]
            rings = [oxy] + [r[0] for r in inners]
            # roof (tessellated, supports courtyards)
            roof_start = len(V)
            flat = []
            for r in rings:
                flat.append([Vector((p[0], p[1], 0.0)) for p in r])
            try:
                tris = tessellate_polygon(flat)
            except Exception:
                tris = []
            allpts = [p for r in rings for p in r]
            for p in allpts:
                V.append((float(p[0]), float(p[1]), top))
            for t in tris:
                p0, p1, p2 = (allpts[t[0]], allpts[t[1]], allpts[t[2]])
                cz = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])
                tri = (roof_start + t[0], roof_start + t[1], roof_start + t[2])
                F.append(tri if cz > 0 else tri[::-1])
            nroof = len(tris)
            # walls
            wall_faces = 0
            for r in rings:
                s = len(V)
                n = len(r)
                for p in r:
                    V.append((float(p[0]), float(p[1]), bot))
                for p in r:
                    V.append((float(p[0]), float(p[1]), top))
                for i in range(n):
                    j = (i + 1) % n
                    F.append((s + i, s + j, s + n + j, s + n + i))
                wall_faces += n
            nf = nroof + wall_faces
            bk["h"] += [h] * nf; bk["lv"] += [int(lv)] * nf; bk["src"] += [src] * nf
            n_ok += 1
    for k, bk in buckets.items():
        make_obj(tname(prefix, k), bk["v"], bk["f"], col, mat,
                 {"height": ("FLOAT", bk["h"]), "levels": ("INT", bk["lv"]), "height_src": ("INT", bk["src"])})
    log(prefix, "built", n_ok, "in", len(buckets), "tiles")


# ----------------------------------------------------------------------------- lines
ROAD_W = {"motorway": 22, "trunk": 20, "primary": 14, "secondary": 11, "tertiary": 8,
          "motorway_link": 6, "trunk_link": 6, "primary_link": 6, "secondary_link": 6, "tertiary_link": 6,
          "unclassified": 6, "residential": 6, "living_street": 5, "road": 6, "busway": 7,
          "service": 4, "track": 3, "pedestrian": 6, "footway": 2, "path": 1.5, "cycleway": 2,
          "steps": 2, "bridleway": 2, "corridor": 2}
ROAD_GROUP = {}
for k in ("motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link", "secondary_link"):
    ROAD_GROUP[k] = ("04_Roads_Major", "RoadMajor", 0.14)
for k in ("tertiary", "tertiary_link", "unclassified", "residential", "living_street", "road", "busway"):
    ROAD_GROUP[k] = ("05_Roads_Minor", "RoadMinor", 0.12)
for k in ("service", "track"):
    ROAD_GROUP[k] = ("06_Roads_Service", "RoadService", 0.10)
for k in ("pedestrian", "footway", "path", "cycleway", "steps", "bridleway", "corridor"):
    ROAD_GROUP[k] = ("07_Paths_Sidewalks", "Path", 0.16)
SKIP_HW = {"proposed", "construction", "abandoned", "razed", "platform", "raceway", "elevator", "bus_stop",
           "rest_area", "services", "emergency_bay", "escape", "no", "via_ferrata", "disused"}


def densify(xy, maxlen):
    out = [xy[0]]
    for i in range(1, len(xy)):
        a, b = xy[i - 1], xy[i]
        L = float(np.hypot(*(b - a)))
        n = int(L // maxlen)
        for j in range(1, n + 1):
            t = j / (n + 1)
            out.append(a + (b - a) * t)
        out.append(b)
    return np.array(out)


def ribbon(xy, w_left, w_right):
    """Offset polyline; returns left, right point arrays (miter joins, clamped)."""
    d = np.diff(xy, axis=0)
    L = np.hypot(d[:, 0], d[:, 1]); L[L == 0] = 1e-9
    t = d / L[:, None]
    nrm = np.stack([-t[:, 1], t[:, 0]], 1)  # left normal
    vn = np.zeros_like(xy)
    vn[0] = nrm[0]; vn[-1] = nrm[-1]
    if len(xy) > 2:
        m = nrm[:-1] + nrm[1:]
        ml = np.hypot(m[:, 0], m[:, 1]); ml[ml < 1e-9] = 1e-9
        m = m / ml[:, None]
        cosang = np.clip((m * nrm[1:]).sum(1), 0.35, 1.0)
        vn[1:-1] = m / cosang[:, None]
    return xy + vn * w_left, xy - vn * w_right


class LineBucket:
    def __init__(self):
        self.v = []; self.f = []

    def add_strip(self, left, right, zl, zr):
        s = len(self.v)
        n = len(left)
        for i in range(n):
            self.v.append((float(left[i, 0]), float(left[i, 1]), float(zl[i])))
            self.v.append((float(right[i, 0]), float(right[i, 1]), float(zr[i])))
        for i in range(n - 1):
            a = s + 2 * i
            self.f.append((a + 1, a + 3, a + 2, a))


def xy_to_z(dtm, xy):
    lon, lat = local_to_lonlat(xy[:, 0], xy[:, 1])
    return dtm.sample(lon, lat)


def road_width(tags):
    w = _num(tags.get("width"))
    hw = tags.get("highway")
    if w and 1.0 <= w <= 80:
        return w
    lanes = _num(tags.get("lanes"))
    if lanes and 1 <= lanes <= 12 and hw not in ("footway", "path", "cycleway", "steps"):
        return lanes * 3.5 + (1.0 if hw in ("primary", "secondary", "trunk") else 0.0)
    return ROAD_W.get(hw, 4)


def build_lines(dtm, highways, lines):
    buckets = {}  # (colname, prefix, tile) -> LineBucket

    def bucket(colname, prefix, k):
        key = (colname, prefix, k)
        if key not in buckets:
            buckets[key] = LineBucket()
        return buckets[key]

    stats = {}
    for hw in highways:
        tags = hw["tags"]; cls = tags.get("highway")
        if cls in SKIP_HW or cls not in ROAD_GROUP:
            continue
        if tags.get("tunnel") in ("yes", "building_passage") and cls not in ("footway", "path"):
            pass  # keep at grade for LOD1
        pts = np.asarray(hw["pts"], dtype=np.float64)
        x, y = geo.to_local(pts[:, 0], pts[:, 1])
        xy = np.stack([x, y], 1)
        keep = np.ones(len(xy), bool); keep[1:] = np.hypot(*(xy[1:] - xy[:-1]).T) > 0.05
        xy = xy[keep]
        if len(xy) < 2:
            continue
        if min(np.hypot(*xy[0]), np.hypot(*xy[-1])) > R:
            continue
        xy = densify(xy, 20.0)
        colname, prefix, zoff = ROAD_GROUP[cls]
        is_sidewalk = cls == "footway" and tags.get("footway") in ("sidewalk", "crossing")
        w = road_width(tags)
        L, Rr = ribbon(xy, w / 2, w / 2)
        z = xy_to_z(dtm, xy) + zoff
        mid = xy[len(xy) // 2]
        k = tile_key(mid[0], mid[1])
        bucket(colname, prefix, k).add_strip(L, Rr, z, z)
        stats[prefix] = stats.get(prefix, 0) + 1
        # sidewalks from road tags (raised 15 cm above the road surface)
        sw = tags.get("sidewalk") or tags.get("sidewalk:both")
        sides = set()
        if sw in ("both", "yes"):
            sides = {"l", "r"}
        elif sw == "left":
            sides = {"l"}
        elif sw == "right":
            sides = {"r"}
        if tags.get("sidewalk:left") == "yes": sides.add("l")
        if tags.get("sidewalk:right") == "yes": sides.add("r")
        if sides and cls not in ("footway", "path", "cycleway", "steps", "pedestrian"):
            sw_w = _num(tags.get("sidewalk:width")) or 2.25
            zs = z + 0.15
            if "l" in sides:
                a, _ = ribbon(xy, w / 2 + sw_w, 0); b, _ = ribbon(xy, w / 2, 0)
                bucket("07_Paths_Sidewalks", "Sidewalk", k).add_strip(a, b, zs, zs)
            if "r" in sides:
                _, a = ribbon(xy, 0, w / 2); _, b = ribbon(xy, 0, w / 2 + sw_w)
                bucket("07_Paths_Sidewalks", "Sidewalk", k).add_strip(a, b, zs, zs)
            stats["tag_sidewalks"] = stats.get("tag_sidewalks", 0) + len(sides)
        if is_sidewalk:
            stats["mapped_sidewalks"] = stats.get("mapped_sidewalks", 0) + 1

    for ln in lines:
        tags = ln["tags"]
        rw = tags.get("railway"); ww = tags.get("waterway")
        if rw in ("rail", "tram", "light_rail", "narrow_gauge", "subway", "monorail") and tags.get("tunnel") != "yes":
            w = 3.2 if rw != "tram" else 2.6
            colname, prefix, zoff = "08_Railways", "Rail", 0.2
        elif ww in ("river", "canal", "stream", "drain", "ditch"):
            w = _num(tags.get("width")) or {"river": 25, "canal": 10, "stream": 4, "drain": 2, "ditch": 1.5}[ww]
            colname, prefix, zoff = "09_Water", "Waterway", 0.05
            if tags.get("tunnel") in ("culvert", "yes"):
                continue
        else:
            continue
        pts = np.asarray(ln["pts"], dtype=np.float64)
        x, y = geo.to_local(pts[:, 0], pts[:, 1]); xy = np.stack([x, y], 1)
        keep = np.ones(len(xy), bool); keep[1:] = np.hypot(*(xy[1:] - xy[:-1]).T) > 0.05
        xy = xy[keep]
        if len(xy) < 2:
            continue
        xy = densify(xy, 25.0)
        L, Rr = ribbon(xy, w / 2, w / 2)
        z = xy_to_z(dtm, xy) + zoff
        mid = xy[len(xy) // 2]
        bucket(colname, prefix, tile_key(mid[0], mid[1])).add_strip(L, Rr, z, z)
        stats[prefix] = stats.get(prefix, 0) + 1

    mats = {"RoadMajor": get_mat("M_Road_Major", (0.09, 0.09, 0.10), 0.6),
            "RoadMinor": get_mat("M_Road_Minor", (0.13, 0.13, 0.14), 0.7),
            "RoadService": get_mat("M_Road_Service", (0.20, 0.20, 0.21), 0.8),
            "Path": get_mat("M_Path", (0.55, 0.53, 0.50), 0.9),
            "Sidewalk": get_mat("M_Sidewalk", (0.62, 0.60, 0.57), 0.9),
            "Rail": get_mat("M_Rail", (0.30, 0.24, 0.20), 0.9),
            "Waterway": get_mat("M_Water", (0.10, 0.28, 0.42), 0.1)}
    for (colname, prefix, k), bk in buckets.items():
        make_obj(tname(prefix, k), bk.v, bk.f, get_col(colname), mats[prefix])
    log("lines", stats)


# ----------------------------------------------------------------------------- areas
AREA_CLASS = [
    ("water", lambda t: t.get("natural") == "water" or "water" in t or t.get("waterway") in ("riverbank", "dock")
        or t.get("landuse") in ("reservoir", "basin"), (0.10, 0.28, 0.42), 0.04),
    ("park", lambda t: t.get("leisure") in ("park", "garden", "playground", "dog_park", "common")
        or t.get("landuse") in ("grass", "recreation_ground", "village_green", "flowerbed"), (0.24, 0.40, 0.16), 0.03),
    ("sport", lambda t: t.get("leisure") in ("pitch", "stadium", "track", "sports_centre"), (0.30, 0.45, 0.25), 0.05),
    ("forest", lambda t: t.get("landuse") == "forest" or t.get("natural") in ("wood", "scrub"), (0.14, 0.28, 0.10), 0.02),
    ("cemetery", lambda t: t.get("landuse") == "cemetery", (0.30, 0.34, 0.24), 0.02),
    ("parking", lambda t: t.get("amenity") == "parking", (0.22, 0.22, 0.23), 0.06),
]


def build_areas(dtm, areas):
    col = get_col("10_Landuse_Green")
    buckets = {}
    cnt = {}
    for ar in areas:
        tags = ar["tags"]
        cls = None
        for name, fn, rgb, zoff in AREA_CLASS:
            if fn(tags):
                cls = (name, rgb, zoff); break
        if cls is None:
            continue
        for poly in ar["polys"]:
            o = clean_ring(poly["outer"])
            if o is None:
                continue
            oxy, oll = o
            A = abs(ring_area(oxy))
            if A < 20 or A > 2.0e6:     # skip huge rural polygons (terrain texture will cover them)
                continue
            c = oxy.mean(0)
            if math.hypot(*c) > R:
                continue
            rings_xy = [densify(np.vstack([oxy, oxy[:1]]), 25.0)[:-1]]
            for ir in poly.get("inner", []):
                q = clean_ring(ir)
                if q is not None:
                    rings_xy.append(q[0])
            flat = [[Vector((p[0], p[1], 0)) for p in r] for r in rings_xy]
            try:
                tris = tessellate_polygon(flat)
            except Exception:
                continue
            allxy = np.vstack(rings_xy)
            z = xy_to_z(dtm, allxy) + cls[2]
            k = (cls[0], tile_key(c[0], c[1]))
            bk = buckets.setdefault(k, {"v": [], "f": [], "rgb": cls[1]})
            s = len(bk["v"])
            bk["v"] += [(float(p[0]), float(p[1]), float(zz)) for p, zz in zip(allxy, z)]
            for t in tris:
                p0, p1, p2 = allxy[t[0]], allxy[t[1]], allxy[t[2]]
                cz = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])
                tri = (s + t[0], s + t[1], s + t[2])
                bk["f"].append(tri if cz > 0 else tri[::-1])
            cnt[cls[0]] = cnt.get(cls[0], 0) + 1
    for (name, k), bk in buckets.items():
        make_obj(tname("Area_" + name, k), bk["v"], bk["f"], col, get_mat("M_Area_" + name, bk["rgb"], 0.9))
    log("areas", cnt)


def build_points(dtm, nodes):
    col = get_col("11_Points_Trees_Lamps")
    groups = {}
    for nd in nodes:
        groups.setdefault(nd["t"], []).append(nd["p"])
    for t, pts in groups.items():
        a = np.asarray(pts, dtype=np.float64)
        x, y = geo.to_local(a[:, 0], a[:, 1])
        m = np.hypot(x, y) <= R
        if not m.any():
            continue
        z = dtm.sample(a[m, 0], a[m, 1])
        me = bpy.data.meshes.new("PTS_" + t.replace("=", "_"))
        me.from_pydata(np.stack([x[m], y[m], z], 1).tolist(), [], [])
        ob = bpy.data.objects.new("PTS_" + t.replace("=", "_"), me)
        col.objects.link(ob)
    log("points", {k: len(v) for k, v in groups.items()})


def build_reference():
    col = get_col("00_Reference")
    mat = get_mat("M_Site", (0.9, 0.05, 0.05), 0.5)
    bpy.ops.mesh.primitive_cylinder_add(radius=3, depth=120, location=(0, 0, 0))
    ob = bpy.context.active_object
    ob.name = "SITE_Toktonalieva_77"
    for c in ob.users_collection:
        c.objects.unlink(ob)
    col.objects.link(ob)
    ob.data.materials.append(mat)
    for r in (500, 1000, 3000, 5000, 10000, 20000, 35000):
        if r > R:
            continue
        cu = bpy.data.curves.new(f"Ring_{r}m", "CURVE")
        cu.dimensions = "3D"
        sp = cu.splines.new("POLY")
        n = 256
        sp.points.add(n)
        for i in range(n + 1):
            a = 2 * math.pi * i / n
            sp.points[i].co = (r * math.cos(a), r * math.sin(a), 0, 1)
        o = bpy.data.objects.new(f"Ring_{r}m", cu)
        col.objects.link(o)


def main():
    open(LOG_PATH, "w").close()
    log("start build, R =", R)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.name = "Bishkek_35km"
    sc.unit_settings.system = "METRIC"
    sc["geo_origin_lat"] = geo.LAT0; sc["geo_origin_lon"] = geo.LON0
    sc["geo_crs"] = "EPSG:32643 (UTM 43N) shifted: x=(E-E0)/k, y=(N-N0)/k"
    sc["geo_E0"] = geo.E0; sc["geo_N0"] = geo.N0; sc["geo_k"] = geo.KS
    sc["z_datum"] = "metres above sea level (EGM2008, Copernicus DEM)"
    ex = os.path.join(ROOT, "data", "osm", "extract")

    def load(n):
        with open(os.path.join(ex, n + ".json"), encoding="utf-8") as f:
            return json.load(f)

    dtm, dsm = load_dem()
    build_reference()
    build_terrain(dtm)
    build_buildings(dtm, load("buildings"), "02_Buildings_LOD1", "Bld", get_mat("M_Building", (0.78, 0.76, 0.72), 0.7))
    parts = load("building_parts")
    if parts:
        build_buildings(dtm, parts, "03_Building_Parts", "BldPart", get_mat("M_Building", (0.78, 0.76, 0.72), 0.7))
    build_lines(dtm, load("highways"), load("lines"))
    build_areas(dtm, load("areas"))
    build_points(dtm, load("nodes"))
    # viewport clipping for a 70 km scene
    for scr in bpy.data.screens:
        for area in scr.areas:
            for sp in area.spaces:
                if sp.type == "VIEW_3D":
                    sp.clip_start = 1.0; sp.clip_end = 250000.0
    out = os.environ.get("BISHKEK_OUT", os.path.join(ROOT, "Bishkek_35km.blend"))
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    log("SAVED", out)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        log("ERROR\n" + traceback.format_exc())
        raise
