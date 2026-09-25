"""Stage 15 - bring the finished city tiles into the single working file Bishkek_35km.blend.

  - links collection CITY_T_I_J from city\\tile_I_J.blend (relative path) under CITY_1km_Tiles (re-run = library reload)
  - removes the v1 LOD1 buildings (Bld_* chunks) whose parts lie inside the finished tiles (each tile rebuilt them)
  - cuts the 35 km terrain (Terrain_*) under the finished tiles (exact boolean with an extruded outline of the union)
    and puts the new terrain edge on the DTM, 3 cm under the tile edge (tile skirts hide the hairline)
  - hides Z1_Seam_Ribbon where tiles surround the 1 km zone
Run: blender -b Bishkek_35km.blend --python 15_integrate_city.py   (saves in place)
 or inside an open Blender: exec the file, then integrate(save=False)
"""
import os, sys, json, math, hashlib
ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "pylibs")):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)
import numpy as np
import bpy


def log(*a):
    print("[city]", *a, flush=True)


def done_tiles():
    tl = json.load(open(os.path.join(ROOT, "data", "city", "tile_list.json")))
    out = []
    for i, j in tl:
        d = os.path.join(ROOT, "data", "city", f"T_{i}_{j}")
        b = os.path.join(ROOT, "city", f"tile_{i}_{j}.blend")
        if os.path.exists(os.path.join(d, "DONE")) and os.path.exists(b):
            out.append((i, j, d, b))
    return out


def tile_union(tiles):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polys = []
    for i, j, d, b in tiles:
        ring = np.asarray(json.load(open(os.path.join(d, "zone_ring.json"))), float)[:, :2]
        polys.append(Polygon(ring).buffer(0))
    return unary_union(polys).buffer(0.01, join_style="mitre").buffer(-0.01, join_style="mitre")


def link_tiles(tiles):
    sc = bpy.context.scene
    parent = bpy.data.collections.get("CITY_1km_Tiles")
    if parent is None:
        parent = bpy.data.collections.new("CITY_1km_Tiles"); sc.collection.children.link(parent)
    have = {}
    for lib in bpy.data.libraries:
        have[os.path.normcase(os.path.abspath(bpy.path.abspath(lib.filepath)))] = lib
    n_new = n_rel = 0
    for i, j, d, b in tiles:
        name = f"CITY_T_{i}_{j}"
        key = os.path.normcase(os.path.abspath(b))
        if key in have:
            # a file opened fresh already reads every library from disk; reload only in a long-open session
            if os.environ.get("BISHKEK_CITY_RELOAD") == "1":
                try:
                    have[key].reload(); n_rel += 1
                except Exception as e:
                    log("reload failed", name, e)
        else:
            rel = bpy.path.relpath(b) if bpy.data.filepath else b
            with bpy.data.libraries.load(rel, link=True) as (src, dst):
                dst.collections = [c for c in src.collections if c == name]
            n_new += 1
        col = next((c for c in bpy.data.collections if c.name == name and c.library is not None
                    and os.path.normcase(os.path.abspath(bpy.path.abspath(c.library.filepath))) == key), None) \
            if key in have else (dst.collections[0] if dst.collections else None)
        if col is not None and col.name not in [c.name for c in parent.children]:
            parent.children.link(col)
        if (n_new + n_rel) % 25 == 0 and n_new:
            log("  linked", n_new)
    log("tiles linked new", n_new, "reloaded", n_rel)


def set_view_range(km=None):
    """viewport speed: tiles farther than km from the site are excluded from the view layer (tick them on in the
    outliner, or call set_view_range(99) to show the whole city). Env BISHKEK_CITY_VIEW_KM, default 3.5."""
    km = float(os.environ.get("BISHKEK_CITY_VIEW_KM", "3.5")) if km is None else km
    root = next((lc for lc in bpy.context.view_layer.layer_collection.children if lc.name == "CITY_1km_Tiles"), None)
    if root is None:
        return
    shown = 0
    for lc in root.children:
        try:
            _, _, i, j = lc.name.split("_")[:4]
            d = math.hypot(int(i), int(j))
        except Exception:
            continue
        lc.exclude = d > km
        shown += not lc.exclude
    log("tiles shown in the viewport", shown, "of", len(root.children), "(within", km, "km)")


