"""Geo helpers for the Bishkek 35 km model (pure numpy, no GDAL/pyproj).

Coordinate system: UTM zone 43N (EPSG:32643, WGS84), shifted so the site is at
(0, 0) and divided by the UTM point scale factor at the site, so distances near
the site are true metres. Z = metres above sea level (EGM2008, from Copernicus DEM).
"""
import math
import numpy as np

LAT0, LON0 = 42.845424, 74.591755      # site (Toktonalieva 77, Bishkek)
RADIUS = 35000.0

_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0 = 0.9996
_LONC = math.radians(75.0)             # UTM zone 43 central meridian


def utm43(lon, lat):
    """Forward UTM 43N (Snyder series). Returns E, N, point scale k."""
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    phi = np.radians(lat)
    lam = np.radians(lon)
    s, c = np.sin(phi), np.cos(phi)
    N = _A / np.sqrt(1 - _E2 * s * s)
    T = np.tan(phi) ** 2
    C = _EP2 * c * c
    A = (lam - _LONC) * c
    e2, e4, e6 = _E2, _E2 ** 2, _E2 ** 3
    M = _A * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
              - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * np.sin(2 * phi)
              + (15 * e4 / 256 + 45 * e6 / 1024) * np.sin(4 * phi)
              - (35 * e6 / 3072) * np.sin(6 * phi))
    E = _K0 * N * (A + (1 - T + C) * A ** 3 / 6
                   + (5 - 18 * T + T * T + 72 * C - 58 * _EP2) * A ** 5 / 120) + 500000.0
    Nn = _K0 * (M + N * np.tan(phi) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
                                       + (61 - 58 * T + T * T + 600 * C - 330 * _EP2) * A ** 6 / 720))
    k = _K0 * (1 + (1 + C) * A * A / 2 + (5 - 4 * T + 42 * C + 13 * C * C - 28 * _EP2) * A ** 4 / 24
               + (61 - 148 * T + 16 * T * T) * A ** 6 / 720)
    return E, Nn, k


E0, N0, KS = (float(v) for v in utm43(LON0, LAT0))


def to_local(lon, lat):
    """lon/lat (deg) -> local metres (x east, y north), site at origin."""
    E, N, _ = utm43(lon, lat)
    return (E - E0) / KS, (N - N0) / KS


class DEM:
    """Bilinear sampler over a lat/lon grid (row 0 = north)."""

    def __init__(self, arr, lon_min, lat_max, dlon, dlat):
        self.a = arr.astype(np.float32)
        self.lon_min, self.lat_max, self.dlon, self.dlat = lon_min, lat_max, dlon, dlat
        self.h, self.w = arr.shape

    def sample(self, lon, lat):
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        # pixel-centre convention: centre of pixel (r,c) at lon_min+(c+0.5)dlon, lat_max-(r+0.5)dlat
        fx = (lon - self.lon_min) / self.dlon - 0.5
        fy = (self.lat_max - lat) / self.dlat - 0.5
        x0 = np.clip(np.floor(fx).astype(np.int64), 0, self.w - 2)
        y0 = np.clip(np.floor(fy).astype(np.int64), 0, self.h - 2)
        tx = np.clip(fx - x0, 0, 1)
        ty = np.clip(fy - y0, 0, 1)
        a = self.a
        z00 = a[y0, x0]; z01 = a[y0, x0 + 1]; z10 = a[y0 + 1, x0]; z11 = a[y0 + 1, x0 + 1]
        return (z00 * (1 - tx) * (1 - ty) + z01 * tx * (1 - ty) + z10 * (1 - tx) * ty + z11 * tx * ty)


def _shift_stack(a, r, fn):
    """Separable min/max filter with window (2r+1) using edge padding."""
    out = a
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="edge")
        acc = None
        n = out.shape[axis]
        for i in range(2 * r + 1):
            sl = [slice(None), slice(None)]
            sl[axis] = slice(i, i + n)
            v = p[tuple(sl)]
            acc = v if acc is None else fn(acc, v)
        out = acc
    return out


def box_blur(a, r):
    out = a.astype(np.float64)
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r + 1, r)
        p = np.pad(out, pad, mode="edge")
        cs = np.cumsum(p, axis=axis)
        n = out.shape[axis]
        hi = [slice(None), slice(None)]; lo = [slice(None), slice(None)]
        hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
        lo[axis] = slice(0, n)
        out = (cs[tuple(hi)] - cs[tuple(lo)]) / (2 * r + 1)
    return out.astype(np.float32)


def dsm_to_dtm(dsm, r=3, slope_lo=0.06, slope_hi=0.15, px_m=27.0):
    """Approximate bare-earth DTM from the Copernicus DSM.

    Morphological opening (min then max, window 2r+1 px) removes buildings and
    tree canopies narrower than ~(2r+1)*30 m; a light blur follows. The opened
    surface is used on gentle terrain (city, valley); steep mountain terrain keeps
    the raw DSM so ridges are not shaved.
    """
    opened = _shift_stack(_shift_stack(dsm, r, np.minimum), r, np.maximum)
    opened = box_blur(opened, 2)
    gy, gx = np.gradient(box_blur(dsm, 2), px_m)
    slope = np.hypot(gx, gy)
    w = np.clip((slope - slope_lo) / (slope_hi - slope_lo), 0, 1).astype(np.float32)
    return opened * (1 - w) + dsm * w
