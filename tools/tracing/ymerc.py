import math
E = 0.0818191908426
def to_px(lon, lat, z):
    s = 256 * 2 ** z
    x = (lon + 180) / 360 * s
    phi = math.radians(lat); es = E * math.sin(phi)
    y = (1 - math.log(math.tan(math.pi / 4 + phi / 2) * ((1 - es) / (1 + es)) ** (E / 2)) / math.pi) / 2 * s
    return x, y
def from_px(x, y, z):
    s = 256 * 2 ** z
    lon = x / s * 360 - 180
    t = math.exp(-(2 * y / s - 1) * -math.pi) if False else math.exp((1 - 2 * y / s) * math.pi)
    phi = math.pi / 2 - 2 * math.atan(1 / t)
    for _ in range(8):
        es = E * math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan((1 / t) * ((1 - es) / (1 + es)) ** (E / 2))
    return lon, math.degrees(phi)
