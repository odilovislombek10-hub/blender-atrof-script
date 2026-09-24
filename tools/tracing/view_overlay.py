"""Make a JS snippet that overlays the model's ground classes on the Yandex satellite view.
Usage: python3 view_overlay.py <ll_lon> <ll_lat>  -> /tmp/ov.js ; anchor of ll = screen (610,350), z19, viewport 800x700"""
import sys, json, math, numpy as np
sys.path.insert(0, 'scripts'); import geo, ymerc
from shapely.geometry import Polygon
from shapely.ops import unary_union
lon0, lat0 = float(sys.argv[1]), float(sys.argv[2])
Z = 19; AX, AY = 610, 350
cx, cy = ymerc.to_px(lon0, lat0, Z)
kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0
def local_to_ll(x, y):
    lon = geo.LON0 + x / kx; lat = geo.LAT0 + y / ky
    for _ in range(6):
        ex, ey = geo.to_local(lon, lat); lon += (x - ex) / kx; lat += (y - ey) / ky
    return lon, lat
def local_to_scr(x, y):
    lon, lat = local_to_ll(x, y); px, py = ymerc.to_px(lon, lat, Z); return px - cx + AX, py - cy + AY
# view window in local coords
corners = []
for sx, sy in ((0, 0), (800, 0), (0, 700), (800, 700)):
    lon, lat = ymerc.from_px(cx + sx - AX, cy + sy - AY, Z); corners.append(geo.to_local(lon, lat))
xs = [float(c[0]) for c in corners]; ys = [float(c[1]) for c in corners]
bx = (min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5)
z = np.load('data/zone_partition.npz'); V = z['V']; T = z['T']; C = z['TC']
names = {c[0]: c[1] for c in json.loads(str(z['classes']))}
cen = V[T].mean(1)
m = (cen[:, 0] > bx[0]) & (cen[:, 0] < bx[2]) & (cen[:, 1] > bx[1]) & (cen[:, 1] < bx[3])
col = {"Parking_Asphalt": "#ffd400", "Parking_Lane": "#ffd400", "Entrance_Paving": "#ff66ff", "Path_Paving": "#00e5ff",
       "Sidewalk_Paving": "#00e5ff", "Playground": "#ff3b3b", "Lawn": "#39ff14", "Street_Green": "#39ff14",
       "Asphalt_Road": "#ffffff", "Forecourt_Paving": "#ff9900", "Apron_Concrete": "#bbbbbb", "Yard_Hard": "#8888ff",
       "Private_Plot": "#aa7744", "Trees_Ground": "#1b8a1b", "Aryk": "#0066ff", "Channel_Bank": "#0066ff", "Water_Channel": "#0066ff"}
paths = []
for cid in np.unique(C[m]):
    nm = names[int(cid)]
    if nm not in col:
        continue
    tris = [Polygon(V[t][:, :2]) for t in T[m & (C == cid)]]
    u = unary_union([t.buffer(0.01) for t in tris])
    for g in getattr(u, 'geoms', [u]):
        for ring in [g.exterior] + list(g.interiors):
            pts = [local_to_scr(x, y) for x, y in list(ring.coords)[::1]]
            d = 'M' + ' L'.join(f'{a:.1f},{b:.1f}' for a, b in pts) + ' Z'
            paths.append(f'<path d="{d}" fill="none" stroke="{col[nm]}" stroke-width="1.3" opacity="0.9"/>')
sx, sy = local_to_scr(0, 0)
svg = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="700" style="position:fixed;left:0;top:0;z-index:99999;pointer-events:none">' + ''.join(paths) + f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4" fill="red"/></svg>'
js = "(()=>{let d=document.getElementById('osmov'); if(d) d.remove(); d=document.createElement('div'); d.id='osmov'; d.innerHTML=%s; document.body.appendChild(d); return 'ok'})()" % json.dumps(svg)
open('/tmp/ov.js', 'w').write(js)
print('view local bbox', [round(v) for v in bx], 'js chars', len(js))
