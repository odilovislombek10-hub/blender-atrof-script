"""Geometric QA of the 1 km detail zone - finds model errors from the mesh data itself (no pictures).

Runs inside Blender (live via MCP, or: blender -b Bishkek_35km.blend --python 12_qa_geometry.py).
Checks
  1  per object   : degenerate faces, loose verts, flipped horizontal faces, duplicate verts
  2  seams        : the whole ground (all GROUND_* objects together) must be closed. Boundary edges that are not
                    on a building outline (incl. courtyards, 0.3 m) and lie inside the ring are chained into loops
                    with the same global vertex identity the repair stage uses (08_repair_ground.analyse):
                      hole        closed loop, area > 0.01 m2 (visible gap)                       sev 3
                      tjunction   closed zero-area loops (one summary issue with the count)       sev 1
                      open_chain  chain that does not close, longer than 0.3 m                    sev 2
                    plus edges with > 2 faces (nonmanifold_edge) and unpaired vertical wall ends (wall_end_hole)
  3  z-fighting   : horizontal faces of different objects overlapping in plan (interior overlap) at ~same height
  4  logic        : road fragments, dangling paths, parking without road access, entrances not at a building,
                    playgrounds without a path, crosswalks not joining two sidewalks, tiny category slivers
  5  trees        : trunks standing on hard surfaces / inside buildings
  6  buildings    : overlapping footprints, footprints on roads, floating bases (exact ground height under the
                    building's plan + 1 m)
  7  terrain seam : zone edge vs 35 km terrain hole edge along the ring; the vertical interval between them must be
                    covered by Z1_Seam_Ribbon -> terrain_seam_gap = uncovered places only
Output: data/qa_geometry.json with 'summary' {type: count}, 'severity' {sev: count}, 'issue_counts', 'issues'
(+ optional marker object _QA_Markers with an 'issue' attribute)
"""
import os, sys, json, math, time
from collections import defaultdict, Counter
import numpy as np
import bpy

ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
_CT = os.environ.get("BISHKEK_TILE")   # city mode: per-tile data dir data/city/T_I_J
DATADIR = os.path.join(ROOT, "data", "city", "T_%s_%s" % tuple(_CT.split(","))) if _CT else os.path.join(ROOT, "data")
for p in (os.path.join(ROOT, "pylibs"), os.path.join(ROOT, "scripts")):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)
import shapely
from shapely import STRtree
from shapely.geometry import Polygon, Point

T0 = time.time()
Q = 1000.0  # 1 mm quantisation
ISS = []
SEAM_RIBBON = "Z1_Seam_Ribbon"


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


def issue(kind, sev, x, y, z=0.0, **info):
    ISS.append({"type": kind, "sev": sev, "x": round(float(x), 2), "y": round(float(y), 2), "z": round(float(z), 2), **info})


def _load_repair():
    import importlib.util
    if "repair_ground" in sys.modules:
        return sys.modules["repair_ground"]
    here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(ROOT, "scripts")
    for d in (os.path.join(ROOT, "scripts"), here):
        for nm in ("08_repair_ground.py", "repair_ground.py"):
            rp = os.path.join(d, nm)
            if os.path.exists(rp):
                spec = importlib.util.spec_from_file_location("repair_ground", rp)
                mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
                sys.modules["repair_ground"] = mod
                return mod
    raise ImportError("08_repair_ground.py / repair_ground.py not found in " + os.path.join(ROOT, "scripts"))


def mesh_arrays(ob):
    me = ob.data
    mw = np.array(ob.matrix_world)
    n = len(me.vertices)
    co = np.empty(n * 3, np.float64); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    if not np.allclose(mw, np.eye(4)):
        co = co @ mw[:3, :3].T + mw[:3, 3]
    ls = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", lt)
    lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv)
    return co, ls, lt, lv


def poly_list(ls, lt, lv):
    return [lv[s:s + t] for s, t in zip(ls, lt)]


