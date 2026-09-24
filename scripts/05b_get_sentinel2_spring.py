import os, sys, urllib.request, shutil, time, numpy as np
sys.path.append(r"D:\Bishkek_35km\pylibs"); sys.path.append(r"D:\Bishkek_35km\scripts")
import tifffile, geo
OUT = r"D:\Bishkek_35km\data\s2"
scenes = {"20260328": "2026/3/S2B_43TDH_20260328_0_L2A", "20260412": "2026/4/S2C_43TDH_20260412_0_L2A"}
base = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/43/T/DH/"
res = {}
for d, path in scenes.items():
    for f in ["B04.tif", "B08.tif", "TCI.tif"]:
        dst = os.path.join(OUT, d + "_" + f)
        if not os.path.exists(dst):
            req = urllib.request.Request(base + path + "/" + f, headers={"User-Agent": "LanessaStudio-Bishkek35km/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r, open(dst, "wb") as fo:
                shutil.copyfileobj(r, fo, 1 << 20)
        print(d, f, round(os.path.getsize(dst) / 1e6, 1), flush=True)
half = 2500
o = {}
for d in scenes:
    for band in ["B04", "B08", "TCI"]:
        pg = tifffile.TiffFile(os.path.join(OUT, d + "_" + band + ".tif")).pages[0]
        tp = pg.tags["ModelTiepointTag"].value; px = pg.tags["ModelPixelScaleTag"].value[0]
        E_ul, N_ul = tp[3], tp[4]
        c0 = int((geo.E0 - half - E_ul) / px); c1 = int((geo.E0 + half - E_ul) / px) + 1
        r0 = int((N_ul - (geo.N0 + half)) / px); r1 = int((N_ul - (geo.N0 - half)) / px) + 1
        a = pg.asarray()
        o[d + "_" + band] = a[r0:r1, c0:c1]; o[d + "_" + band + "_geo"] = np.array([E_ul + c0 * px, N_ul - r0 * px, px])
np.savez_compressed(r"D:\Bishkek_35km\data\s2_zone_spring.npz", **o)
print("SPRING DONE", flush=True)
