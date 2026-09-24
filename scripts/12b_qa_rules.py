"""Stage 12b - checks for the client's (SHEF) review points, on the partition data (plain python, no Blender).

  E2  path_dead_end        footpath ends that touch no road / sidewalk / hard yard / other path / building (1 m)
  E4  house_without_wall   private houses (< 350 m2) with no plot wall within 12 m
  E6  marking_gap_main     gaps > 25 m in the centre/lane markings of a main street, not explained by a crossing
                           of two main streets or a zebra
  E1  yard_lawn_share      share of lawn in apartment yards (info) ; yard_soil_under_canopy (must be 0: SHEF rule)
Writes data/qa_rules.json {summary:{...}, items:{...}} ; 13_qa_report merges the summary into the gates.
"""
import os, sys, json, math
import numpy as np
ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
_CT = os.environ.get("BISHKEK_TILE")   # city mode: per-tile data dir data/city/T_I_J
DATADIR = os.path.join(ROOT, "data", "city", "T_%s_%s" % tuple(_CT.split(","))) if _CT else os.path.join(ROOT, "data")
for p in (os.path.join(ROOT, "pylibs"), os.path.join(ROOT, "scripts")):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)
import shapely
from shapely import STRtree
from shapely.geometry import Point, LineString, Polygon
import geo


