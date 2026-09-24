"""Stage 05d - Sentinel-2 L2A stack for the whole-city run (summer, leaf-off spring, September, January snow).
Reads only the needed COG tiles with HTTP range requests (no full-scene download).
Output: data/s2_zone_seasons.npz with <date>_<band> arrays (+ _geo = [E_ul, N_ul, px]) for a +-HALF m box,
and data/s2_seasons_<date>_TCI.png previews.
"""
import os, sys, io, json, time, urllib.request
import numpy as np
ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
sys.path.append(os.path.join(ROOT, "pylibs")); sys.path.append(os.path.join(ROOT, "scripts"))
import tifffile, geo

BASE = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/43/T/DH/"
# city-wide stack for the 1 km city tiles: every band resampled to one 10 m grid (B11 20 m -> 10 m)
SCENES = {"20260716": ("2026/7/S2B_43TDH_20260716_0_L2A", ["B04", "B08"]),      # summer: canopy
          "20260328": ("2026/3/S2B_43TDH_20260328_0_L2A", ["B04", "B08"]),      # leaf-off spring: ground vegetation
          "20260914": ("2026/9/S2B_43TDH_20260914_0_L2A", ["B04", "B08"]),      # September: green or not
          "20260124": ("2026/1/S2B_43TDH_20260124_0_L2A", ["B03", "B11"])}      # January snow
X0, X1, Y0, Y1 = -14000.0, 17000.0, -10000.0, 10000.0     # local metres (city tiles + margin)
UA = {"User-Agent": "LanessaStudio-Bishkek35km/1.0"}
LOG = open(os.path.join(ROOT, "logs", "05d_city_s2.log"), "w")


def log(*a):
    print(*a, file=LOG, flush=True); print(*a, flush=True)


class HttpFile(io.RawIOBase):
    """seekable read-only file over HTTP range requests, with a small block cache"""
    def __init__(self, url, block=1 << 16):
        self.url = url; self.pos = 0; self.block = block; self.cache = {}
        req = urllib.request.Request(url, method="HEAD", headers=UA)
        self.size = int(urllib.request.urlopen(req, timeout=60).headers["Content-Length"])

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def _get(self, a, b):
        req = urllib.request.Request(self.url, headers=dict(UA, Range=f"bytes={a}-{b - 1}"))
        for k in range(4):
            try:
                return urllib.request.urlopen(req, timeout=120).read()
            except Exception as e:
                if k == 3:
                    raise
                time.sleep(2 + 3 * k)

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        end = min(self.pos + n, self.size)
        if end <= self.pos:
            return b""
        b0 = self.pos // self.block; b1 = (end - 1) // self.block
        if b1 - b0 > 8:   # large read: fetch directly
            data = self._get(self.pos, end)
        else:
            parts = []
            for b in range(b0, b1 + 1):
                if b not in self.cache:
                    self.cache[b] = self._get(b * self.block, min((b + 1) * self.block, self.size))
                parts.append(self.cache[b])
            buf = b"".join(parts); s = self.pos - b0 * self.block
            data = buf[s:s + (end - self.pos)]
        self.pos = end
        return data

    def readinto(self, b):
        d = self.read(len(b)); b[:len(d)] = d; return len(d)


def _range(url, a, b):
    req = urllib.request.Request(url, headers=dict(UA, Range=f"bytes={a}-{b - 1}"))
    for k in range(5):
        try:
            return urllib.request.urlopen(req, timeout=120).read()
        except Exception:
            if k == 4:
                raise
            time.sleep(2 + 3 * k)


def crop(url):
    """header via HttpFile, then every needed COG tile fetched with its own range request, 12 in parallel"""
    from concurrent.futures import ThreadPoolExecutor
    fh = HttpFile(url)
    with tifffile.TiffFile(fh) as tf:
        pg = tf.pages[0]
        tp = pg.tags["ModelTiepointTag"].value; px = pg.tags["ModelPixelScaleTag"].value[0]
        E_ul, N_ul = tp[3], tp[4]
        c0 = int((geo.E0 + X0 * geo.KS - E_ul) / px); c1 = int((geo.E0 + X1 * geo.KS - E_ul) / px) + 1
        r0 = int((N_ul - (geo.N0 + Y1 * geo.KS)) / px); r1 = int((N_ul - (geo.N0 + Y0 * geo.KS)) / px) + 1
        c0 = max(c0, 0); r0 = max(r0, 0); c1 = min(c1, pg.imagewidth); r1 = min(r1, pg.imagelength)
        tw, th = pg.tilewidth, pg.tilelength
        ntx = (pg.imagewidth + tw - 1) // tw
        spp = pg.samplesperpixel
        out = np.zeros((r1 - r0, c1 - c0) + ((spp,) if spp > 1 else ()), dtype=pg.dtype)
        jobs = [(ty, tx) for ty in range(r0 // th, (r1 - 1) // th + 1) for tx in range(c0 // tw, (c1 - 1) // tw + 1)]
        offs = list(pg.dataoffsets); cnts = list(pg.databytecounts)

        def fetch(j):
            ty, tx = j; idx = ty * ntx + tx
            return j, idx, _range(url, offs[idx], offs[idx] + cnts[idx])
        with ThreadPoolExecutor(12) as ex:
            for (ty, tx), idx, data in ex.map(fetch, jobs):
                tile, _, _ = pg.decode(data, idx)
                tile = np.asarray(tile).reshape((th, tw) + ((spp,) if spp > 1 else ()))
                ys, xs = ty * th, tx * tw
                a0, a1 = max(r0, ys), min(r1, ys + th); b0, b1 = max(c0, xs), min(c1, xs + tw)
                out[a0 - r0:a1 - r0, b0 - c0:b1 - c0] = tile[a0 - ys:a1 - ys, b0 - xs:b1 - xs]
        return out, np.array([E_ul + c0 * px, N_ul - r0 * px, px])


def main():
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(d, path, b) for d, (path, bands) in SCENES.items() for b in bands]
    t00 = time.time()

    def one(j):
        d, path, b = j; t0 = time.time()
        try:
            a, g = crop(BASE + path + "/" + b + ".tif")
        except Exception as e:
            log("FAILED", d, b, repr(e)); return j, None, None
        log(d, b, a.shape, round(time.time() - t0, 1), "s")
        return j, a, g
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, jobs))
    o = {}
    ref = None
    for (d, path, b), a, g in res:      # reference grid = first 10 m band
        if a is not None and g[2] < 15 and ref is None:
            ref = g
    for (d, path, b), a, g in res:
        if a is None:
            continue
        if g[2] > 15:   # 20 m band -> 10 m grid
            a = np.kron(a, np.ones((2, 2), a.dtype)); g = np.array([g[0], g[1], g[2] / 2])
        # align to the reference 10 m grid
        dc = int(round((ref[0] - g[0]) / 10.0)); dr = int(round((g[1] - ref[1]) / 10.0))
        if dc or dr:
            a = a[max(0, dr):, max(0, dc):]
        o[f"{d}_{b}"] = a
    h = min(v.shape[0] for v in o.values()); w = min(v.shape[1] for v in o.values())
    for k in list(o):
        o[k] = o[k][:h, :w]
    o["geo"] = ref
    np.savez_compressed(os.path.join(ROOT, "data", "s2_city.npz"), **o)
    log("CITY S2 DONE", round(time.time() - t00, 1), "s", {k: v.shape for k, v in o.items() if k != "geo"})


if __name__ == "__main__":
    main()