def _components(nv, edges):
    """connected vertex components (min-label propagation with pointer jumping)"""
    lab = np.arange(nv)
    if not len(edges):
        return lab
    a, b = edges[:, 0], edges[:, 1]
    for _ in range(200):
        m = np.minimum(lab[a], lab[b])
        old = lab.copy()
        np.minimum.at(lab, a, m); np.minimum.at(lab, b, m)
        lab = lab[lab]
        if np.array_equal(lab, old):
            break
    return lab


def remove_v1_buildings(U):
    """delete every v1 LOD1 building (loose part of a Bld_* chunk) whose centre lies inside the finished tiles"""
    import shapely, bmesh
    shapely.prepare(U)
    x0, y0, x1, y1 = U.bounds
    removed = 0
    for o in list(bpy.data.objects):
        if o.type != "MESH" or not (o.name.startswith("Bld_") or o.name.startswith("BldPart_")) or o.library is not None:
            continue
        mw = np.array(o.matrix_world)
        bb = np.array([mw[:3, :3] @ np.array(v) + mw[:3, 3] for v in o.bound_box])
        if bb[:, 0].min() > x1 or bb[:, 0].max() < x0 or bb[:, 1].min() > y1 or bb[:, 1].max() < y0:
            continue
        me = o.data
        nv = len(me.vertices)
        if nv == 0:
            continue
        co = np.empty(nv * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
        ed = np.empty(len(me.edges) * 2, np.int64); me.edges.foreach_get("vertices", ed); ed = ed.reshape(-1, 2)
        lab = _components(nv, ed)
        u, inv = np.unique(lab, return_inverse=True)
        cx = np.bincount(inv, co[:, 0]) / np.bincount(inv); cy = np.bincount(inv, co[:, 1]) / np.bincount(inv)
        inside = shapely.contains_xy(U, cx, cy)
        if not inside.any():
            continue
        kill_v = inside[inv]
        bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.verts[k] for k in np.nonzero(kill_v)[0]], context="VERTS")
        bm.to_mesh(me); bm.free(); me.update()
        removed += int(inside.sum())
    log("v1 LOD1 buildings removed under city tiles", removed)


TERRAIN_TILE = 5000.0
BASE_BLEND = os.path.join(ROOT, "_old_versions", "Bishkek_35km_v1_base.blend")


def _dtm_sampler():
    import geo
    zdat = np.load(os.path.join(ROOT, "data", "dtm_crop.npz"))
    dem = geo.DEM(zdat["dtm"], float(zdat["lon_min_edge"]), float(zdat["lat_max_edge"]), float(zdat["d"]), float(zdat["d"]))
    kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0

    def zs(xy):
        xy = np.asarray(xy, float).reshape(-1, 2)
        lon = geo.LON0 + xy[:, 0] / kx; lat = geo.LAT0 + xy[:, 1] / ky
        for _ in range(6):
            cx, cy = geo.to_local(lon, lat); lon = lon + (xy[:, 0] - cx) / kx; lat = lat + (xy[:, 1] - cy) / ky
        return dem.sample(lon, lat)
    return zs


def _zone_poly():
    from shapely.geometry import Polygon, Point
    p = os.path.join(ROOT, "data", "zone_ring.json")
    if os.path.exists(p):
        r = json.load(open(p))
        return Polygon(np.asarray(r["outer"] if isinstance(r, dict) else r, float)[:, :2]).buffer(0), r
    RZ = float(os.environ.get("BISHKEK_ZONE_R", "1000"))
    return Point(0, 0).buffer(RZ, quad_segs=64), None


def _zone_ring_hash(ring):
    """same hash 07_zone_blender.cut_terrain stores, so a later zone rebuild does not boolean-cut these tiles again"""
    if ring is None:
        return None
    ring = ring[:-1]
    return hashlib.md5(json.dumps([[round(x, 3), round(y, 3)] for x, y in ring]).encode()).hexdigest()[:16]