def newell(co, idx):
    p = co[idx]; q = np.roll(p, -1, axis=0)
    n = np.array([np.sum((p[:, 1] - q[:, 1]) * (p[:, 2] + q[:, 2])),
                  np.sum((p[:, 2] - q[:, 2]) * (p[:, 0] + q[:, 0])),
                  np.sum((p[:, 0] - q[:, 0]) * (p[:, 1] + q[:, 1]))])
    return n  # length = 2*area


def newell_all(V, LS, LT, LV):
    """vectorised Newell normals (length = 2*area) for all faces"""
    fol = np.repeat(np.arange(len(LS)), LT)
    pos = np.arange(len(LV)) - LS[fol]
    nxt = LS[fol] + (pos + 1) % LT[fol]
    P = V[LV]; Qn = V[LV[nxt]]
    nf = len(LS)
    nx = np.bincount(fol, (P[:, 1] - Qn[:, 1]) * (P[:, 2] + Qn[:, 2]), nf)
    ny = np.bincount(fol, (P[:, 2] - Qn[:, 2]) * (P[:, 0] + Qn[:, 0]), nf)
    nz = np.bincount(fol, (P[:, 0] - Qn[:, 0]) * (P[:, 1] + Qn[:, 1]), nf)
    return np.stack([nx, ny, nz], 1)


def cluster(points, r=3.0):
    """merge nearby issue points -> list of (xyz, count)"""
    out = []
    if not len(points):
        return out
    P = np.asarray(points)
    key = np.floor(P[:, :2] / r).astype(np.int64)
    d = defaultdict(list)
    for i, k in enumerate(map(tuple, key)):
        d[k].append(i)
    for k, ids in d.items():
        c = P[ids].mean(0); out.append((c, len(ids)))
    return out


# ------------------------------------------------------------------------------------------ terrain seam
def _ring_s(ring_line, xy):
    return shapely.line_locate_point(ring_line, shapely.points(np.asarray(xy)[:, :2]))


def _on_ring(ring_line, xy, tol):
    return shapely.distance(ring_line, shapely.points(np.asarray(xy)[:, :2])) < tol


def _seg_samples(s0, s1, S, L):
    """indices of samples S (sorted, in [0,L)) inside segment [s0,s1] (s1 may exceed L -> wraps), and their
    unwrapped positions"""
    i0 = np.searchsorted(S, s0, "left"); i1 = np.searchsorted(S, min(s1, L), "right")
    idx = np.arange(i0, i1); pos = S[idx]
    if s1 > L:
        j1 = np.searchsorted(S, s1 - L, "right")
        idx = np.r_[idx, np.arange(0, j1)]; pos = np.r_[pos, S[:j1] + L]
    return idx, pos


def _edge_profile(segs, S, L, mode="max"):
    """segs: list of (sa, za, sb, zb) along the ring -> z at every sample (nan where no segment)"""
    z = np.full(len(S), np.nan)
    for sa, za, sb, zb in segs:
        if sb < sa:
            sa, za, sb, zb = sb, zb, sa, za
        if sb - sa > L / 2:          # crosses s = 0
            sa, za, sb, zb = sb, zb, sa + L, za
        if sb - sa < 1e-6:
            continue
        idx, pos = _seg_samples(sa, sb, S, L)
        if not len(idx):
            continue
        zz = za + (zb - za) * (pos - sa) / (sb - sa)
        cur = z[idx]
        z[idx] = np.where(np.isnan(cur), zz, np.maximum(cur, zz) if mode == "max" else np.minimum(cur, zz))
    return z


