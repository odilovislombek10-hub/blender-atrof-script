import os, urllib.request, shutil, time, json
OUT = r"D:\Bishkek_35km\data\s2"; os.makedirs(OUT, exist_ok=True)
base = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/43/T/DH/2026/7/S2B_43TDH_20260716_0_L2A/"
for f in ["B04.tif", "B08.tif", "SCL.tif", "TCI.tif", "B03.tif", "B11.tif"]:
    dst = os.path.join(OUT, "20260716_" + f)
    t0 = time.time()
    req = urllib.request.Request(base + f, headers={"User-Agent": "LanessaStudio-Bishkek35km/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r, open(dst, "wb") as fo:
        shutil.copyfileobj(r, fo, 1 << 20)
    print(f, round(os.path.getsize(dst) / 1e6, 1), "MB", round(time.time() - t0, 1), "s", flush=True)
print("S2 DONE", flush=True)
