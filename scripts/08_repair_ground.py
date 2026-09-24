"""Stage 08 - automatic repair of the ground surface (runs inside Blender, called by 07 before saving).

All GROUND_* category objects together must form one closed surface, except along building outlines
(the ground is cut there, the building covers it) and at the outer 1 km ring (closed by Z1_Seam_Ribbon).

Shared analysis (also used by 12_qa_geometry.py, so QA and repair always agree):
  1  vertices of all categories get one global identity by position (1 mm grid + merge of keys in the
     neighbouring cells, i.e. pairs that straddle a grid line)
  2  edges used by exactly one face = boundary edges; the ones on building outlines (outer rings and
     courtyards, 0.3 m) or outside the ring (buffer -0.5 m) are intended
  3  the remaining directed boundary edges are chained (hole on the right, tightest turn at pinch points):
       closed loop with vector area > 0.01 m2  -> hole
       closed loop with ~zero area            -> t-junction (long edge on one side, several on the other;
                                                 no visible gap)
       chain that does not close              -> open chain
Repair:
  every hole with <= 64 edges and <= 200 m2 and every open chain whose ends are within 0.05 m is filled:
  triangulated in its own plane (works for vertical wall-end slots too), winding reversed so the new edges
  pair with the neighbours, added to the GROUND object that owns most of the loop's edges (the category
  objects are never merged), world-metre UVs. A second pass picks up loops exposed by the first one.
Returns a dict with counts (also logged).
"""
import os, sys, json, math
from collections import defaultdict, Counter
import numpy as np
import bpy

ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
_CT = os.environ.get("BISHKEK_TILE")   # city mode: per-tile data dir data/city/T_I_J
DATADIR = os.path.join(ROOT, "data", "city", "T_%s_%s" % tuple(_CT.split(","))) if _CT else os.path.join(ROOT, "data")
for p in (os.path.join(ROOT, "pylibs"), os.path.join(ROOT, "scripts")):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)

HOLE_MIN_AREA = 0.01     # m2: smaller closed loops are t-junctions / hairlines (no visible gap)
OPEN_MIN_LEN = 0.3       # m : shorter open chains are ignored by QA
BLD_TOL = 0.3            # m : boundary edges this close to a building outline are intended
RING_IN = 0.5            # m : boundary edges this close to the zone ring (or outside) are intended


# ------------------------------------------------------------------------------------------ data
def _arrays(ob):
    me = ob.data
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    mw = np.array(ob.matrix_world)
    if not np.allclose(mw, np.eye(4)):
        co = co @ mw[:3, :3].T + mw[:3, 3]
    ls = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", lt)
    lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv)
    return co, ls, lt, lv


def ground_objects():
    return sorted([o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith("GROUND_")], key=lambda o: o.name)


def collect(grounds):
    """all GROUND objects as one indexed face set: V (world), ls/lt (per face), lv (global vertex index per loop),
    fobj (object index per face)"""
    Vs, LS, LT, LV, FO = [], [], [], [], []
    voff = 0; loff = 0
    for gi, o in enumerate(grounds):
        co, ls, lt, lv = _arrays(o)
        Vs.append(co); LS.append(ls + loff); LT.append(lt); LV.append(lv + voff); FO.append(np.full(len(ls), gi, np.int64))
        voff += len(co); loff += len(lv)
    if not Vs:
        z = np.zeros(0, np.int64)
        return np.zeros((0, 3)), z, z, z, z
    return np.concatenate(Vs), np.concatenate(LS), np.concatenate(LT), np.concatenate(LV), np.concatenate(FO)


def _global_ids(V, q=1000.0):
    """position identity with 1 mm grid + merge of keys in neighbouring cells (pairs straddling a grid line).
    The result depends only on the order of first occurrence of each key (same as a plain per-vertex loop)."""
    if len(V) == 0:
        return np.zeros(0, np.int64), 0
    K = np.round(np.asarray(V) * q).astype(np.int64)
    uk, first, inv = np.unique(K, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    order = np.argsort(first, kind="stable")
    keymap = {}
    uid = np.empty(len(uk), np.int64)
    n = 0
    nb = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if not (dx == dy == dz == 0)]
    for u in order:
        k = tuple(uk[u])
        j = None
        for dx, dy, dz in nb:
            j = keymap.get((k[0] + dx, k[1] + dy, k[2] + dz))
            if j is not None:
                break
        if j is None:
            j = n; n += 1
        keymap[k] = j
        uid[u] = j
    return uid[inv], n