def seam_check(A, ter, ring_poly, step=0.25):
    """zone edge (top faces on the ring) vs terrain hole edge vs Z1_Seam_Ribbon, sampled every `step` m along the ring"""
    ring_line = ring_poly.exterior
    L = ring_line.length
    V, LS, LT, LV = A["V"], A["LS"], A["LT"], A["LV"]
    GV = A["GV"]; ea, eb, ef = A["ea"], A["eb"], A["ef"]
    NZ = A["_NZ"]
    # zone top edge: edges of up-facing ground faces with both ends on the ring
    m = NZ[ef] > 0.5
    ca, cb = ea[m], eb[m]
    on_a = _on_ring(ring_line, GV[ca], 0.02); on_b = _on_ring(ring_line, GV[cb], 0.02)
    k = on_a & on_b
    za_, zb_ = GV[ca[k]], GV[cb[k]]
    dxy = np.hypot(*(zb_[:, :2] - za_[:, :2]).T)
    za_, zb_ = za_[dxy > 1e-3], zb_[dxy > 1e-3]
    zone_segs = list(zip(_ring_s(ring_line, za_), za_[:, 2], _ring_s(ring_line, zb_), zb_[:, 2])) if len(za_) else []
    # sample positions (avoid exact vertex positions where the zone edge steps)
    S = np.arange(step / 2, L, step)
    zz = _edge_profile(zone_segs, S, L, "max")
    # terrain hole edge
    ter_segs = []
    for o in ter:
        co, ls, lt, lv = mesh_arrays(o)
        r = np.hypot(co[:, 0], co[:, 1])
        R = float(np.hypot(*np.asarray(ring_line.coords)[:, :2].T).max())
        if r.min() > R + 50:
            continue
        near = np.nonzero(np.abs(r - R) < 5)[0]
        if not len(near):
            continue
        fol = np.repeat(np.arange(len(ls)), lt); pos = np.arange(len(lv)) - ls[fol]; nxt = ls[fol] + (pos + 1) % lt[fol]
        a, b = lv, lv[nxt]
        cand = np.isin(a, near) & np.isin(b, near)
        a, b = a[cand], b[cand]
        lo = np.minimum(a, b); hi = np.maximum(a, b)
        kk = lo * (len(co) + 1) + hi
        u, cnt = np.unique(kk, return_counts=True)
        bset = set(u[cnt == 1].tolist())
        sel = np.array([x in bset for x in kk.tolist()], bool) if len(kk) else np.zeros(0, bool)
        a, b = a[sel], b[sel]
        if not len(a):
            continue
        ok = _on_ring(ring_line, co[a], 0.05) & _on_ring(ring_line, co[b], 0.05)
        a, b = a[ok], b[ok]
        d = np.hypot(*(co[b, :2] - co[a, :2]).T)
        a, b = a[d > 1e-3], b[d > 1e-3]
        if len(a):
            ter_segs += list(zip(_ring_s(ring_line, co[a]), co[a, 2], _ring_s(ring_line, co[b]), co[b, 2]))
    zt = _edge_profile(ter_segs, S, L, "max")
    # ribbon cross-sections
    lo_c = [[] for _ in range(len(S))]
    rib = bpy.data.objects.get(SEAM_RIBBON)
    n_rib = 0
    if rib is not None and rib.type == 'MESH':
        co, ls, lt, lv = mesh_arrays(rib)
        n_rib = len(ls)
        rs = _ring_s(ring_line, co) if len(co) else np.zeros(0)
        for s_, t_ in zip(ls, lt):
            p = lv[s_:s_ + t_]
            ss = rs[p].copy(); zc = co[p, 2]
            if ss.max() - ss.min() > L / 2:
                ss[ss < L / 2] += L
            s0, s1 = ss.min(), ss.max()
            if s1 - s0 < 1e-6:
                continue
            idx, pos = _seg_samples(s0, s1, S, L)
            if not len(idx):
                continue
            n = len(p); zs = []
            for i in range(n):
                sa, sb = ss[i], ss[(i + 1) % n]; za, zb = zc[i], zc[(i + 1) % n]
                if abs(sb - sa) < 1e-9:
                    continue
                t = (pos - sa) / (sb - sa)
                inside = (t >= -1e-9) & (t <= 1 + 1e-9)
                zs.append(np.where(inside, za + (zb - za) * t, np.nan))
            if not zs:
                continue
            Z_ = np.array(zs)
            zlo = np.nanmin(Z_, 0); zhi = np.nanmax(Z_, 0)
            for j, i in enumerate(idx):
                if not np.isnan(zlo[j]):
                    lo_c[i].append((zlo[j], zhi[j]))
    gaps = []
    no_ter = 0; no_zone = 0; worst = 0.0
    dz_all = []
    for i in range(len(S)):
        if np.isnan(zz[i]):
            no_zone += 1; continue
        if np.isnan(zt[i]):
            no_ter += 1; gaps.append((S[i], zz[i], 99.0)); continue
        a_, b_ = sorted((zz[i], zt[i]))
        dz_all.append(b_ - a_)
        if b_ - a_ <= 0.01:
            continue
        iv = sorted(lo_c[i])
        cov = a_ + 0.005
        for lo, hi in iv:
            if lo <= cov + 0.005:
                cov = max(cov, hi)
        unc = max(0.0, b_ - 0.005 - cov)
        if unc > 0.02:
            gaps.append((S[i], (a_ + b_) / 2, unc)); worst = max(worst, unc)
    pts = []
    for s_, z_, u in gaps:
        p = ring_line.interpolate(s_ % L)
        pts.append((p.x, p.y, z_))
    for (c, n) in cluster(pts, 20.0):
        issue("terrain_seam_gap", 2, *c, n=int(n))
    dz_all = np.array(dz_all) if dz_all else np.zeros(1)
    info = {"samples": int(len(S)), "step_m": step, "zone_edge_segments": len(zone_segs), "terrain_edge_segments": len(ter_segs),
            "ribbon_faces": n_rib, "max_abs_dz": round(float(dz_all.max()), 3), "p95_abs_dz": round(float(np.percentile(dz_all, 95)), 3),
            "uncovered_samples": len(gaps), "samples_without_terrain_edge": no_ter, "samples_without_zone_edge": no_zone,
            "worst_uncovered_m": round(worst, 3)}
    log("terrain seam", info)
    return info


