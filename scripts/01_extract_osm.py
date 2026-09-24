
import sys, os, json, math, time
ROOT = r"D:\Bishkek_35km"
sys.path.append(os.path.join(ROOT, "pylibs"))
import osmium

LAT0, LON0 = 42.845424, 74.591755
R = 36000.0  # 35 km + 1 km margin
KX = 111320.0 * math.cos(math.radians(LAT0)); KY = 110574.0
def dist(lon, lat):
    return math.hypot((lon - LON0) * KX, (lat - LAT0) * KY)

BKEYS = ["building","building:levels","height","min_height","building:min_level","roof:shape","roof:levels","roof:height","name","addr:street","addr:housenumber","amenity","start_date","building:material","building:colour","roof:colour"]
HKEYS = ["highway","name","lanes","lanes:forward","lanes:backward","width","oneway","surface","sidewalk","sidewalk:left","sidewalk:right","sidewalk:both","footway","bridge","tunnel","layer","lit","cycleway","service","junction","maxspeed","ref","area","crossing","smoothness","parking:lane:both","parking:both"]
AREA_KEYS = {"landuse","leisure","natural","water","waterway","amenity","place","man_made","aeroway"}
LINE_KEYS = {"railway","waterway","barrier","natural","power","aerialway"}
NODE_TAGS = {("natural","tree"),("highway","street_lamp"),("highway","traffic_signals"),("highway","crossing"),("highway","bus_stop"),("public_transport","platform"),("amenity","bench"),("natural","peak")}

def pick(tags, keys):
    return {k: tags[k] for k in keys if k in tags}

def ring(r):
    pts = [(round(n.lon, 7), round(n.lat, 7)) for n in r if n.location.valid()]
    return pts

out = {"buildings": [], "building_parts": [], "highways": [], "highway_areas": [], "lines": [], "areas": [], "nodes": []}
t0 = time.time(); n_obj = 0
fp = osmium.FileProcessor(os.path.join(ROOT, "data", "osm", "kyrgyzstan-latest.osm.pbf")).with_locations().with_areas().with_filter(osmium.filter.EmptyTagFilter())
for o in fp:
    n_obj += 1
    if n_obj % 500000 == 0:
        print("objects", n_obj, round(time.time() - t0, 1), "s", flush=True)
    tags = {t.k: t.v for t in o.tags}
    if o.is_node():
        kv = None
        for k, v in NODE_TAGS:
            if tags.get(k) == v:
                kv = (k, v); break
        if kv is None: continue
        if dist(o.lon, o.lat) > R: continue
        out["nodes"].append({"t": kv[0] + "=" + kv[1], "p": [round(o.lon, 7), round(o.lat, 7)], "tags": pick(tags, ["height","ele","name","species","leaf_type","crossing","shelter"])})
    elif o.is_area():
        outers = []
        for orr in o.outer_rings():
            pts = ring(orr)
            if len(pts) < 3: continue
            inners = [ring(ir) for ir in o.inner_rings(orr)]
            inners = [p for p in inners if len(p) >= 3]
            outers.append({"outer": pts, "inner": inners})
        if not outers: continue
        p0 = outers[0]["outer"][0]
        if dist(p0[0], p0[1]) > R: continue
        oid = ("w" if o.from_way() else "r") + str(o.orig_id())
        if "building" in tags and tags["building"] != "no":
            out["buildings"].append({"id": oid, "tags": pick(tags, BKEYS), "polys": outers})
        elif "building:part" in tags:
            out["building_parts"].append({"id": oid, "tags": pick(tags, BKEYS + ["building:part"]), "polys": outers})
        elif "highway" in tags or "area:highway" in tags:
            if tags.get("area") == "yes" or "area:highway" in tags:
                out["highway_areas"].append({"id": oid, "tags": pick(tags, HKEYS + ["area:highway"]), "polys": outers})
        elif AREA_KEYS & set(tags):
            keep = {k: tags[k] for k in (list(AREA_KEYS) + ["name","sport","surface","landcover","wetland","parking","natural","water"]) if k in tags}
            out["areas"].append({"id": oid, "tags": keep, "polys": outers})
    elif o.is_way():
        if "highway" in tags:
            if tags.get("area") == "yes": continue
            pts = ring(o.nodes)
            if len(pts) < 2: continue
            if min(dist(pts[0][0], pts[0][1]), dist(pts[-1][0], pts[-1][1])) > R: continue
            out["highways"].append({"id": "w" + str(o.id), "tags": pick(tags, HKEYS), "pts": pts})
        elif LINE_KEYS & set(tags):
            pts = ring(o.nodes)
            if len(pts) < 2: continue
            if min(dist(pts[0][0], pts[0][1]), dist(pts[-1][0], pts[-1][1])) > R: continue
            keep = {k: tags[k] for k in (list(LINE_KEYS) + ["name","width","usage","service","gauge","electrified","tunnel","bridge","layer","height","material","intermittent"]) if k in tags}
            out["lines"].append({"id": "w" + str(o.id), "tags": keep, "pts": pts})

print("parse done", round(time.time() - t0, 1), "s", {k: len(v) for k, v in out.items()}, flush=True)
os.makedirs(os.path.join(ROOT, "data", "osm", "extract"), exist_ok=True)
for k, v in out.items():
    with open(os.path.join(ROOT, "data", "osm", "extract", k + ".json"), "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, separators=(",", ":"))
print("DONE", round(time.time() - t0, 1), "s", flush=True)