def outline_rings():
    """building outlines where the ground is intentionally open: every hole the partition cut for buildings
    (data/zone_ground_holes.json, includes buildings crossing the ring) + the zone footprints (outer and inner)"""
    import shapely
    rings = []
    for fn in ("zone_ground_holes.json", "zone_footprints_local.json"):
        p = os.path.join(DATADIR, fn)
        if not os.path.exists(p):
            continue
        for f in json.load(open(p)):
            for r in [f["outer"]] + list(f.get("inner") or []):
                if len(r) >= 4:
                    rings.append(shapely.LinearRing(r))
    return rings


def zone_ring():
    import shapely
    ring = json.load(open(os.path.join(DATADIR, "zone_ring.json")))
    xy = np.asarray(ring["outer"] if isinstance(ring, dict) else ring, float)[:, :2]
    return shapely.Polygon(xy)


# ------------------------------------------------------------------------------------------ analysis
def _newell(P):
    q = np.roll(P, -1, axis=0)
    return np.array([np.sum((P[:, 1] - q[:, 1]) * (P[:, 2] + q[:, 2])),
                     np.sum((P[:, 2] - q[:, 2]) * (P[:, 0] + q[:, 0])),
                     np.sum((P[:, 0] - q[:, 0]) * (P[:, 1] + q[:, 1]))]) / 2.0


def _chain(ea, eb, GV):
    """split directed boundary edges into closed loops and open chains (hole kept on the right side)"""
    n = len(ea)
    out = defaultdict(list)
    for i in range(n):
        out[int(ea[i])].append(i)
    used = np.zeros(n, bool)
    loops, chains = [], []

    def pick(v, prev, start):
        opts = [i for i in out.get(v, ()) if not used[i]]
        if not opts:
            return None
        if len(opts) == 1:
            return opts[0]
        for i in opts:
            if eb[i] == start:
                return i
        d0 = GV[eb[prev], :2] - GV[ea[prev], :2]
        best, bang = opts[0], None
        if math.hypot(*d0) > 1e-6:
            for i in opts:
                d1 = GV[eb[i], :2] - GV[ea[i], :2]
                if math.hypot(*d1) < 1e-6:
                    continue
                ang = math.atan2(d0[0] * d1[1] - d0[1] * d1[0], d0[0] * d1[0] + d0[1] * d1[1])
                if bang is None or ang < bang:
                    best, bang = i, ang
        return best

    def walk(e0):
        pv = [int(ea[e0])]; pe = []
        pos = {pv[0]: 0}
        e = e0
        while e is not None:
            used[e] = True; pe.append(e)
            w = int(eb[e])
            k = pos.get(w)
            if k is not None:
                loops.append((pv[k:], pe[k:]))
                for v in pv[k + 1:]:
                    pos.pop(v, None)
                pv = pv[:k + 1]; pe = pe[:k]
            else:
                pos[w] = len(pv); pv.append(w)
            e = pick(w, e, pv[0])
        if pe:
            chains.append((pv, pe))

    indeg = Counter(int(b) for b in eb)
    starts = [i for i in range(n) if len(out[int(ea[i])]) > indeg.get(int(ea[i]), 0)]
    for i in starts:
        if not used[i]:
            walk(i)
    for i in range(n):
        if not used[i]:
            walk(i)
    return loops, chains


