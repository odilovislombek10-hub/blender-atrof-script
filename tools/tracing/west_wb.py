"""Wayback (web mercator, ArcGIS view) helpers.
  west_wb.py grid XMIN YMAX RES OX OY STEP   -> JS grid in local metres
  west_wb.py feat XMIN YMAX RES OX OY FILE.. -> JS features overlay
  west_wb.py s2l XMIN YMAX RES OX OY sx,sy ... -> local coords
  west_wb.py goto X Y Z                      -> JS goTo local point, returns extent info
"""
import sys, os, math, json
HERE = os.path.dirname(os.path.abspath(__file__)); DEV = os.path.dirname(HERE)
sys.path.insert(0, HERE); os.chdir(DEV)
import geo, west
R = 6378137.0


def make(xmin, ymax, res, ox, oy):
    def s2l(sx, sy):
        mx = xmin + (sx - ox) * res; my = ymax - (sy - oy) * res
        lon = math.degrees(mx / R); lat = math.degrees(2 * math.atan(math.exp(my / R)) - math.pi / 2)
        x, y = geo.to_local(lon, lat); return float(x), float(y)
    def l2s(x, y):
        lon, lat = west.lonlat(x, y)
        mx = R * math.radians(lon); my = R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        return (mx - xmin) / res + ox, (ymax - my) / res + oy
    return s2l, l2s


def affine(s2l, l2s, cx, cy):
    x0, y0 = s2l(cx, cy)
    p0 = l2s(x0, y0); px = l2s(x0 + 100, y0); py = l2s(x0, y0 + 100)
    a = (px[0] - p0[0]) / 100; d = (px[1] - p0[1]) / 100
    b = (py[0] - p0[0]) / 100; e = (py[1] - p0[1]) / 100
    return (a, b, p0[0] - a * x0 - b * y0, d, e, p0[1] - d * x0 - e * y0)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "goto":
        lon, lat = west.lonlat(float(sys.argv[2]), float(sys.argv[3]))
        print("(async()=>{let v=document.querySelector('arcgis-map').view;await v.goTo({center:[%.7f,%.7f],zoom:%s},{animate:false});await new Promise(r=>setTimeout(r,300));let r=v.container.getBoundingClientRect();return [v.extent.xmin,v.extent.ymax,v.resolution,r.x,r.y,v.width,v.height].join(' ')})()" % (lon, lat, sys.argv[4]))
        sys.exit()
    xmin, ymax, res, ox, oy = map(float, sys.argv[2:7])
    s2l, l2s = make(xmin, ymax, res, ox, oy)
    if cmd == "s2l":
        for p in sys.argv[7:]:
            sx, sy = map(float, p.split(",")); print(p, [round(v, 2) for v in s2l(sx, sy)])
    elif cmd == "grid":
        step = int(sys.argv[7])
        a, b, c, d, e, f = affine(s2l, l2s, ox + 225, oy + 350)
        xs = [s2l(ox, oy)[0], s2l(ox + 450, oy + 700)[0]]; ys = [s2l(ox, oy)[1], s2l(ox + 450, oy + 700)[1]]
        x0 = math.floor(min(xs) / step) * step; x1 = math.ceil(max(xs) / step) * step
        y0 = math.floor(min(ys) / step) * step; y1 = math.ceil(max(ys) / step) * step
        lab = step
        js = ("(()=>{let A=[%.5f,%.5f,%.3f,%.5f,%.5f,%.3f],P=(x,y)=>[A[0]*x+A[1]*y+A[2],A[3]*x+A[4]*y+A[5]];"
              "let s='';for(let x=%d;x<=%d;x+=%d){let p=P(x,%d),q=P(x,%d);s+=`<line x1=${p[0]} y1=${p[1]} x2=${q[0]} y2=${q[1]} stroke='rgba(255,255,0,0.5)' stroke-width='0.7'/>`}"
              "for(let y=%d;y<=%d;y+=%d){let p=P(%d,y),q=P(%d,y);s+=`<line x1=${p[0]} y1=${p[1]} x2=${q[0]} y2=${q[1]} stroke='rgba(255,255,0,0.5)' stroke-width='0.7'/>`}"
              "for(let x=%d;x<=%d;x+=%d)for(let y=%d;y<=%d;y+=%d){let p=P(x,y);s+=`<text x=${p[0]+2} y=${p[1]-2} font-size='9' fill='#ff0' stroke='#000' stroke-width='0.3'>${x},${y}</text>`}"
              "let g=document.getElementById('wgrid');if(g)g.remove();g=document.createElement('div');g.id='wgrid';"
              "g.innerHTML=`<svg width=800 height=700 style='position:fixed;left:0;top:0;z-index:99998;pointer-events:none'>${s}</svg>`;document.body.appendChild(g);"
              "window.__g=(v)=>{g.style.display=v?'block':'none'};return 'grid ok'})()") % (
            a, b, c, d, e, f, x0, x1, step, y0, y1, y0, y1, step, x0, x1, x0, x1, lab, y0, y1, lab)
        print(js)
    elif cmd == "feat":
        import scr2local
        orig = scr2local.make
        scr2local.make = lambda *a, **k: (s2l, l2s)
        print(west.feat(0, 0, 19, sys.argv[7:]))
