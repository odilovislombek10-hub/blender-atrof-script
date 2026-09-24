"""agent-west helpers.
  west.py nav X Y Z                 -> NAV url + AFTER ll
  west.py grid LON LAT Z STEP       -> print compact JS drawing a local-metre grid (labels every 5*STEP... every label step)
  west.py feat LON LAT Z FILE [F2]  -> print JS drawing traced features of tile json(s)
  west.py model LON LAT Z OUT       -> model overlay js (whole view) to OUT
"""
import sys, os, json, math, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); DEV = os.path.dirname(HERE)
sys.path.insert(0, HERE); os.chdir(DEV)
import geo, ymerc, scr2local


def nav(x, y, Z):
    kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0
    lon = geo.LON0 + x / kx; lat = geo.LAT0 + y / ky
    for _ in range(6):
        ex, ey = geo.to_local(lon, lat); lon += (x - ex) / kx; lat += (y - ey) / ky
    px, py = ymerc.to_px(lon, lat, Z)
    lon2, lat2 = ymerc.from_px(px + 210, py, Z)
    print(f"NAV https://yandex.uz/maps/10309/bishkek/sputnik/?ll={lon:.6f}%2C{lat:.6f}&z={Z}")
    print(f"AFTER {lon2:.6f},{lat2:.6f}")


def affine(lon, lat, Z):
    s2l, l2s = scr2local.make(lon, lat, Z)
    x0, y0 = s2l(400, 350)
    p0 = l2s(x0, y0); px = l2s(x0 + 100, y0); py = l2s(x0, y0 + 100)
    a = (px[0] - p0[0]) / 100; d = (px[1] - p0[1]) / 100
    b = (py[0] - p0[0]) / 100; e = (py[1] - p0[1]) / 100
    c = p0[0] - a * x0 - b * y0; f = p0[1] - d * x0 - e * y0
    return (a, b, c, d, e, f), s2l, l2s


def grid(lon, lat, Z, step):
    (a, b, c, d, e, f), s2l, l2s = affine(lon, lat, Z)
    xs = [s2l(0, 0)[0], s2l(800, 700)[0]]; ys = [s2l(0, 0)[1], s2l(800, 700)[1]]
    x0 = math.floor(min(xs) / step) * step; x1 = math.ceil(max(xs) / step) * step
    y0 = math.floor(min(ys) / step) * step; y1 = math.ceil(max(ys) / step) * step
    lab = int(os.environ.get('LAB', 2 * step))
    js = ("(()=>{let A=[%.5f,%.5f,%.3f,%.5f,%.5f,%.3f],P=(x,y)=>[A[0]*x+A[1]*y+A[2],A[3]*x+A[4]*y+A[5]];"
          "let s='';for(let x=%d;x<=%d;x+=%d){let p=P(x,%d),q=P(x,%d);s+=`<line x1=${p[0]} y1=${p[1]} x2=${q[0]} y2=${q[1]} stroke='%s' stroke-width='${x%%%d?0.6:1}'/>`}"
          "for(let y=%d;y<=%d;y+=%d){let p=P(%d,y),q=P(%d,y);s+=`<line x1=${p[0]} y1=${p[1]} x2=${q[0]} y2=${q[1]} stroke='%s' stroke-width='${y%%%d?0.6:1}'/>`}"
          "for(let x=%d;x<=%d;x+=%d)for(let y=%d;y<=%d;y+=%d){let p=P(x,y);s+=`<text x=${p[0]+2} y=${p[1]-2} font-size='10' fill='#ff0' stroke='#000' stroke-width='0.3'>${x},${y}</text>`}"
          "let g=document.getElementById('wgrid');if(g)g.remove();g=document.createElement('div');g.id='wgrid';"
          "g.innerHTML=`<svg width=800 height=700 style='position:fixed;left:0;top:0;z-index:99998;pointer-events:none'>${s}</svg>`;document.body.appendChild(g);"
          "window.__g=(v)=>{g.style.display=v?'block':'none'};return 'grid ok'})()") % (
        a, b, c, d, e, f, x0, x1, step, y0, y1, 'rgba(255,255,0,0.55)', lab, y0, y1, step, x0, x1, 'rgba(255,255,0,0.55)', lab,
        math.ceil(x0 / lab) * lab, x1, lab, math.ceil(y0 / lab) * lab, y1, lab)
    return js