def analyse(grounds=None, data=None, log=None):
    """boundary analysis of the combined ground. data = collect(grounds) may be passed in to avoid re-reading."""
    import shapely
    from shapely import STRtree
    if grounds is None:
        grounds = ground_objects()
    V, LS, LT, LV, FO = data if data is not None else collect(grounds)
    res = {"grounds": grounds, "names": [o.name[7:] for o in grounds], "V": V, "LS": LS, "LT": LT, "LV": LV, "FO": FO}
    gid, ng = _global_ids(V)
    GV = np.zeros((ng, 3)); GV[gid] = V
    res["gid"] = gid; res["GV"] = GV
    nl = len(LV)
    face_of_loop = np.repeat(np.arange(len(LS)), LT)
    pos = np.arange(nl) - LS[face_of_loop]
    nxt = LS[face_of_loop] + (pos + 1) % LT[face_of_loop]
    a = gid[LV]; b = gid[LV[nxt]]
    keep = a != b
    a, b, f = a[keep], b[keep], face_of_loop[keep]
    lo = np.minimum(a, b); hi = np.maximum(a, b)
    key = lo * (ng + 1) + hi
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    ecount = cnt[inv]                       # use count of each directed edge's undirected edge
    res.update(ea=a, eb=b, ef=f, ekey_inv=inv, ecount=ecount, ukey_count=cnt)
    # adjacency pairs (exactly two faces) for logic checks
    o2 = np.argsort(inv, kind="stable")
    st = np.searchsorted(inv[o2], np.arange(len(uk)))
    two = np.nonzero(cnt == 2)[0]
    res["pairs"] = np.stack([f[o2[st[two]]], f[o2[st[two] + 1]]], 1) if len(two) else np.zeros((0, 2), np.int64)
    nm = np.nonzero(cnt > 2)[0]
    res["nonmanifold_mid"] = np.array([(GV[a[o2[st[k]]]] + GV[b[o2[st[k]]]]) / 2 for k in nm]).reshape(-1, 3)
    # boundary edges
    bi = np.nonzero(ecount == 1)[0]
    ba, bb, bf = a[bi], b[bi], f[bi]
    mid = (GV[ba] + GV[bb]) / 2
    ring = zone_ring()
    inner = ring.buffer(-RING_IN)
    in_zone = shapely.contains_xy(inner, mid[:, 0], mid[:, 1]) if len(mid) else np.zeros(0, bool)
    rings = outline_rings()
    on_b = np.zeros(len(bi), bool)
    if rings and len(bi):
        rt = STRtree(rings)
        ai, _ = rt.query(shapely.points(mid[:, :2]), predicate="dwithin", distance=BLD_TOL)
        on_b[ai] = True
    cand = in_zone & ~on_b
    res.update(b_a=ba, b_b=bb, b_f=bf, b_mid=mid, b_in_zone=in_zone, b_on_bld=on_b, b_cand=cand, ring=ring)
    ca, cb, cf = ba[cand], bb[cand], bf[cand]
    loops_raw, chains_raw = _chain(ca, cb, GV)
    loops, tj, chains = [], [], []
    for pv, pe in loops_raw:
        P = GV[pv]
        area = float(np.linalg.norm(_newell(P))) if len(pv) >= 3 else 0.0
        rec = {"v": pv, "e": [(int(ca[i]), int(cb[i]), int(cf[i])) for i in pe], "area": area, "n": len(pv),
               "c": P.mean(0)}
        (loops if area > HOLE_MIN_AREA else tj).append(rec)
    for pv, pe in chains_raw:
        P = GV[pv]
        L = float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())
        gap = float(np.linalg.norm(P[-1] - P[0]))
        area = float(np.linalg.norm(_newell(P))) if len(pv) >= 3 else 0.0
        chains.append({"v": pv, "e": [(int(ca[i]), int(cb[i]), int(cf[i])) for i in pe], "length": L, "gap": gap,
                       "area": area, "c": P.mean(0)})
    res.update(holes=loops, tjunctions=tj, chains=chains)
    res["counts"] = {"boundary_edges": int(len(bi)), "on_building": int(on_b.sum()), "at_ring": int((~in_zone).sum()),
                     "unintended": int(cand.sum()), "holes": len(loops), "hole_m2": round(sum(l["area"] for l in loops), 3),
                     "tjunction_loops": len(tj), "open_chains": len(chains),
                     "open_chains_long": sum(1 for c in chains if c["length"] > OPEN_MIN_LEN), "nonmanifold_edges": int(len(nm))}
    if log:
        log("ground boundary", res["counts"])
    return res


# ------------------------------------------------------------------------------------------ repair
def _triangulate_loop(P):
    """triangles (index triples into P) covering polygon P (3D, any plane), wound like P"""
    from mathutils import Vector
    from mathutils.geometry import tessellate_polygon
    N = _newell(P)
    tris = []
    try:
        tris = [tuple(t) for t in tessellate_polygon([[Vector(p) for p in P]])]
    except Exception:
        tris = []
    if len(tris) < len(P) - 2 - 1:   # scanfill gave up (degenerate input) -> fan
        tris = [(0, i, i + 1) for i in range(1, len(P) - 1)]
    out = []
    for i, j, k in tris:
        n = np.cross(P[j] - P[i], P[k] - P[i])
        if np.linalg.norm(n) < 2e-7:
            continue
        out.append((i, j, k) if np.dot(n, N) >= 0 else (i, k, j))
    return out


