import sys, math
sys.path.insert(0, '.'); import geo, ymerc, scr2local
def ll_for(x, y, z):
    """URL ll such that local (x,y) is at the screen centre (400,350)."""
    kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0
    lon = geo.LON0 + x / kx; lat = geo.LAT0 + y / ky
    for _ in range(6):
        ex, ey = geo.to_local(lon, lat); lon += (x - ex) / kx; lat += (y - ey) / ky
    px, py = ymerc.to_px(lon, lat, z)
    # ll pixel is at (AX,AY); we want (x,y) at (400,350) -> ll pixel = p + (AX-400, AY-350)
    return ymerc.from_px(px + scr2local.AX - 400, py + scr2local.AY - 350, z)
if __name__ == "__main__":
    x, y, z = float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
    lon, lat = ll_for(x, y, z); print(f"{lon:.6f},{lat:.6f}")
