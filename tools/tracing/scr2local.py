import sys, math
sys.path.insert(0, 'scripts'); import geo, ymerc
Z = 19; AX, AY = 610, 350
def make(ll_lon, ll_lat, z=None):
    Zv = Z if z is None else z
    cx, cy = ymerc.to_px(ll_lon, ll_lat, Zv)
    kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0
    def s2l(sx, sy):
        lon, lat = ymerc.from_px(cx + sx - AX, cy + sy - AY, Zv)
        x, y = geo.to_local(lon, lat); return float(x), float(y)
    def l2s(x, y):
        lon = geo.LON0 + x / kx; lat = geo.LAT0 + y / ky
        for _ in range(6):
            ex, ey = geo.to_local(lon, lat); lon += (x - ex) / kx; lat += (y - ey) / ky
        px, py = ymerc.to_px(lon, lat, Zv); return px - cx + AX, py - cy + AY
    return s2l, l2s
if __name__ == "__main__":
    s2l, l2s = make(float(sys.argv[1]), float(sys.argv[2]))
    print('site at screen', [round(v) for v in l2s(0, 0)], 'screen corners local', [tuple(round(v) for v in s2l(*p)) for p in ((0,0),(800,700))])