def _append_faces(o, tris):
    """append triangles (world coords) to object o, reusing its vertices by position (1 mm)"""
    me = o.data
    co, *_ = _arrays(o)
    mw = np.array(o.matrix_world); inv = np.linalg.inv(mw) if not np.allclose(mw, np.eye(4)) else None
    key = {}
    for i, k in enumerate(map(tuple, np.round(co * 1000).astype(np.int64))):
        key.setdefault(k, i)
    nv0 = len(me.vertices)
    newv = []; faces_new = []
    for tri in tris:
        idx = []
        for p in tri:
            k = tuple(np.round(np.asarray(p) * 1000).astype(np.int64))
            i = key.get(k)
            if i is None:
                i = nv0 + len(newv); newv.append(p); key[k] = i
            idx.append(i)
        if len(set(idx)) == 3:
            faces_new.append(idx)
    if not faces_new:
        return 0
    if newv:
        nv = np.asarray(newv, float)
        if inv is not None:
            nv = nv @ inv[:3, :3].T + inv[:3, 3]
        loc = np.empty(nv0 * 3); me.vertices.foreach_get("co", loc)
        me.vertices.add(len(newv))
        me.vertices.foreach_set("co", np.concatenate([loc, nv.ravel()]))
    nl0 = len(me.loops); np0 = len(me.polygons)
    me.loops.add(3 * len(faces_new)); me.polygons.add(len(faces_new))
    vi = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", vi)
    vi[nl0:] = np.array(faces_new, np.int32).ravel()
    me.loops.foreach_set("vertex_index", vi)
    starts = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_start", starts)
    starts[np0:] = np.arange(nl0, nl0 + 3 * len(faces_new), 3, dtype=np.int32)
    me.polygons.foreach_set("loop_start", starts)
    # world-metre UVs: plan (x, y) for flat faces, (along, z) for steep ones
    uv = me.uv_layers.get("UVMap")
    if uv is not None:
        d = np.empty(len(me.loops) * 2, np.float32); uv.data.foreach_get("uv", d); d = d.reshape(-1, 2)
        allco = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", allco); allco = allco.reshape(-1, 3)
        if inv is not None:
            allco = allco @ mw[:3, :3].T + mw[:3, 3]
        for fi, f in enumerate(faces_new):
            P = allco[f]; n = np.cross(P[1] - P[0], P[2] - P[0]); nn = np.linalg.norm(n) or 1.0
            li = nl0 + 3 * fi
            if abs(n[2]) / nn > 0.5:
                d[li:li + 3] = P[:, :2]
            else:
                h = np.array([-n[1], n[0]]); hl = np.hypot(*h) or 1.0; h = h / hl
                d[li:li + 3, 0] = P[:, 0] * h[0] + P[:, 1] * h[1]; d[li:li + 3, 1] = P[:, 2]
        uv.data.foreach_set("uv", d.ravel())
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    return len(faces_new)


def repair_ground(max_edges=64, max_area=200.0, close_tol=0.05, passes=2, log=print):
    grounds = ground_objects()
    if not grounds:
        return {}
    total = Counter(); skipped = []
    A = None
    for it in range(passes):
        A = analyse(grounds, log=None)
        GV, FO = A["GV"], A["FO"]
        work = [(h, False) for h in A["holes"]]
        work += [(c, True) for c in A["chains"] if c["gap"] <= close_tol and len(c["v"]) >= 3 and c["area"] > HOLE_MIN_AREA]
        add = defaultdict(list)
        n_fill = 0
        for rec, is_chain in work:
            if len(rec["v"]) > max_edges or rec["area"] > max_area:
                skipped.append((round(float(rec["c"][0]), 1), round(float(rec["c"][1]), 1), len(rec["v"]), round(rec["area"], 2)))
                continue
            P = GV[rec["v"]]
            owners = Counter(int(FO[fi]) for _, _, fi in rec["e"])
            oi = owners.most_common(1)[0][0]
            poly = P[::-1]                       # reversed: pairs with the neighbours' edges
            tris = _triangulate_loop(poly)
            if not tris:
                continue
            for i, j, k in tris:
                add[oi].append((poly[i], poly[j], poly[k]))
            n_fill += 1
            total["filled_chains" if is_chain else "filled_holes"] += 1
            total["filled_m2"] += rec["area"]
        nf = 0
        for oi, tris in add.items():
            nf += _append_faces(grounds[oi], tris)
        total["fill_faces"] += nf
        if it == 0:
            total["holes_found"] = len(A["holes"]); total["tjunction_loops"] = len(A["tjunctions"])
            total["open_chains"] = len(A["chains"])
        if n_fill == 0:
            break
    A = analyse(grounds, log=None) if total["fill_faces"] else A
    res = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in total.items()}
    res.update(remaining_holes=len(A["holes"]), remaining_hole_m2=round(sum(h["area"] for h in A["holes"]), 3),
               remaining_open_chains_long=sum(1 for c in A["chains"] if c["length"] > OPEN_MIN_LEN),
               skipped_large=len(set(skipped)))
    if skipped:
        res["skipped_examples"] = sorted(set(skipped), key=lambda s: -s[3])[:5]
    log("repair_ground", res)
    return res


if __name__ == "__main__":
    repair_ground()
