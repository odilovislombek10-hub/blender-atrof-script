"""Plan one z18 Yandex view: navigate URL (panel opens) -> collapse panel -> map centre = target at screen (400,350).
usage: python pgview.py X Y [R] [Z]  -> prints nav ll, post-collapse ll, writes /tmp/ov_cur.js (overlay limited to FOCUS)"""
import sys, os, math, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo, ymerc
x, y = float(sys.argv[1]), float(sys.argv[2]); R = float(sys.argv[3]) if len(sys.argv) > 3 else 90; Z = int(sys.argv[4]) if len(sys.argv) > 4 else 18
kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0
lon = geo.LON0 + x / kx; lat = geo.LAT0 + y / ky
for _ in range(6):
    ex, ey = geo.to_local(lon, lat); lon += (x - ex) / kx; lat += (y - ey) / ky
px, py = ymerc.to_px(lon, lat, Z)
lon2, lat2 = ymerc.from_px(px + 210, py, Z)
print(f"NAV https://yandex.uz/maps/10309/bishkek/sputnik/?ll={lon:.6f}%2C{lat:.6f}&z={Z}")
print(f"AFTER {lon2:.6f},{lat2:.6f}")
env = dict(os.environ, FOCUS=os.environ.get("FOCUS", f"{x},{y},{R}"))
subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ovl.py"), f"{lon2:.6f}", f"{lat2:.6f}", str(Z), "/tmp/ov_cur.js"], env=env, check=True)
