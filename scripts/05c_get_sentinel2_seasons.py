"""Two-season Sentinel-2 L2A crops around the site (SHEF: compare January and September).
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
SCENES = {"20260914": "2026/9/S2B_43TDH_20260914_0_L2A",     # September, 0 % cloud
          "20260124": "2026/1/S2B_43TDH_20260124_0_L2A",     # January, snow 82 %
          "20260102": "2026/1/S2C_43TDH_20260102_0_L2A"}     # January, 7 % cloud
BANDS = ["B03", "B04", "B08", "B11", "TCI"]
HALF = 1100.0
UA = {"User-Agent": "LanessaStudio-Bishkek35km/1.0"}
LOG = open(os.path.join(ROOT, "logs", "05c_seasons.log"), "w")


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


def crop(url):
    fh = HttpFile(url)
    with tifffile.TiffFile(fh) as tf:
        pg = tf.pages[0]
        tp = pg.tags["ModelTiepointTag"].value; px = pg.tags["ModelPixelScaleTag"].value[0]
        E_ul, N_ul = tp[3], tp[4]
        c0 = int((geo.E0 - HALF - E_ul) / px); c1 = int((geo.E0 + HALF - E_ul) / px) + 1
        r0 = int((N_ul - (geo.N0 + HALF)) / px); r1 = int((N_ul - (geo.N0 - HALF)) / px) + 1
        tw, th = pg.tilewidth, pg.tilelength
        ntx = (pg.imagewidth + tw - 1) // tw
        spp = pg.samplesperpixel
        out = np.zeros((r1 - r0, c1 - c0) + ((spp,) if spp > 1 else ()), dtype=pg.dtype)
        for ty in range(r0 // th, (r1 - 1) // th + 1):
            for tx in range(c0 // tw, (c1 - 1) // tw + 1):
                idx = ty * ntx + tx
                fh.seek(pg.dataoffsets[idx]); data = fh.read(pg.databytecounts[idx])
                tile, _, _ = pg.decode(data, idx)
                tile = np.asarray(tile).reshape((th, tw) + ((spp,) if spp > 1 else ()))
                ys, xs = ty * th, tx * tw
                a0, a1 = max(r0, ys), min(r1, ys + th); b0, b1 = max(c0, xs), min(c1, xs + tw)
                out[a0 - r0:a1 - r0, b0 - c0:b1 - c0] = tile[a0 - ys:a1 - ys, b0 - xs:b1 - xs]
        return out, np.array([E_ul + c0 * px, N_ul - r0 * px, px])


def main():
    o = {}
    for d, path in SCENES.items():
        for b in BANDS:
            t0 = time.time()
            try:
                a, g = crop(BASE + path + "/" + b + ".tif")
            except Exception as e:
                log("FAILED", d, b, repr(e)); continue
            o[f"{d}_{b}"] = a; o[f"{d}_{b}_geo"] = g
            log(d, b, a.shape, a.dtype, round(time.time() - t0, 1), "s")
        if f"{d}_TCI" in o:
            try:
                from PIL import Image
                Image.fromarray(o[f"{d}_TCI"][..., :3]).resize((880, 880), Image.NEAREST).save(os.path.join(ROOT, "data", f"s2_seasons_{d}_TCI.png"))
            except Exception as e:
                log("preview failed", e)
    np.savez_compressed(os.path.join(ROOT, "data", "s2_zone_seasons.npz"), **o)
    log("SEASONS DONE", len(o))


if __name__ == "__main__":
    main()