def _restore_terrain(names):
    """put the pristine terrain meshes (v1 base file) back on these objects; keeps their materials"""
    if not os.path.exists(BASE_BLEND):
        log("WARNING no base file", BASE_BLEND, "- terrain cut on the current meshes")
        return 0
    with bpy.data.libraries.load(BASE_BLEND, link=False) as (src, dst):
        want = [n for n in names if n in src.meshes]
        dst.meshes = list(want)          # (Blender replaces the list items with the loaded IDs)
    n = 0
    for name, me_new in zip(want, dst.meshes):
        if me_new is None:
            continue
        o = bpy.data.objects.get(name)
        old = o.data
        mats = list(old.materials)
        o.data = me_new
        me_new.materials.clear()
        for m in mats:
            me_new.materials.append(m)
        if old.users == 0:
            bpy.data.meshes.remove(old)
        me_new.name = name
        n += 1
    return n


class _TileGroundZ:
    """height of the finished ground (city tiles / 1 km zone) right at a point of the city outline: the terrain edge
    is put 3 cm under it, so the terrain meets the real tile edge (kerbs, aryks) and not just the DTM"""
    def __init__(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("city_report16", os.path.join(ROOT, "scripts", "16_city_report.py"))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        self.TG = m.TileGround
        self.cache = {}
        self.RZ = float(os.environ.get("BISHKEK_ZONE_R", "1000"))

    def _get(self, x, y):
        if math.hypot(x, y) < self.RZ:
            k, d = "ZONE", os.path.join(ROOT, "data")
        else:
            i, j = int(math.floor(x / 1000.0 + 0.5)), int(math.floor(y / 1000.0 + 0.5))
            k, d = f"T_{i}_{j}", os.path.join(ROOT, "data", "city", f"T_{i}_{j}")
        if k not in self.cache:
            self.cache[k] = self.TG(d) if os.path.exists(os.path.join(d, "zone_partition.npz")) else None
        return self.cache[k]

    def z(self, xy):
        out = np.full(len(xy), np.nan)
        for n, (x, y) in enumerate(xy):
            for dx, dy in ((0.05, 0), (-0.05, 0), (0, 0.05), (0, -0.05), (0.04, 0.04), (-0.04, -0.04), (0.04, -0.04), (-0.04, 0.04)):
                g = self._get(x + dx, y + dy)
                if g is None:
                    continue
                c, zz = g.sample(np.array([[x + dx, y + dy]]))
                if c[0] is not None and np.isfinite(zz[0]):
                    out[n] = zz[0] if np.isnan(out[n]) else min(out[n], zz[0])
            # (lowest of the touching surfaces: the terrain never stands above an aryk / kerb edge)
        return out


def _clip_terrain(o, CUT, zs, zhash, chash, gz=None):
    """remove the part of a terrain tile that lies inside CUT (2D clip of every triangle, no boolean):
    triangles inside are deleted, triangles crossing the outline keep their outside part (constrained triangulation,
    heights on the original triangle plane), new outline vertices sit on the DTM 3 cm under the tile ground edge"""
    import shapely, bmesh
    me = o.data
    mw = np.array(o.matrix_world); inv = np.linalg.inv(mw)
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    if not len(bm.faces):
        bm.free(); me["city_cut"] = chash; return 0
    W = np.array([mw[:3, :3] @ np.array(v.co) + mw[:3, 3] for v in bm.verts])
    F = np.array([[v.index for v in f.verts] for f in bm.faces], np.int64)
    P = W[F]
    nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]); nl = np.linalg.norm(nrm, axis=1) + 1e-12
    vert = np.abs(nrm[:, 2]) / nl < 0.2
    cen = P.mean(1)
    kill = np.zeros(len(F), bool)
    kill[vert] = shapely.contains_xy(CUT, cen[vert, 0], cen[vert, 1])
    hz = np.nonzero(~vert)[0]
    polys = shapely.polygons(P[hz][:, :, :2])
    inside = shapely.within(polys, CUT)
    kill[hz[inside]] = True
    cross_i = hz[~inside & shapely.intersects(polys, CUT)]
    newtris = []
    for fi in cross_i:
        tri = shapely.polygons(P[fi][:, :2])
        rest = tri.difference(CUT)
        kill[fi] = True
        if rest.is_empty or rest.area < 1e-4:
            continue
        A = P[fi, 0]; nv = nrm[fi]
        for t in getattr(shapely.constrained_delaunay_triangles(rest), "geoms", []):
            c = np.asarray(t.exterior.coords)[:3]
            if abs((c[1, 0] - c[0, 0]) * (c[2, 1] - c[0, 1]) - (c[2, 0] - c[0, 0]) * (c[1, 1] - c[0, 1])) < 1e-6:
                continue
            z = A[2] - (nv[0] * (c[:, 0] - A[0]) + nv[1] * (c[:, 1] - A[1])) / nv[2]
            newtris.append(np.c_[c, z])
    if not kill.any():
        bm.free(); return 0
    kf = [bm.faces[i] for i in np.nonzero(kill)[0]]
    bmesh.ops.delete(bm, geom=kf, context="FACES_ONLY")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.verts.ensure_lookup_table()
    key = {}
    for v in bm.verts:
        w = mw[:3, :3] @ np.array(v.co) + mw[:3, 3]
        key[(round(w[0] * 1000), round(w[1] * 1000))] = v
    edge = CUT.boundary
    for T in newtris:
        vs = []
        for x, y, z in T:
            k = (round(x * 1000), round(y * 1000))
            v = key.get(k)
            if v is None:
                l = inv[:3, :3] @ np.array([x, y, z]) + inv[:3, 3]
                v = bm.verts.new(l); key[k] = v
            vs.append(v)
        if len(set(vs)) == 3:
            try:
                bm.faces.new(vs)
            except ValueError:
                pass
    # outline vertices: DTM height, 3 cm under the city tile ground edge (tile skirts hide the hairline)
    bm.verts.ensure_lookup_table()
    Wn = np.array([mw[:3, :3] @ np.array(v.co) + mw[:3, 3] for v in bm.verts]).reshape(-1, 3)
    on = (shapely.distance(edge, shapely.points(Wn[:, :2])) < 0.05) if len(Wn) else np.zeros(0, bool)
    if on.any():
        zt = zs(Wn[on, :2]) - 0.03
        if gz is not None:
            zg = gz.z(Wn[on, :2])
            ok = np.isfinite(zg)
            zt[ok] = zg[ok] - 0.03
            _clip_terrain.matched = getattr(_clip_terrain, "matched", 0) + int(ok.sum())
            _clip_terrain.total = getattr(_clip_terrain, "total", 0) + int(len(ok))
        Wn[on, 2] = zt
        for i in np.nonzero(on)[0]:
            bm.verts[i].co = inv[:3, :3] @ Wn[i] + inv[:3, 3]
    bm.to_mesh(me); bm.free(); me.update()
    # UVs of the Sentinel terrain texture (same mapping as 10_apply_terrain_textures) + z_dtm for the zone seam logic
    try:
        ix, iy = (int(v) for v in o.name.split("_")[1:3])
        x0, y0 = ix * TERRAIN_TILE, iy * TERRAIN_TILE
        if not len(me.vertices):
            raise ValueError("tile fully inside the city")
        uvl = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
        vi = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", vi)
        co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        wc = co @ mw[:3, :3].T.astype(np.float32) + mw[:3, 3].astype(np.float32)
        uvl.data.foreach_set("uv", np.stack([(wc[vi, 0] - x0) / TERRAIN_TILE, (wc[vi, 1] - y0) / TERRAIN_TILE], 1).astype(np.float32).ravel())
        att = me.attributes.get("z_dtm") or me.attributes.new("z_dtm", "FLOAT", "POINT")
        att.data.foreach_set("value", wc[:, 2].astype(np.float32))
    except Exception as e:
        log("uv/z_dtm update failed", o.name, e)
    if zhash:
        me["zone_hole_ring"] = zhash
    me["city_cut"] = chash
    return int(kill.sum())


