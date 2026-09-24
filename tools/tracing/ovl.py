"""Overlay of the current model (partition classes + building footprints) on a Yandex z19 view.
usage: python ovl.py LON LAT [out.js]   -> JS that draws an SVG over the page (toggle: window.__ov(0/1))"""
import sys, os, json, pickle, math
import numpy as np
from shapely.geometry import Polygon, box, LineString
from shapely.ops import unary_union
HERE = os.path.dirname(os.path.abspath(__file__)); DEV = os.path.dirname(HERE)
sys.path.insert(0, HERE); os.chdir(DEV)
import scr2local
CACHE = os.path.join(DEV, "data", "_ovl_cache.pkl")
STYLE = {  # class: (stroke, width, fill)
    "Asphalt_Road": ("#ffffff", 1.2, "none"), "Sidewalk_Paving": ("#ffd400", 1.0, "none"),
    "Parking_Asphalt": ("#ff00ff", 2.0, "rgba(255,0,255,0.15)"), "Parking_Lane": ("#ff00ff", 2.0, "rgba(255,0,255,0.25)"),
    "Playground": ("#ff2020", 2.2, "rgba(255,0,0,0.20)"), "Sport_Pitch": ("#ff8800", 1.6, "none"),
    "Path_Paving": ("#ffaa66", 1.0, "none"), "Forecourt_Paving": ("#c080ff", 1.2, "none"),
    "Entrance_Paving": ("#c080ff", 1.0, "none"), "Lawn": ("#40ff40", 0.8, "none"),
}


def load():
    if os.path.exists(CACHE) and os.path.getmtime(CACHE) > os.path.getmtime("data/zone_partition.npz"):
        return pickle.load(open(CACHE, "rb"))
    z = np.load("data/zone_partition.npz", allow_pickle=True)
    V, T, TC = z["V"][:, :2], z["T"], z["TC"]
    names = {int(c[0]): c[1] for c in json.loads(str(z["classes"]))}
    out = {}
    for cid, nm in names.items():
        if nm not in STYLE:
            continue
        idx = np.nonzero(TC == cid)[0]
        if not len(idx):
            continue
        polys = [Polygon(V[t]) for t in T[idx]]
        out[nm] = unary_union([p for p in polys if p.area > 1e-6]).buffer(0.01).buffer(-0.01)
    fp = json.load(open("data/zone_footprints_local.json"))
    out["_bld"] = [Polygon(f["outer"]) for f in fp]
    pickle.dump(out, open(CACHE, "wb"))
    return out


def rings(g):
    if g.is_empty:
        return []
    gs = [g] if g.geom_type == "Polygon" else [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]
    r = []
    from shapely.geometry import Polygon as _P
    for p in gs:
        if p.area < 4:
            continue
        r.append(list(p.exterior.coords)); r += [list(i.coords) for i in p.interiors if _P(i).area > 8]
    return r


def main():
    lon, lat = float(sys.argv[1]), float(sys.argv[2]); zz = int(sys.argv[3]) if len(sys.argv) > 3 else 19
    outp = sys.argv[4] if len(sys.argv) > 4 else "/tmp/ov_view.js"
    s2l, l2s = scr2local.make(lon, lat, zz)
    xs = [s2l(0, 0)[0], s2l(800, 700)[0]]; ys = [s2l(0, 0)[1], s2l(800, 700)[1]]
    vb = box(min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5)
    if os.environ.get("FOCUS"):
        from shapely.geometry import Point
        foc = unary_union([Point(*map(float, f.split(",")[:2])).buffer(float(f.split(",")[2])) for f in os.environ["FOCUS"].split(";")])
        vb = vb.intersection(foc)
    L = load(); parts = []
    def path(rs):
        d = []
        for r in rs:
            pts = [l2s(x, y) for x, y in r]
            d.append("M" + "L".join(f"{a:.0f} {b:.0f}" for a, b in pts) + "Z")
        return " ".join(d)
    for nm, (st, w, fi) in STYLE.items():
        if nm not in L or (zz < 19 and nm in ("Lawn",)):
            continue
        g = L[nm].intersection(vb).simplify(0.3 if zz >= 19 else 0.6)
        rs = rings(g)
        if rs:
            parts.append(f'<path d="{path(rs)}" fill="{fi}" fill-rule="evenodd" stroke="{st}" stroke-width="{w}"/>')
    b = [p for p in L["_bld"] if p.intersects(vb)]
    if b:
        parts.append(f'<path d="{path([list(p.exterior.coords) for p in b])}" fill="none" stroke="#00ffff" stroke-width="1.2"/>')
    if os.environ.get("WALLS"):
        zz_ = np.load("data/zone_partition.npz", allow_pickle=True)
        PWa = zz_["PW"] if "PW" in zz_.files else np.zeros((0, 6))
        segs_ = []
        for w in PWa:
            if vb.intersects(LineString([(w[0], w[1]), (w[2], w[3])])):
                a_ = l2s(w[0], w[1]); b_ = l2s(w[2], w[3])
                segs_.append(f"M{a_[0]:.0f} {a_[1]:.0f}L{b_[0]:.0f} {b_[1]:.0f}")
        if segs_:
            parts.append(f'<path d="{" ".join(segs_)}" fill="none" stroke="#ff4040" stroke-width="2"/>')
    pv = json.load(open("data/playgrounds_to_verify.json"))
    for i, p in enumerate(pv):
        pg = Polygon(p["poly"])
        if pg.intersects(vb):
            parts.append(f'<path d="{path([list(pg.exterior.coords)])}" fill="none" stroke="#ff3030" stroke-width="2" stroke-dasharray="5,3"/>')
            tx, ty = l2s(p["x"], p["y"])
            parts.append(f'<text x="{tx:.0f}" y="{ty:.0f}" fill="#fff" stroke="#000" stroke-width="0.6" font-size="14" font-weight="bold" text-anchor="middle">P{i}</text>')
    sx, sy = l2s(0, 0)
    parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="5" fill="red"/>')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="700" style="position:fixed;left:0;top:0;z-index:99999;pointer-events:none">' + "".join(parts) + "</svg>"
    js = ("(()=>{let d=document.getElementById('osmov'); if(d) d.remove(); d=document.createElement('div'); d.id='osmov'; d.innerHTML=" + json.dumps(svg) +
          "; document.body.appendChild(d); window.__ov=(v)=>{d.style.display=v?'block':'none'}; return 'ok '+" + json.dumps(f"view local x {min(xs):.0f}..{max(xs):.0f} y {min(ys):.0f}..{max(ys):.0f}") + "})()")
    open(outp, "w").write(js)
    print("view local x %.0f..%.0f  y %.0f..%.0f  -> %s (%d bytes)" % (min(xs), max(xs), min(ys), max(ys), outp, len(js)))


if __name__ == "__main__":
    main()