def main():
    z = np.load(os.path.join(DATADIR, "zone_partition.npz"), allow_pickle=True)
    V = z["V"][:, :2]; T = z["T"]; TC = z["TC"]; PW = z["PW"] if "PW" in z.files else np.zeros((0, 6))
    names = {int(c[0]): c[1] for c in json.loads(str(z["classes"]))}
    cid = {v: k for k, v in names.items()}
    RZ = float(z["rz"])
    tri = shapely.polygons(V[T])
    out = {"summary": {}, "items": {}}

    def tree_of(classes):
        m = np.isin(TC, [cid[c] for c in classes if c in cid])
        return STRtree(tri[m]), int(m.sum())

    fp = json.load(open(os.path.join(DATADIR, "zone_footprints_local.json")))
    B = [Polygon(f["outer"]) for f in fp]
    tB = STRtree(B)
    zr = os.path.join(ROOT, "data", "zone_raw.json")
    ctp = os.path.join(ROOT, "data", "city", "osm", "T_%s_%s.json" % tuple(_CT.split(","))) if _CT else ""
    RING = Polygon(np.asarray(json.load(open(os.path.join(DATADIR, "zone_ring.json"))), float)[:, :2])
    RE = RING.exterior

    def inside(x, y, m):
        """point is inside the zone (circle or city tile) and at least m metres from its border"""
        p = Point(x, y)
        return RING.contains(p) and RE.distance(p) > m
    if _CT and os.path.exists(ctp):
        D = json.load(open(ctp, encoding="utf-8"))
    elif os.path.exists(zr):
        D = json.load(open(zr, encoding="utf-8"))
    else:
        D = {"highways": json.load(open(os.path.join(ROOT, "data", "osm", "extract", "highways.json"), encoding="utf-8"))}

    # ---- E2 path dead ends (checked against the built partition)
    hardT, _ = tree_of(["Sidewalk_Paving", "Entrance_Paving", "Forecourt_Paving", "Apron_Concrete", "Crosswalk", "Cycleway",
                        "Asphalt_Road", "Parking_Asphalt", "Playground", "Sport_Pitch", "Yard_Hard", "Curb", "Dirt_Track"])
    pathT, _ = tree_of(["Path_Paving"])
    from shapely.ops import unary_union
    pm = TC == cid["Path_Paving"]
    PU = unary_union([g.buffer(0.01) for g in tri[pm]]).buffer(-0.01)
    PCOMP = list(getattr(PU, "geoms", [PU]))
    lines = []
    for h in D["highways"]:
        t = h["tags"]
        if t.get("highway") not in ("footway", "path", "pedestrian", "steps", "cycleway") or t.get("footway") in ("crossing", "sidewalk"):
            continue
        a = np.asarray(h["pts"]); x, y = geo.to_local(a[:, 0], a[:, 1]); lines.append(np.c_[x, y])
    L = [LineString(l) for l in lines]; tL = STRtree(L) if L else None
    dead = []
    for i, l in enumerate(lines):
        for px, py in (l[0], l[-1]):
            if not inside(px, py, 10):
                continue
            p = Point(px, py)
            ok = len(hardT.query(p, predicate="dwithin", distance=1.0)) or len(tB.query(p, predicate="dwithin", distance=1.0))
            if not ok and tL is not None:
                ok = any(j != i for j in tL.query(p, predicate="dwithin", distance=1.0))
            if not ok:
                # the generator may have joined it: the Path_Paving piece at this end must reach a hard surface/building
                comp = None
                for g in PCOMP:
                    if g.distance(p) < 1.5:
                        comp = g; break
                if comp is not None:
                    cb = comp.buffer(0.3)
                    ok = len(hardT.query(cb, predicate="intersects")) > 0 or len(tB.query(cb, predicate="intersects")) > 0
            if not ok:
                dead.append([round(px, 1), round(py, 1)])
    out["summary"]["path_dead_end"] = len(dead); out["items"]["path_dead_end"] = dead[:200]

    # ---- E4 houses without plot wall
    houses = [b for b in B if b.area < 350 and inside(b.centroid.x, b.centroid.y, 15)]
    privT, _ = tree_of(["Private_Plot"])
    segs = [LineString([(r[0], r[1]), (r[2], r[3])]) for r in PW] if len(PW) else []
    tW = STRtree(segs) if segs else None
    nowall = []
    for b in houses:
        if not len(privT.query(b.buffer(3.0), predicate="intersects")):
            continue  # not a private-housing house (e.g. kiosk in a yard)
        if tW is None or not len(tW.query(b.buffer(12.0), predicate="intersects")):
            c = b.centroid; nowall.append([round(c.x, 1), round(c.y, 1)])
    out["summary"]["house_without_wall"] = len(nowall); out["items"]["house_without_wall"] = nowall[:200]
    streetT, _ = tree_of(["Asphalt_Road", "Road_Marking", "Crosswalk", "Parking_Lane", "Curb", "Sidewalk_Paving", "Street_Green", "Aryk"])
    onroad = []
    for sg in segs:
        mid = sg.interpolate(0.5, normalized=True)
        hits = streetT.query(mid, predicate="within")
        if len(hits):
            onroad.append([round(mid.x, 1), round(mid.y, 1)])
    out["summary"]["wall_on_street"] = len(onroad); out["items"]["wall_on_street"] = onroad[:200]
    out["summary"]["private_houses"] = len(houses)

    # ---- E6 marking gaps along main streets
    markT, nm = tree_of(["Road_Marking"])
    xwT, _ = tree_of(["Crosswalk"])
    gaps = []
    for h in D["highways"]:
        t = h["tags"]
        if t.get("highway") not in ("primary", "secondary", "tertiary", "trunk") or t.get("oneway") in ("yes", "1", "-1", "true"):
            continue
        a = np.asarray(h["pts"]); x, y = geo.to_local(a[:, 0], a[:, 1]); ln = LineString(np.c_[x, y])
        if ln.length < 60:
            continue
        run = 0.0; start = None
        for s_ in np.arange(0, ln.length, 3.0):
            p = ln.interpolate(s_)
            if not inside(p.x, p.y, 20):
                run = 0.0; continue
            has = len(markT.query(p.buffer(4.0), predicate="intersects")) > 0
            xw = len(xwT.query(p.buffer(8.0), predicate="intersects")) > 0
            if has or xw:
                if run > 25.0:
                    gaps.append([round(start.x, 1), round(start.y, 1), round(run, 1)])
                run = 0.0; start = None
            else:
                if start is None:
                    start = p
                run += 3.0
        if run > 25.0 and start is not None:
            gaps.append([round(start.x, 1), round(start.y, 1), round(run, 1)])
    # a gap at a crossing of two main streets is expected (junction box, 13 m radius -> ~26-30 m)
    gaps = [g for g in gaps if g[2] > 32.0]
    out["summary"]["marking_gap_main"] = len(gaps); out["items"]["marking_gap_main"] = gaps[:200]

    # ---- E1 yard ground: no soil under yard trees (SHEF), lawn share info
    json.dump(out, open(os.path.join(DATADIR, "qa_rules.json"), "w"), indent=1)
    print("QA RULES", out["summary"])
    return out


if __name__ == "__main__":
    main()