def cut_terrain(U):
    """terrain hole under the 1 km zone + every finished city tile. Earlier versions used an exact boolean with an
    extruded outline; on the open terrain surface it produced stray faces (terrain showing through the tiles), so
    the tiles now get their pristine mesh back and are clipped in 2D (deterministic, idempotent)."""
    import shapely
    from shapely.geometry import box
    from shapely.ops import unary_union
    Z, zring = _zone_poly()
    CUT = unary_union([U, Z]).buffer(0.001, join_style="mitre").buffer(-0.001, join_style="mitre")
    shapely.prepare(CUT)
    zhash = _zone_ring_hash(zring)
    chash = hashlib.md5(CUT.wkb + b"edge-v2").hexdigest()[:16]   # v2: terrain edge on the tile ground (25 Sep)
    x0, y0, x1, y1 = CUT.bounds
    names = []
    for o in bpy.data.objects:
        if not o.name.startswith("Terrain_") or o.type != "MESH" or o.library is not None:
            continue
        try:
            ix, iy = (int(v) for v in o.name.split("_")[1:3])
        except Exception:
            continue
        tb = box(ix * TERRAIN_TILE - 20, iy * TERRAIN_TILE - 20, (ix + 1) * TERRAIN_TILE + 20, (iy + 1) * TERRAIN_TILE + 20)
        if not CUT.intersects(tb) or o.data.get("city_cut") == chash:
            continue
        names.append(o.name)
    if not names:
        log("terrain: nothing to cut"); return
    nr = _restore_terrain(names)
    zs = _dtm_sampler()
    try:
        gz = _TileGroundZ()
    except Exception as e:
        log("tile ground sampler unavailable, terrain edge on the DTM:", e); gz = None
    tot = 0
    for nm in names:
        tot += _clip_terrain(bpy.data.objects[nm], CUT, zs, zhash, chash, gz)
    log("terrain tiles restored", nr, "clipped", len(names), "faces removed", tot,
        "| edge vertices on the tile ground", getattr(_clip_terrain, "matched", 0), "of", getattr(_clip_terrain, "total", 0))