COL = {"alley": "#ff00ff", "footpath": "#00ff66", "fence": "#ff3030", "area": "#00e5ff", "building_missing": "#ffffff", "building_gone": "#ff8800"}
ACOL = {"asphalt": "#9999ff", "concrete": "#dddddd", "paving": "#ffcc66", "soil": "#cc8844", "grass": "#44ff44", "gravel": "#bbbbbb",
        "rubber": "#ff4444", "turf": "#22cc22"}


def feat(lon, lat, Z, files):
    s2l, l2s = scr2local.make(lon, lat, Z)
    parts = []
    for fn in files:
        D = json.load(open(fn))
        for k, ft in enumerate(D["features"]):
            t = ft["type"]
            if t in ("alley", "footpath", "fence"):
                pts = [l2s(*p) for p in ft["line"]]
                w = 2 if t == "fence" else max(1.5, ft.get("width", 1) / (0.44 if Z == 18 else 0.22) * 0.5)
                parts.append(f'<path d="M{" L".join(f"{a:.0f} {b:.0f}" for a, b in pts)}" fill="none" stroke="{COL[t]}" stroke-width="{w:.1f}" stroke-opacity="0.8"/>')
            elif t in ("area", "building_missing"):
                pts = [l2s(*p) for p in ft["poly"]]
                col = ACOL.get(ft.get("surface"), "#fff") if t == "area" else "#ffffff"
                dash = ' stroke-dasharray="4,3"' if t == "building_missing" else ""
                parts.append(f'<path d="M{" L".join(f"{a:.0f} {b:.0f}" for a, b in pts)}Z" fill="{col}" fill-opacity="0.18" stroke="{col}" stroke-width="1.5"{dash}/>')
                if t == "area":
                    cx = sum(p[0] for p in pts) / len(pts); cy = sum(p[1] for p in pts) / len(pts)
                    parts.append(f'<text x="{cx:.0f}" y="{cy:.0f}" font-size="10" fill="{col}" stroke="#000" stroke-width="0.3">{k}</text>')
            elif t == "building_gone":
                a, b = l2s(*ft["at"])
                parts.append(f'<circle cx="{a:.0f}" cy="{b:.0f}" r="6" fill="none" stroke="#ff8800" stroke-width="2"/>')
    svg = '<svg width=800 height=700 style="position:fixed;left:0;top:0;z-index:99997;pointer-events:none">' + "".join(parts) + "</svg>"
    return ("(()=>{let g=document.getElementById('wfeat');if(g)g.remove();g=document.createElement('div');g.id='wfeat';g.innerHTML="
            + json.dumps(svg) + ";document.body.appendChild(g);window.__f=(v)=>{g.style.display=v?'block':'none'};return 'feat ok'})()")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "nav":
        nav(float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]))
    elif cmd == "grid":
        print(grid(float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])))
    elif cmd == "feat":
        print(feat(float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5:]))
    elif cmd == "model":
        lon, lat, Z = sys.argv[2], sys.argv[3], sys.argv[4]
        s2l, l2s = scr2local.make(float(lon), float(lat), int(Z)); c = s2l(400, 350)
        env = dict(os.environ, FOCUS=f"{c[0]},{c[1]},300")
        subprocess.run([sys.executable, os.path.join(HERE, "ovl.py"), lon, lat, Z, sys.argv[5]], env=env, check=True)
        import re
        keep = os.environ.get("KEEP", "#ffffff,#ff00ff,#ff2020,#ff8800,#00ffff").split(",")
        js = open(sys.argv[5]).read()
        def filt(m):
            st = re.search(r'stroke=\\"(#[0-9a-f]{6})', m.group(0))
            return m.group(0) if (st and st.group(1) in keep) else ""
        js = re.sub(r'<path [^>]*?/>', filt, js)
        js = re.sub(r'<text [^<]*</text>', "", js)
        open(sys.argv[5], "w").write(js); print(len(js))


def lonlat(x, y):
    kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0
    lon = geo.LON0 + x / kx; lat = geo.LAT0 + y / ky
    for _ in range(6):
        ex, ey = geo.to_local(lon, lat); lon += (x - ex) / kx; lat += (y - ey) / ky
    return lon, lat


if __name__ == "__main__" and sys.argv[1] == "wb":
    lon, lat = lonlat(float(sys.argv[2]), float(sys.argv[3]))
    print(f"https://livingatlas.arcgis.com/wayback/#mapCenter={lon:.5f}%2C{lat:.5f}%2C{sys.argv[4]}&mode=explore&active=9812")