# ------------------------------------------------------------------------------------------ main
def main(make_markers=True):
    ISS.clear()
    rg = _load_repair()
    grounds = rg.ground_objects()
    log("ground objects", len(grounds))
    data = rg.collect(grounds)
    V, LS, LT, LV, FO = data
    names = [o.name[7:] for o in grounds]
    NN = newell_all(V, LS, LT, LV)
    AR = np.linalg.norm(NN, axis=1) / 2
    NZ = np.where(AR > 0, NN[:, 2] / np.maximum(2 * AR, 1e-30), 0.0)
    allF = np.split(LV, LS[1:]) if len(LS) else []
    # degenerate = no real surface (< 1 mm2). Before 25 Sep every face under 1 cm2 was counted (600-970 per tile);
    # those are small or thin but valid, watertight pieces -> reported per object as tiny_faces / thin_slivers.
    LMAX = np.zeros(len(LS))
    if len(LS):
        nxt = np.arange(len(LV)) + 1
        ends = LS + LT
        nxt[ends - 1] = LS
        el = np.linalg.norm(V[LV[nxt]] - V[LV], axis=1)
        LMAX = np.maximum.reduceat(el, LS)
    THK = 2 * AR / np.maximum(LMAX, 1e-12)
    stats = {}
    loop_obj = FO[np.repeat(np.arange(len(LS)), LT)] if len(LS) else np.zeros(0, np.int64)
    for gi, ob in enumerate(grounds):
        fi = np.nonzero(FO == gi)[0]
        degen = fi[AR[fi] < 1e-6]                 # no surface at all (< 1 mm2)
        tiny = int((AR[fi] < 1e-4).sum())         # info: small valid faces (< 1 cm2)
        thin = int((THK[fi] < 1e-3).sum())        # info: slivers thinner than 1 mm (valid, watertight)
        flipped = fi[NZ[fi] < -0.5]
        vi = np.unique(LV[loop_obj == gi])
        me = ob.data
        loose = len(me.vertices) - len(vi)
        co = V[vi] if len(vi) else np.zeros((0, 3))
        dup = 0
        if len(co):
            qk = np.round(co * Q).astype(np.int64)
            _, cnt = np.unique(qk, axis=0, return_counts=True)
            dup = int((cnt > 1).sum())
        stats[names[gi]] = {"faces": int(len(fi)), "area_m2": round(float(AR[fi][NZ[fi] > 0.5].sum()), 1), "degenerate": int(len(degen)), "tiny_faces": tiny, "thin_slivers": thin,
                            "flipped": int(len(flipped)), "loose_verts": int(loose), "duplicate_verts": dup}
        for i in flipped[:200]:
            c = V[allF[i]].mean(0); issue("flipped_face", 2, *c, obj=ob.name)
        for i in degen[:50]:
            c = V[allF[i]].mean(0); issue("degenerate_face", 1, *c, obj=ob.name)
        log(f"  {ob.name}: {len(fi)} faces, degen {len(degen)}, flipped {len(flipped)}, loose {loose}, dup {dup}")

    # ---- 2 global seams: loop-based hole detection (shared with the repair stage)
    A = rg.analyse(grounds, data=data, log=log)
    A["_NZ"] = NZ
    GV = A["GV"]
    ring_poly = A["ring"]
    RZ_ = float(np.hypot(*np.asarray(ring_poly.exterior.coords).T).max())
    for h in A["holes"]:
        cats = Counter(names[FO[e[2]]] for e in h["e"])
        issue("hole", 3, *h["c"], area=round(h["area"], 3), n_edges=len(h["v"]), cat=cats.most_common(1)[0][0])
    if A["tjunctions"]:
        issue("tjunction", 1, 0, 0, 0, count=len(A["tjunctions"]),
              note="closed zero-area boundary loops (long edge on one side, several on the other): no visible gap")
    for c in A["chains"]:
        if c["length"] > rg.OPEN_MIN_LEN:
            cats = Counter(names[FO[e[2]]] for e in c["e"])
            issue("open_chain", 2, *c["c"], length=round(c["length"], 2), gap=round(c["gap"], 3), n_edges=len(c["e"]),
                  cat=cats.most_common(1)[0][0])
    for (c, n) in cluster(A["nonmanifold_mid"], 2.0):
        issue("nonmanifold_edge", 3, *c, n_edges=int(n))
    # vertical wall ends: z-intervals at one XY must pair up, otherwise the end of a step wall is open
    cand = A["b_cand"]
    ba, bb = A["b_a"][cand], A["b_b"][cand]
    dxy = np.hypot(*(GV[bb, :2] - GV[ba, :2]).T) if len(ba) else np.zeros(0)
    near_ring = ring_poly.exterior.buffer(8.0)
    byxy = defaultdict(list)
    for a, b in zip(ba[dxy < 1e-3], bb[dxy < 1e-3]):
        byxy[tuple(np.round(GV[a, :2] * 100).astype(np.int64))].append(sorted((GV[a, 2], GV[b, 2])))
    tj = 0
    for k, iv in byxy.items():
        ends = defaultdict(int)
        for z0, z1 in iv:
            ends[round(z0, 3)] += 1; ends[round(z1, 3)] += 1
        if not [z for z, n in ends.items() if n % 2]:
            tj += 1; continue
        x, y = k[0] / 100, k[1] / 100
        zlo = min(z for z, _ in iv); zhi = max(z for _, z in iv)
        issue("wall_end_hole", 1 if near_ring.contains(Point(x, y)) else 3, x, y, zlo, height=round(zhi - zlo, 2))
    if tj:
        issue("tjunction_vertical", 1, 0, 0, 0, count=tj)
    log("vertical open locations", len(byxy), "vertical t-junctions", tj)
    pairs = A["pairs"]
    log("adjacent face pairs", len(pairs))

    # ---- 3 z-fighting: interior overlaps of horizontal faces from different objects
    hor = np.nonzero(NZ > 0.5)[0]
    geoms = shapely.polygons([V[allF[i]][:, :2] for i in hor])
    valid = shapely.is_valid(geoms) & (shapely.area(geoms) > 1e-5)
    hor = hor[valid]; geoms = geoms[valid]
    tree = STRtree(geoms)
    zf = []
    for pred in ("overlaps", "contains"):
        a, b = tree.query(geoms, predicate=pred)
        m = a != b
        a, b = a[m], b[m]
        if len(a):
            ia = shapely.area(shapely.intersection(geoms[a], geoms[b]))
            m2 = ia > 0.01
            for i, j, ar in zip(a[m2], b[m2], ia[m2]):
                fi, fj = hor[i], hor[j]
                za = V[allF[fi]][:, 2].mean(); zb = V[allF[fj]][:, 2].mean()
                zf.append((fi, fj, ar, abs(za - zb)))
    seen = set(); zc = []
    for fi, fj, ar, dz in zf:
        k = (min(fi, fj), max(fi, fj))
        if k in seen:
            continue
        seen.add(k)
        c = V[allF[fi]].mean(0)
        zc.append((c, ar, dz, names[FO[fi]], names[FO[fj]]))
    log("overlapping face pairs", len(zc))
    for c, ar, dz, na, nb in zc[:2000]:
        issue("overlap_zfight" if dz < 0.05 else "overlap_stacked", 3 if dz < 0.05 else 2, *c, area=round(float(ar), 3), dz=round(float(dz), 3), a=na, b=nb)

    # ---- 4 logic: components per category using face adjacency
    nF = len(allF)
    par = np.arange(nF)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x

    cat_of = np.array(names)[FO]
    same = pairs[cat_of[pairs[:, 0]] == cat_of[pairs[:, 1]]] if len(pairs) else pairs
    for i, j in same:
        ri, rj = find(i), find(j)
        if ri != rj:
            par[ri] = rj
    root = np.array([find(i) for i in range(nF)])
    comp_area = defaultdict(float); comp_faces = defaultdict(list)
    for i in range(nF):
        if NZ[i] > 0.5:
            comp_area[root[i]] += AR[i]
        comp_faces[root[i]].append(i)
    nb = defaultdict(set)
    for i, j in pairs:
        ri, rj = root[i], root[j]
        if ri != rj:
            nb[ri].add(cat_of[j]); nb[rj].add(cat_of[i])
    fp = json.load(open(os.path.join(DATADIR, "zone_footprints_local.json")))
    # np object array: STRtree.query needs object dtype, also for a tile with no buildings (park / railway tile)
    fpoly = np.array([Polygon(f["outer"], f.get("inner") or []) for f in fp] or [Polygon()], dtype=object)[:len(fp)]
    out_rings = rg.outline_rings()
    fline_tree = STRtree(out_rings) if out_rings else STRtree([p.exterior for p in fpoly])
    bl = [o for o in bpy.data.objects if o.type == 'MESH' and o.users_collection and o.users_collection[0].name.startswith("Z1_Buildings")]
    fps = []
    for o in bl:
        co = mesh_arrays(o)[0]
        fps.append((o.name, shapely.MultiPoint(co[:, :2]).convex_hull, float(co[:, 2].min()), float(co[:, 2].max())))
    log("building objects", len(fps), "footprints", len(fpoly))
    ftree = STRtree(fpoly)
    HARD_PED = {"Sidewalk_Paving", "Path_Paving", "Entrance_Paving", "Forecourt_Paving", "Apron_Concrete", "Yard_Hard", "Crosswalk", "Cycleway"}
    ring_edge = ring_poly.exterior   # zone border (circle in zone mode, tile square in city mode)
    for r, fl in comp_faces.items():
        cat = cat_of[fl[0]]; ar = comp_area[r]
        vx = np.concatenate([V[allF[f]] for f in fl])
        near_border = float(shapely.distance(shapely.points(vx[:, :2]), ring_edge).min()) < 3.0
        cen = vx.mean(0)
        if ar < 0.5 and cat not in ("Road_Marking", "Curb", "Crosswalk", "Aryk", "Channel_Bank") and NZ[fl[0]] > 0.5:
            issue("sliver", 1, *cen, cat=cat, area=round(ar, 3))
        if cat == "Asphalt_Road" and 0.05 <= ar < 60 and not near_border and not (nb[r] & {"Parking_Asphalt", "Parking_Lane", "Crosswalk", "Road_Marking"}):
            issue("road_fragment", 2, *cen, area=round(ar, 1), touches=sorted(nb[r]))
        if cat == "Path_Paving" and not near_border:
            if not (nb[r] & (HARD_PED | {"Playground", "Sport_Pitch", "Curb"})):
                issue("path_dead_island", 2, *cen, area=round(ar, 1), touches=sorted(nb[r]))
        if cat == "Parking_Asphalt" and not near_border and not (nb[r] & {"Asphalt_Road", "Curb", "Yard_Hard", "Parking_Lane", "Road_Marking"}):
            issue("parking_no_access", 2, *cen, area=round(ar, 1), touches=sorted(nb[r]))
        if cat == "Playground" and not (nb[r] & (HARD_PED | {"Curb"})):
            issue("playground_no_path", 1, *cen, area=round(ar, 1), touches=sorted(nb[r]))
        if cat == "Entrance_Paving" and not near_border:
            mp = shapely.MultiPoint(vx[:, :2])
            if not len(fline_tree.query(mp, predicate="dwithin", distance=0.5)):
                issue("entrance_not_at_building", 2, *cen, area=round(ar, 1), touches=sorted(nb[r]))
        if cat == "Crosswalk":
            sides = nb[r] & ((HARD_PED - {"Crosswalk"}) | {"Curb"})
            if not sides:
                issue("crosswalk_no_sidewalk", 2, *cen, touches=sorted(nb[r]))

    # ---- 5 trees on hard surfaces / in buildings
    tri_geoms = geoms; tri_cat = cat_of[hor]
    tp = None
    ti = bpy.data.objects.get("Z1_Trees_Instancer")
    if ti is not None:
        co, *_ = mesh_arrays(ti); tp = co
    if tp is not None and len(tp):
        pts = shapely.points(tp[:, :2])
        a, b = tree.query(pts, predicate="within")
        cats = defaultdict(str)
        for i, j in zip(a, b):
            cats[i] = tri_cat[j]
        BAD = {"Asphalt_Road", "Crosswalk", "Parking_Asphalt", "Parking_Lane", "Sidewalk_Paving", "Road_Marking", "Playground",
               "Sport_Pitch", "Entrance_Paving", "Water", "Water_Channel", "Curb", "Cycleway"}
        nb_bad = 0
        for i, c in cats.items():
            if c in BAD:
                nb_bad += 1; issue("tree_on_hard", 1, *tp[i], cat=c)
        a, b = ftree.query(pts, predicate="within")
        for i, j in zip(a, b):
            issue("tree_in_building", 2, *tp[i])
        log("trees", len(tp), "on hard", nb_bad, dict(Counter(c for c in cats.values() if c in BAD)))

    # ---- 6 buildings
    a, b = ftree.query(fpoly, predicate="intersects")
    m = a < b
    for i, j in zip(a[m], b[m]):
        g = fpoly[i].intersection(fpoly[j])
        if g.area > 0.5:
            issue("building_overlap", 2, g.centroid.x, g.centroid.y, area=round(g.area, 1))
    road_u = [tri_geoms[k] for k in np.nonzero(np.isin(tri_cat, ["Asphalt_Road", "Parking_Asphalt", "Crosswalk", "Parking_Lane"]))[0]]
    rtree = STRtree(road_u) if road_u else None
    if rtree is not None:
        a, b = rtree.query(fpoly, predicate="intersects")
        acc = defaultdict(float)
        for i, j in zip(a, b):
            acc[i] += fpoly[i].intersection(road_u[j]).area
        for i, ar in acc.items():
            if ar > 1.0:
                c = fpoly[i].centroid; issue("building_on_road", 2, c.x, c.y, area=round(ar, 1))
    # floating: exact lowest ground height inside (plan hull + 1 m), evaluated on the clipped face planes
    P0 = np.array([V[allF[f][0]] for f in hor]); P1 = np.array([V[allF[f][1]] for f in hor]); P2 = np.array([V[allF[f][2]] for f in hor])
    Nf = np.cross(P1 - P0, P2 - P0)
    for nm, hull, zmin, zmax in fps:
        region = hull.buffer(1.0)
        ids = tree.query(region, predicate="intersects")
        if not len(ids):
            continue
        clip = shapely.intersection(geoms[ids], region)
        xy, gi_ = shapely.get_coordinates(clip, return_index=True)
        if not len(xy):
            continue
        t = ids[gi_]
        nz_ = Nf[t, 2]
        ok = np.abs(nz_) > 1e-12
        zg = P0[t, 2] - (Nf[t, 0] * (xy[:, 0] - P0[t, 0]) + Nf[t, 1] * (xy[:, 1] - P0[t, 1])) / np.where(ok, nz_, 1.0)
        zg = zg[ok]
        if len(zg) and zmin > zg.min() + 0.02:
            c = hull.centroid; issue("building_floating", 3, c.x, c.y, zmin, bld=nm, gap=round(zmin - float(zg.min()), 2))

    # ---- 7 terrain seam (ribbon-aware)
    ter = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith("Terrain_")]
    seam = seam_check(A, ter, ring_poly) if ter else {}

    counts = Counter(it["type"] for it in ISS)
    summary = {}
    for t_, n_ in counts.items():
        its = [it for it in ISS if it["type"] == t_]
        summary[t_] = int(sum(it.get("count", 1) for it in its)) if all("count" in it for it in its) else int(n_)
    sev = Counter(str(it["sev"]) for it in ISS)
    out = {"when": time.strftime("%Y-%m-%d %H:%M"), "blend": bpy.data.filepath,
           "summary": dict(sorted(summary.items())), "severity": {k: sev[k] for k in sorted(sev)},
           "ground_boundary": A["counts"], "terrain_seam": seam,
           "objects": stats, "issue_counts": dict(counts), "issues": ISS}
    json.dump(out, open(os.path.join(DATADIR, "qa_geometry.json"), "w"), indent=1)
    log("SUMMARY", out["summary"])
    log("SEVERITY", out["severity"])
    if make_markers:
        markers()
    return out


def markers():
    """one point per issue in object _QA_Markers (attribute 'issue' = type index), shown as small spheres via GN-free vertex display"""
    old = bpy.data.objects.get("_QA_Markers")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    if not ISS:
        return
    types = sorted({i["type"] for i in ISS})
    me = bpy.data.meshes.new("_QA_Markers")
    me.from_pydata([(i["x"], i["y"], i["z"] + 2.0) for i in ISS], [], [])
    at = me.attributes.new("issue", "INT", "POINT")
    at.data.foreach_set("value", [types.index(i["type"]) for i in ISS])
    ob = bpy.data.objects.new("_QA_Markers", me)
    ob["issue_types"] = json.dumps(types)
    bpy.context.scene.collection.objects.link(ob)


if __name__ == "__main__":
    main(make_markers=False)