def hide_ribbon(U):
    """the 1 km zone seam ribbon is not needed where city tiles touch the zone edge all round"""
    import shapely
    from shapely.geometry import Point
    rib = bpy.data.objects.get("Z1_Seam_Ribbon")
    if rib is None:
        return
    ring = Point(0, 0).buffer(float(os.environ.get("BISHKEK_ZONE_R", "1000")) + 0.5, quad_segs=64).exterior
    cov = ring.intersection(U.buffer(1.0)).length / ring.length
    if cov > 0.999:
        rib.hide_viewport = True; rib.hide_render = True
    log("zone ring covered by tiles", round(cov * 100, 1), "% -> ribbon hidden" if cov > 0.999 else "")


def purge_old():
    """SHEF: no old layers left in the working file. Removed: the hidden v1 OSM overlay collection (map ribbons /
    area patches of the first draft), the v1 distance rings, the zone seam ribbon (city tiles surround the zone),
    empty v1 building chunks and helper leftovers. Kept: terrain + LOD1 buildings outside the city tiles (35 km
    context), the site marker, the cameras."""
    n = 0
    for cname in ("_REF_OSM_v1_overlays (hidden)", "04_Roads_Major", "05_Roads_Minor", "06_Roads_Service", "07_Paths_Sidewalks",
                  "08_Railways", "09_Water", "10_Landuse_Green", "11_Points_Trees_Lamps"):
        ref = bpy.data.collections.get(cname)
        if ref is None or ref.library is not None:
            continue
        for o in list(ref.all_objects):
            if o.library is None:
                bpy.data.objects.remove(o, do_unlink=True); n += 1
        for c in list(ref.children_recursive):
            if c.library is None:
                bpy.data.collections.remove(c)
        bpy.data.collections.remove(ref)
    for o in list(bpy.data.objects):
        if o.library is not None:
            continue
        nm = o.name
        if nm.startswith("Ring_") or nm in ("Z1_Seam_Ribbon", "_QA_Markers", "_zone_cutter", "_city_cutter", "_city_cut_curve") \
                or ((nm.startswith("Bld_") or nm.startswith("BldPart_")) and o.type == "MESH" and len(o.data.polygons) == 0):
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
    log("old layers removed: objects", n)


def integrate(save=True):
    tiles = done_tiles()
    log("finished tiles", len(tiles))
    if not tiles:
        return
    U = tile_union(tiles)
    link_tiles(tiles)
    set_view_range()
    remove_v1_buildings(U)
    cut_terrain(U)
    hide_ribbon(U)
    purge_old()
    json.dump({"tiles": [[i, j] for i, j, d, b in tiles], "area_km2": round(U.area / 1e6, 2)},
              open(os.path.join(ROOT, "data", "city", "integrated.json"), "w"))
    if save:
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_mainfile(compress=True)
        log("SAVED", bpy.data.filepath)


if __name__ == "__main__":
    integrate(save=bool(bpy.app.background))
