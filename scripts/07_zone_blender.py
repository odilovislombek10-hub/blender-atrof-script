"""Assemble the 1 km detail zone into Bishkek_35km.blend (run with blender -b).

- ground partition (data/zone_partition.npz) -> 250 m tile meshes, one material slot per surface class,
  world-metre UVs (tiling textures line up across tiles), crosswalk stripe direction attribute
- procedural archviz materials (asphalt, zebra, curb concrete, paving, aryk, grass, soil, ...)
- tree trunk points + Geometry Nodes instancer with placeholder trees (swap for real assets)
- terrain tiles get a clean circular hole under the zone (no double ground)
- v1 map ribbons / area overlays (z-fighting) moved to an excluded reference collection
"""
import os, sys, json, math
ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "pylibs")):
    if p not in sys.path:
        sys.path.append(p)
import numpy as np
import bpy, bmesh

TILE = 250.0
# city mode (whole-city run, 1x1 km tiles): BISHKEK_TILE=I,J -> own data dir, own .blend (city\tile_I_J.blend)
CITY = tuple(int(v) for v in os.environ["BISHKEK_TILE"].split(",")) if os.environ.get("BISHKEK_TILE") else None
DATADIR = os.path.join(ROOT, "data", "city", f"T_{CITY[0]}_{CITY[1]}") if CITY else os.path.join(ROOT, "data")
ROOTCOL = f"CITY_T_{CITY[0]}_{CITY[1]}" if CITY else "Z1_DetailZone_1km"
Z = np.load(os.path.join(DATADIR, "zone_partition.npz"))
CLASSES = json.loads(str(Z["classes"]))
CNAME = {c[0]: c[1] for c in CLASSES}
COFF = {c[0]: c[2] for c in CLASSES}
RZ = float(Z["rz"])


def log(*a):
    print("[zone]", *a, flush=True)


# ----------------------------------------------------------------------------- materials
def _nodes(m):
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (600, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (300, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    tc = nt.nodes.new("ShaderNodeTexCoord"); tc.location = (-1000, 0)
    uv = nt.nodes.new("ShaderNodeUVMap"); uv.location = (-1000, -200); uv.uv_map = "UVMap"
    return nt, bsdf, uv


def _ramp(nt, fac_socket, c1, c2, loc):
    r = nt.nodes.new("ShaderNodeValToRGB"); r.location = loc
    r.color_ramp.elements[0].color = (*c1, 1); r.color_ramp.elements[1].color = (*c2, 1)
    nt.links.new(fac_socket, r.inputs["Fac"])
    return r


def _noise(nt, vec, scale, detail=6.0, loc=(-600, 0)):
    n = nt.nodes.new("ShaderNodeTexNoise"); n.location = loc
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    nt.links.new(vec, n.inputs["Vector"])
    return n


def _bump(nt, height, strength, bsdf, loc=(0, -300)):
    b = nt.nodes.new("ShaderNodeBump"); b.location = loc
    b.inputs["Strength"].default_value = strength
    nt.links.new(height, b.inputs["Height"])
    nt.links.new(b.outputs["Normal"], bsdf.inputs["Normal"])
    return b


def mat_noise(name, c1, c2, scale, rough, bump=0.15, scale2=None):
    m = bpy.data.materials.get((name, None)) or bpy.data.materials.new(name)
    nt, bsdf, uv = _nodes(m)
    n = _noise(nt, uv.outputs["UV"], scale)
    r = _ramp(nt, n.outputs["Fac"], c1, c2, (-300, 100))
    nt.links.new(r.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = rough
    fine = _noise(nt, uv.outputs["UV"], scale2 or scale * 20, 4.0, (-600, -300))
    _bump(nt, fine.outputs["Fac"], bump, bsdf)
    m.diffuse_color = (*[(a + b) / 2 for a, b in zip(c1, c2)], 1)
    return m


def mat_brick(name, c1, c2, mortar, brick_w, row_h, rough, offset=0.5):
    m = bpy.data.materials.get((name, None)) or bpy.data.materials.new(name)
    nt, bsdf, uv = _nodes(m)
    br = nt.nodes.new("ShaderNodeTexBrick"); br.location = (-500, 100)
    br.offset = offset
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Brick Width"].default_value = brick_w
    br.inputs["Row Height"].default_value = row_h
    br.inputs["Mortar Size"].default_value = 0.004
    br.inputs["Color1"].default_value = (*c1, 1); br.inputs["Color2"].default_value = (*c2, 1)
    br.inputs["Mortar"].default_value = (*mortar, 1)
    nt.links.new(uv.outputs["UV"], br.inputs["Vector"])
    dirt = _noise(nt, uv.outputs["UV"], 0.6, 5.0, (-500, -150))
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.location = (-150, 50)
    mix.inputs[0].default_value = 0.35
    nt.links.new(br.outputs["Color"], mix.inputs[6])
    dr = _ramp(nt, dirt.outputs["Fac"], (0.75, 0.75, 0.75), (1, 1, 1), (-350, -150))
    nt.links.new(dr.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = rough
    _bump(nt, br.outputs["Fac"], 0.25, bsdf)
    m.diffuse_color = (*c1, 1)
    return m


def mat_crosswalk(name):
    m = bpy.data.materials.get((name, None)) or bpy.data.materials.new(name)
    nt, bsdf, uv = _nodes(m)
    geo_n = nt.nodes.new("ShaderNodeNewGeometry"); geo_n.location = (-1000, 300)
    at = nt.nodes.new("ShaderNodeAttribute"); at.location = (-1000, 500)
    at.attribute_type = "GEOMETRY"; at.attribute_name = "xw_angle"
    neg = nt.nodes.new("ShaderNodeMath"); neg.operation = "MULTIPLY"; neg.inputs[1].default_value = -1.0; neg.location = (-800, 500)
    nt.links.new(at.outputs["Fac"], neg.inputs[0])
    rot = nt.nodes.new("ShaderNodeVectorRotate"); rot.rotation_type = "Z_AXIS"; rot.location = (-600, 400)
    nt.links.new(geo_n.outputs["Position"], rot.inputs["Vector"])
    nt.links.new(neg.outputs[0], rot.inputs["Angle"])
    sep = nt.nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-400, 400)
    nt.links.new(rot.outputs["Vector"], sep.inputs[0])
    md = nt.nodes.new("ShaderNodeMath"); md.operation = "FLOORED_MODULO"; md.inputs[1].default_value = 1.0; md.location = (-250, 400)
    nt.links.new(sep.outputs["Y"], md.inputs[0])
    gt = nt.nodes.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; gt.inputs[1].default_value = 0.5; gt.location = (-100, 400)
    nt.links.new(md.outputs[0], gt.inputs[0])
    wear = _noise(nt, uv.outputs["UV"], 3.0, 8.0, (-400, 100))
    wr = nt.nodes.new("ShaderNodeMath"); wr.operation = "GREATER_THAN"; wr.inputs[1].default_value = 0.38; wr.location = (-200, 100)
    nt.links.new(wear.outputs["Fac"], wr.inputs[0])
    both = nt.nodes.new("ShaderNodeMath"); both.operation = "MULTIPLY"; both.location = (0, 300)
    nt.links.new(gt.outputs[0], both.inputs[0]); nt.links.new(wr.outputs[0], both.inputs[1])
    asph = _noise(nt, uv.outputs["UV"], 8.0, 6.0, (-400, -150))
    ar = _ramp(nt, asph.outputs["Fac"], (0.035, 0.035, 0.04), (0.09, 0.09, 0.095), (-200, -150))
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.location = (150, 150)
    nt.links.new(both.outputs[0], mix.inputs[0])
    nt.links.new(ar.outputs["Color"], mix.inputs[6])
    mix.inputs[7].default_value = (0.8, 0.8, 0.78, 1)
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.75
    m.diffuse_color = (0.3, 0.3, 0.3, 1)
    return m


def mat_parking(name, c1, c2, spacing=2.6, line=0.12):
    """Asphalt with painted bay separators perpendicular to the adjacent road (face attribute xw_angle)."""
    m = bpy.data.materials.get((name, None)) or bpy.data.materials.new(name)
    nt, bsdf, uv = _nodes(m)
    geo_n = nt.nodes.new("ShaderNodeNewGeometry"); geo_n.location = (-1000, 300)
    at = nt.nodes.new("ShaderNodeAttribute"); at.location = (-1000, 500)
    at.attribute_type = "GEOMETRY"; at.attribute_name = "xw_angle"
    neg = nt.nodes.new("ShaderNodeMath"); neg.operation = "MULTIPLY"; neg.inputs[1].default_value = -1.0; neg.location = (-800, 500)
    nt.links.new(at.outputs["Fac"], neg.inputs[0])
    rot = nt.nodes.new("ShaderNodeVectorRotate"); rot.rotation_type = "Z_AXIS"; rot.location = (-600, 400)
    nt.links.new(geo_n.outputs["Position"], rot.inputs["Vector"]); nt.links.new(neg.outputs[0], rot.inputs["Angle"])
    sep = nt.nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-400, 400)
    nt.links.new(rot.outputs["Vector"], sep.inputs[0])
    md = nt.nodes.new("ShaderNodeMath"); md.operation = "FLOORED_MODULO"; md.inputs[1].default_value = spacing; md.location = (-250, 400)
    nt.links.new(sep.outputs["X"], md.inputs[0])
    lt = nt.nodes.new("ShaderNodeMath"); lt.operation = "LESS_THAN"; lt.inputs[1].default_value = line; lt.location = (-100, 400)
    nt.links.new(md.outputs[0], lt.inputs[0])
    asph = _noise(nt, uv.outputs["UV"], 6.0, 6.0, (-400, -150))
    ar = _ramp(nt, asph.outputs["Fac"], c1, c2, (-200, -150))
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.location = (150, 150)
    nt.links.new(lt.outputs[0], mix.inputs[0]); nt.links.new(ar.outputs["Color"], mix.inputs[6])
    mix.inputs[7].default_value = (0.75, 0.75, 0.72, 1)
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.82
    m.diffuse_color = (*c2, 1)
    return m


def build_materials():
    M = {}
    M["Asphalt_Road"] = mat_noise("Z_Asphalt_Road", (0.030, 0.030, 0.034), (0.085, 0.085, 0.09), 6.0, 0.82, 0.25, 180)
    M["Crosswalk"] = mat_crosswalk("Z_Crosswalk_Zebra")
    M["Curb"] = mat_noise("Z_Curb_Concrete", (0.42, 0.41, 0.39), (0.62, 0.61, 0.58), 12.0, 0.8, 0.2)
    M["Sidewalk_Paving"] = mat_brick("Z_Sidewalk_Bruschatka", (0.36, 0.34, 0.32), (0.46, 0.44, 0.40), (0.18, 0.17, 0.16), 0.2, 0.1, 0.78)
    M["Path_Paving"] = mat_brick("Z_Path_Tiles_30cm", (0.50, 0.48, 0.45), (0.58, 0.56, 0.52), (0.25, 0.24, 0.23), 0.3, 0.3, 0.8, 0.0)
    M["Cycleway"] = mat_noise("Z_Cycleway_Asphalt_Red", (0.16, 0.05, 0.04), (0.25, 0.09, 0.07), 6.0, 0.8, 0.2, 150)
    M["Parking_Asphalt"] = mat_parking("Z_Parking_Asphalt_Bays", (0.05, 0.05, 0.055), (0.12, 0.12, 0.125))
    M["Parking_Lane"] = mat_parking("Z_Parking_Lane_Kerbside", (0.035, 0.035, 0.04), (0.09, 0.09, 0.095), 5.5, 0.12)
    M["Road_Marking"] = mat_noise("Z_Road_Marking_Paint", (0.70, 0.70, 0.68), (0.85, 0.85, 0.82), 20.0, 0.6, 0.05)
    M["Entrance_Paving"] = mat_brick("Z_Entrance_Paving", (0.52, 0.40, 0.33), (0.60, 0.47, 0.38), (0.25, 0.22, 0.20), 0.2, 0.1, 0.8)
    M["Apron_Concrete"] = mat_noise("Z_Apron_Concrete", (0.38, 0.37, 0.35), (0.55, 0.54, 0.51), 4.0, 0.85, 0.25)
    M["Forecourt_Paving"] = mat_brick("Z_Forecourt_Tiles_40cm", (0.46, 0.45, 0.43), (0.55, 0.54, 0.51), (0.28, 0.27, 0.26), 0.4, 0.4, 0.8, 0.0)
    M["Water_Channel"] = mat_noise("Z_Water_Channel", (0.03, 0.06, 0.06), (0.06, 0.10, 0.09), 2.0, 0.04, 0.08)
    M["Channel_Bank"] = mat_brick("Z_Channel_Bank_Concrete_Slabs", (0.33, 0.32, 0.30), (0.42, 0.41, 0.38), (0.18, 0.17, 0.16), 1.0, 1.0, 0.85, 0.0)
    M["Aryk"] = mat_noise("Z_Aryk_Concrete", (0.20, 0.19, 0.17), (0.36, 0.35, 0.32), 10.0, 0.7, 0.3)
    M["Water"] = mat_noise("Z_Water", (0.02, 0.05, 0.05), (0.04, 0.08, 0.08), 3.0, 0.05, 0.05)
    M["Playground"] = mat_noise("Z_Playground_Rubber", (0.55, 0.16, 0.08), (0.12, 0.35, 0.18), 0.8, 0.9, 0.1)
    M["Sport_Pitch"] = mat_noise("Z_Sport_Turf", (0.06, 0.20, 0.06), (0.09, 0.28, 0.08), 3.0, 0.85, 0.2)
    M["Street_Green"] = mat_noise("Z_Street_Green_Grass_Soil", (0.10, 0.12, 0.05), (0.20, 0.26, 0.08), 1.5, 0.95, 0.4)
    M["Lawn"] = mat_noise("Z_Lawn_Grass", (0.07, 0.15, 0.04), (0.17, 0.28, 0.07), 0.8, 0.95, 0.4)
    M["Trees_Ground"] = mat_noise("Z_Under_Trees_Soil_Leaves", (0.13, 0.10, 0.06), (0.20, 0.20, 0.08), 1.2, 0.95, 0.4)
    M["Yard_Hard"] = mat_noise("Z_Yard_Old_Asphalt_Concrete", (0.12, 0.12, 0.12), (0.30, 0.29, 0.27), 0.7, 0.85, 0.25)
    M["Private_Plot"] = mat_noise("Z_Private_Plot_Soil_Grass", (0.20, 0.16, 0.10), (0.18, 0.24, 0.09), 0.9, 0.95, 0.4)
    M["Dirt_Track"] = mat_noise("Z_Dirt_Track", (0.22, 0.17, 0.11), (0.32, 0.26, 0.17), 2.0, 0.95, 0.4)
    M["Bare_Soil"] = mat_noise("Z_Bare_Soil", (0.30, 0.24, 0.16), (0.42, 0.35, 0.24), 1.0, 0.95, 0.4)
    return M


# ----------------------------------------------------------------------------- ground tiles
def get_col(name, parent=None):
    col = bpy.data.collections.get((name, None))
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col


def build_ground(M):
    """One object per surface category (asphalt, curb, sidewalk, lawn, ...), each with a single
    material, so categories can be selected, re-textured, scattered on or optimised independently.
    Vertical step faces go to the category that owns them (kerb faces -> Curb, aryk/channel walls -> Aryk)."""
    V = Z["V"]; T = Z["T"]; TC = Z["TC"]; W = Z["W"]; WC = Z["WC"]; XA = Z["XA"]
    root = get_col(ROOTCOL)
    col = get_col("Z1_Ground_by_Category", root)
    # wall depth = larger of the two ends (split walls at height crossings are triangles [a_top, a_low, p, p])
    topz = np.maximum(V[W[:, 0], 2] - V[W[:, 1], 2], V[W[:, 3], 2] - V[W[:, 2], 2]); lowz = np.zeros(len(W))
    wall_owner = []
    for j in range(len(W)):
        c = CNAME[int(WC[j])]
        depth = topz[j] - lowz[j]
        if c in ("Aryk", "Water", "Water_Channel", "Channel_Bank") or depth > 0.3:
            wall_owner.append("Aryk" if c == "Aryk" else ("Channel_Bank" if c in ("Channel_Bank", "Water_Channel") else c if c == "Water" else "Aryk"))
        elif depth > 0.05:
            wall_owner.append("Curb")
        else:
            wall_owner.append(c)
    wall_owner = np.array(wall_owner)
    tri_cls = np.array([CNAME[int(c)] for c in TC])
    total = 0
    for name in sorted(set(tri_cls) | set(wall_owner)):
        ti = np.nonzero(tri_cls == name)[0]
        wi = np.nonzero(wall_owner == name)[0]
        if len(ti) + len(wi) == 0:
            continue
        used = np.unique(np.concatenate([T[ti].ravel(), W[wi].ravel()]))
        remap = np.full(len(V), -1, dtype=np.int64); remap[used] = np.arange(len(used))
        verts = V[used]
        def _dedup(f):
            out = []
            for v in f:
                if not out or out[-1] != v:
                    out.append(v)
            if len(out) > 1 and out[0] == out[-1]:
                out.pop()
            return out
        # QA: a wall that tapers to zero height at one end repeats a vertex; Blender's validate() deleted
        # such quads and left triangular holes -> emit them as triangles instead
        wf = [_dedup(list(remap[w])) for w in W[wi]]
        wf = [f for f in wf if len(f) >= 3]
        faces = [list(remap[t]) for t in T[ti]] + wf
        obn = "GROUND_" + name
        me = bpy.data.meshes.new(obn)
        me.from_pydata(verts.tolist(), [], faces)
        # SHEF E8: the kerbside parking strip is ordinary road asphalt (no bay paint, no separate look)
        me.materials.append(M["Asphalt_Road"] if name == "Parking_Lane" else M[name])
        uvl = me.uv_layers.new(name="UVMap")
        uvs = np.zeros((len(me.loops), 2), dtype=np.float32)
        li = 0
        for fi, f in enumerate(faces):
            if fi < len(ti):
                for v in f:
                    uvs[li] = verts[v, 0], verts[v, 1]; li += 1
            else:
                a, bb = verts[f[0]], verts[f[-1]]
                d = bb[:2] - a[:2]; L = float(np.hypot(*d)) or 1.0; d = d / L
                for v in f:
                    uvs[li] = float(verts[v, 0] * d[0] + verts[v, 1] * d[1]), verts[v, 2]; li += 1
        uvl.data.foreach_set("uv", uvs.ravel())
        at = me.attributes.new("xw_angle", "FLOAT", "FACE")
        at.data.foreach_set("value", np.concatenate([XA[ti], np.zeros(len(wf), np.float32)]).astype(np.float32))
        me.validate(clean_customdata=False)
        me.update()
        ob = bpy.data.objects.new(obn, me)
        col.objects.link(ob)
        total += len(faces)
        log("ground", obn, len(faces), "faces")
    log("ground categories done, faces", total)


# ----------------------------------------------------------------------------- trees
def placeholder_trees():
    col = get_col("Z1_Tree_Placeholders", get_col(ROOTCOL))
    bark = bpy.data.materials.get(("Z_Tree_Bark", None)) or mat_noise("Z_Tree_Bark", (0.10, 0.07, 0.05), (0.18, 0.13, 0.09), 8.0, 0.9)
    leaf = bpy.data.materials.get(("Z_Tree_Leaves", None)) or mat_noise("Z_Tree_Leaves", (0.05, 0.12, 0.03), (0.12, 0.22, 0.05), 2.0, 0.8)
    # weighted mix typical for Bishkek streets/yards: elms (karagach) and maples dominate, some poplars
    specs = [("TREE_Elm_Karagach_A", 0.18, 3.2, 3.6, 1.0), ("TREE_Elm_Karagach_B", 0.22, 3.6, 4.3, 0.95),
             ("TREE_Elm_Young", 0.12, 2.4, 2.4, 1.05), ("TREE_Maple_A", 0.14, 2.6, 2.8, 1.1),
             ("TREE_Maple_B", 0.15, 2.8, 3.2, 1.05), ("TREE_Poplar", 0.20, 3.0, 1.6, 4.0)]
    objs = []
    for name, r, trunk_h, crown_r, zscale in specs:
        me = bpy.data.meshes.new(name)
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=r, radius2=r * 0.7, depth=trunk_h,
                              matrix=__import__("mathutils").Matrix.Translation((0, 0, trunk_h / 2)))
        res = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=crown_r,
                                         matrix=__import__("mathutils").Matrix.Translation((0, 0, trunk_h + crown_r * zscale * 0.8)))
        for v in res["verts"]:
            v.co.z = trunk_h + (v.co.z - trunk_h) * zscale
        crown = set(res["verts"])
        bm.to_mesh(me); bm.free()
        me.materials.append(bark); me.materials.append(leaf)
        for p in me.polygons:
            if all(me.vertices[i].co.z > trunk_h - 0.01 for i in p.vertices) and p.center.z > trunk_h + 0.3:
                p.material_index = 1
        ob = bpy.data.objects.new(name, me)
        col.objects.link(ob)
        ob.location = (0, 0, -10000)  # parked far below, only instanced
        objs.append(ob)
    col.hide_render = True
    return col


def build_trees():
    TP = Z["TREES"]
    if len(TP) == 0:
        return
    tcol = placeholder_trees()
    me = bpy.data.meshes.new("Z1_Tree_Trunk_Points")
    me.from_pydata(TP[:, :3].tolist(), [], [])
    a = me.attributes.new("kind", "INT", "POINT")
    a.data.foreach_set("value", TP[:, 3].astype(np.int32))
    ob = bpy.data.objects.new("Z1_Trees_Instancer", me)
    get_col("Z1_Trees", get_col(ROOTCOL)).objects.link(ob)
    ng = bpy.data.node_groups.new("GN_Tree_Scatter", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N = ng.nodes; L = ng.links
    gi = N.new("NodeGroupInput"); go = N.new("NodeGroupOutput")
    ci = N.new("GeometryNodeCollectionInfo"); ci.inputs["Collection"].default_value = tcol
    ci.inputs["Separate Children"].default_value = True; ci.inputs["Reset Children"].default_value = True
    inst = N.new("GeometryNodeInstanceOnPoints")
    def rv(dtype, mn, mx):
        n = N.new("FunctionNodeRandomValue"); n.data_type = dtype
        want = {"INT": "INT", "FLOAT": "VALUE", "FLOAT_VECTOR": "VECTOR"}[dtype]
        for sock in n.inputs:
            if sock.type == want and sock.name in ("Min", "Max"):
                sock.default_value = mn if sock.name == "Min" else mx
        out = [o for o in n.outputs if o.type == want][0]
        return n, out
    rnd_i, oi = rv("INT", 0, 5)
    rnd_r, orr = rv("FLOAT_VECTOR", (0.0, 0.0, 0.0), (0.05, 0.05, 6.283))
    rnd_s, osc = rv("FLOAT", 0.75, 1.3)
    L.new(gi.outputs[0], inst.inputs["Points"])
    L.new(ci.outputs[0], inst.inputs["Instance"])
    inst.inputs["Pick Instance"].default_value = True
    L.new(oi, inst.inputs["Instance Index"])
    L.new(orr, inst.inputs["Rotation"])
    L.new(osc, inst.inputs["Scale"])
    L.new(inst.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("Trees", "NODES"); mod.node_group = ng
    log("trees", len(TP))


# ----------------------------------------------------------------------------- scene cleanup
def cleanup_v1():
    sc = bpy.context.scene
    ref = get_col("_REF_OSM_v1_overlays (hidden)")
    for name in ("04_Roads_Major", "05_Roads_Minor", "06_Roads_Service", "07_Paths_Sidewalks", "08_Railways",
                 "09_Water", "10_Landuse_Green", "11_Points_Trees_Lamps"):
        c = bpy.data.collections.get((name, None))
        if c is None:
            continue
        for parent in [sc.collection] + list(bpy.data.collections):
            if c.name in parent.children and parent != ref:
                parent.children.unlink(c)
        if c.name not in ref.children:
            ref.children.link(c)
    for lc in bpy.context.view_layer.layer_collection.children:
        if lc.collection == ref:
            lc.exclude = True
    for o in bpy.data.objects:
        if o.name == "SITE_Toktonalieva_77":
            o.location.z = 815.0 + 60.0


_DTM = None


def dtm_sample(xy):
    """30 m DTM height at local xy (same sampler as the partition)"""
    global _DTM
    import geo
    if _DTM is None:
        zdat = np.load(os.path.join(ROOT, "data", "dtm_crop.npz"))
        _DTM = geo.DEM(zdat["dtm"], float(zdat["lon_min_edge"]), float(zdat["lat_max_edge"]), float(zdat["d"]), float(zdat["d"]))
    kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0
    xy = np.asarray(xy, float).reshape(-1, 2)
    lon = geo.LON0 + xy[:, 0] / kx; lat = geo.LAT0 + xy[:, 1] / ky
    for _ in range(6):
        cx, cy = geo.to_local(lon, lat); lon = lon + (xy[:, 0] - cx) / kx; lat = lat + (xy[:, 1] - cy) / ky
    return _DTM.sample(lon, lat)


Z_SANE = 100.0   # m a.s.l.: terrain heights below this are broken (e.g. z_dtm = 0 on vertices a boolean added)


def _terrain_dtm_heights(o, co_local):
    """original (un-blended) terrain heights of all vertices in local coords: z_dtm attribute where valid, the current
    height where no attribute exists, the 30 m DTM where either is broken"""
    me = o.data
    z = co_local[:, 2].copy()
    att = me.attributes.get("z_dtm")
    if att is not None and len(att.data) == len(me.vertices):
        z0 = np.empty(len(me.vertices), np.float32); att.data.foreach_get("value", z0)
        ok = z0 > Z_SANE
        z[ok] = z0[ok]
    bad = z <= Z_SANE
    if bad.any():
        mw = np.array(o.matrix_world)
        w = co_local[bad] @ mw[:3, :3].T + mw[:3, 3]
        zw = dtm_sample(w[:, :2])
        inv = np.linalg.inv(mw)
        loc = np.column_stack([w[:, :2], zw]) @ inv[:3, :3].T + inv[:3, 3]
        z[bad] = loc[:, 2]
    return z


def cut_terrain():
    """Circular hole under the detail zone (exact boolean); Z1_Seam_Ribbon closes the seam.
    Idempotent: a tile already cut with this ring is not cut again (mesh property zone_hole_ring); before any (re)cut
    the tile gets its original DTM heights back, after it z_dtm is refreshed, so the seam blend always starts from the
    DTM and vertices added by the boolean never inherit a zero z_dtm."""
    import hashlib
    ring = json.load(open(os.path.join(DATADIR, "zone_ring.json")))[:-1]
    rhash = hashlib.md5(json.dumps([[round(x, 3), round(y, 3)] for x, y in ring]).encode()).hexdigest()[:16]
    ra = sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1] for i in range(len(ring)))
    if ra < 0:
        ring = ring[::-1]  # CCW so the cutter's normals point outward
    cut = bpy.data.meshes.new("_zone_cutter")
    n_ = len(ring)
    verts = [(x, y, -3000.0) for x, y in ring] + [(x, y, 6000.0) for x, y in ring]
    faces = [list(range(n_))[::-1], list(range(n_, 2 * n_))] + [[i, (i + 1) % n_, n_ + (i + 1) % n_, n_ + i] for i in range(n_)]
    cut.from_pydata(verts, [], faces); cut.update()
    cutter = bpy.data.objects.new("_zone_cutter", cut)
    bpy.context.scene.collection.objects.link(cutter)
    n = 0; n_skip = 0
    for o in list(bpy.data.objects):
        if not o.name.startswith("Terrain_") or o.type != "MESH":
            continue
        xs = [v[0] for v in o.bound_box]; ys = [v[1] for v in o.bound_box]
        if min(xs) > RZ or max(xs) < -RZ or min(ys) > RZ or max(ys) < -RZ:
            continue
        me = o.data
        if me.get("zone_hole_ring") == rhash:
            n_skip += 1
            continue
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        co[:, 2] = _terrain_dtm_heights(o, co)
        me.vertices.foreach_set("co", co.ravel()); me.update()
        m = o.modifiers.new("zone_hole", "BOOLEAN")
        m.operation = "DIFFERENCE"; m.solver = "EXACT"; m.object = cutter
        bpy.context.view_layer.objects.active = o
        with bpy.context.temp_override(object=o, active_object=o):
            bpy.ops.object.modifier_apply(modifier=m.name)
        c = np.empty(len(o.data.polygons) * 3); o.data.polygons.foreach_get("center", c); c = c.reshape(-1, 3)
        left = int((np.hypot(c[:, 0], c[:, 1]) < RZ - 5).sum())
        if left:
            raise RuntimeError(f"terrain cut failed on {o.name}: {left} faces left inside the zone")
        me = o.data
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        bad = co[:, 2] <= Z_SANE
        if bad.any():   # never expected after the restore, but keep the terrain sane
            co[bad, 2] = _terrain_dtm_heights(o, co)[bad]; me.vertices.foreach_set("co", co.ravel()); me.update()
        att = me.attributes.get("z_dtm") or me.attributes.new("z_dtm", "FLOAT", "POINT")
        att.data.foreach_set("value", co[:, 2].astype(np.float32))
        me["zone_hole_ring"] = rhash
        n += 1
    bpy.data.objects.remove(cutter, do_unlink=True)
    log("terrain tiles cut", n, "already cut with this ring", n_skip)
    blend_terrain_seam()


def blend_terrain_seam(band=60.0):
    """QA: the 30 m DTM terrain met the detailed zone edge with steps up to 1.6 m. Terrain vertices on the
    hole edge take the zone edge height (3 cm lower, the zone skirt covers the hairline), and the next
    `band` metres blend smoothly back to the DTM."""
    V = Z["V"]
    r = np.hypot(V[:, 0], V[:, 1])
    m = r > RZ - 0.6
    if not m.any():
        return
    ang = np.arctan2(V[m, 1], V[m, 0]); zz = V[m, 2]
    # top surface per ring position (skirt bottoms are lower copies at the same xy)
    key = np.round(ang * 1e5).astype(np.int64)
    order = np.lexsort((-zz, key)); key_s = key[order]
    first = np.r_[True, key_s[1:] != key_s[:-1]]
    a_top = ang[order][first]; z_top = zz[order][first]
    o2 = np.argsort(a_top); a_top = a_top[o2]; z_top = z_top[o2]
    a_ext = np.r_[a_top - 2 * np.pi, a_top, a_top + 2 * np.pi]; z_ext = np.r_[z_top, z_top, z_top]
    moved = 0; maxd = 0.0
    for o in bpy.data.objects:
        if not o.name.startswith("Terrain_") or o.type != "MESH":
            continue
        xs = [v[0] for v in o.bound_box]; ys = [v[1] for v in o.bound_box]
        R2 = RZ + band + 5
        if min(xs) > R2 or max(xs) < -R2 or min(ys) > R2 or max(ys) < -R2:
            continue
        me = o.data
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        # keep the original DTM height so repeated rebuilds blend from it, not from the last blend
        z0 = _terrain_dtm_heights(o, co)
        att = me.attributes.get("z_dtm") or me.attributes.new("z_dtm", "FLOAT", "POINT")
        att.data.foreach_set("value", z0.astype(np.float32))
        co[:, 2] = z0
        mw = np.array(o.matrix_world); wco = co @ mw[:3, :3].T + mw[:3, 3]
        rr = np.hypot(wco[:, 0], wco[:, 1])
        sel = rr < RZ + band
        if not sel.any():
            continue
        th0 = np.arctan2(wco[:, 1], wco[:, 0])
        zr0 = np.interp(th0, a_ext, z_ext) - 0.03
        sel &= np.abs(zr0 - wco[:, 2]) < 6.0   # tile-edge skirts hang tens of metres down: leave them
        if not sel.any():
            continue
        zr = zr0[sel]
        t = np.clip((rr[sel] - RZ) / band, 0, 1); s_ = t * t * (3 - 2 * t)
        newz = zr * (1 - s_) + wco[sel, 2] * s_
        maxd = max(maxd, float(np.abs(newz - wco[sel, 2]).max()))
        wco[sel, 2] = newz
        inv = np.linalg.inv(mw)
        co = wco @ inv[:3, :3].T + inv[:3, 3]
        me.vertices.foreach_set("co", co.ravel()); me.update()
        moved += int(sel.sum())
    log("terrain seam blended: verts", moved, "max change m", round(maxd, 2))




# ----------------------------------------------------------------------------- seam ribbon (zone edge <-> terrain hole)
def _ring_line():
    from shapely.geometry import Polygon as SPoly
    ring = json.load(open(os.path.join(DATADIR, "zone_ring.json")))
    return SPoly(np.asarray(ring, float)[:, :2]).exterior


def _terrain_ring_edges(ring_line):
    """boundary edges of the cut terrain tiles lying on the ring: list of (xyz_a, xyz_b) in world space"""
    import shapely
    R = float(np.hypot(*np.asarray(ring_line.coords).T).max())
    out = []
    for o in bpy.data.objects:
        if not o.name.startswith("Terrain_") or o.type != "MESH":
            continue
        me = o.data
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        mw = np.array(o.matrix_world)
        if not np.allclose(mw, np.eye(4)):
            co = co @ mw[:3, :3].T + mw[:3, 3]
        r = np.hypot(co[:, 0], co[:, 1])
        near = np.abs(r - R) < 5
        if not near.any():
            continue
        ev = np.empty(len(me.edges) * 2, np.int64); me.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
        ev = ev[near[ev[:, 0]] & near[ev[:, 1]]]
        if not len(ev):
            continue
        # boundary = edge used by one face
        lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv)
        ls = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_start", ls)
        lt = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", lt)
        fol = np.repeat(np.arange(len(ls)), lt); pos = np.arange(len(lv)) - ls[fol]; nxt = ls[fol] + (pos + 1) % lt[fol]
        a, b = lv, lv[nxt]
        m = near[a] & near[b]
        a, b = a[m], b[m]
        k = np.minimum(a, b) * (len(co) + 1) + np.maximum(a, b)
        u, c = np.unique(k, return_counts=True)
        kb = u[c == 1]
        ek = np.minimum(ev[:, 0], ev[:, 1]) * (len(co) + 1) + np.maximum(ev[:, 0], ev[:, 1])
        ev = ev[np.isin(ek, kb)]
        if not len(ev):
            continue
        pa = co[ev[:, 0]]; pb = co[ev[:, 1]]
        on = (shapely.distance(ring_line, shapely.points(pa[:, :2])) < 0.05) & (shapely.distance(ring_line, shapely.points(pb[:, :2])) < 0.05)
        on &= np.hypot(*(pb[:, :2] - pa[:, :2]).T) > 1e-3
        out += list(zip(pa[on], pb[on]))
    return out


def build_seam_ribbon():
    """QA: the 1 km zone edge and the 35 km terrain hole edge run along the same ring but at different heights
    (30 m DTM chords vs kerbs, aryks and the canal of the zone). A vertical ribbon on the ring closes the slot
    between them everywhere: at every position of the union of both vertex sets it spans from the zone edge to the
    terrain edge (split where they cross), faces turned to the side they are seen from. Rebuilt on every run."""
    import shapely
    ring_line = _ring_line()
    L = ring_line.length
    V = Z["V"]; T = Z["T"]
    # zone top edges on the ring = triangle edges with no partner in the triangle set, lying on the ring
    E = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    N = len(V) + 1
    key = E[:, 0] * N + E[:, 1]; rkey = E[:, 1] * N + E[:, 0]
    E = E[~np.isin(rkey, key)]
    d = lambda P: shapely.distance(ring_line, shapely.points(P[:, :2]))
    E = E[(d(V[E[:, 0]]) < 0.01) & (d(V[E[:, 1]]) < 0.01) & (d((V[E[:, 0]] + V[E[:, 1]]) / 2) < 0.01)]
    E = E[np.hypot(*(V[E[:, 1], :2] - V[E[:, 0], :2]).T) > 1e-3]
    ter = _terrain_ring_edges(ring_line)
    if not len(E) or not ter:
        log("seam ribbon skipped: zone edges", len(E), "terrain edges", len(ter))
        return
    # terrain edge profile along the ring = upper envelope of all hole-edge segments (neighbouring 5 km tiles
    # overlap at their borders; tile skirts hang below): breakpoints at every segment end and every crossing
    segs = []
    for pa_, pb_ in ter:
        sa = float(ring_line.project(shapely.Point(pa_[0], pa_[1]))); sb = float(ring_line.project(shapely.Point(pb_[0], pb_[1])))
        za, zb = float(pa_[2]), float(pb_[2])
        if sb < sa:
            sa, sb, za, zb = sb, sa, zb, za
        if sb - sa > L / 2:
            sa, sb, za, zb = sb, sa + L, zb, za
        if sb - sa > 1e-6:
            segs.append((sa, za, sb, zb))
    segs = sorted(segs + [(a_ - L, za_, b_ - L, zb_) for a_, za_, b_, zb_ in segs if b_ > L])
    bps = {round(v, 6) for a_, _, b_, _ in segs for v in (a_ % L, b_ % L)}
    for i, (a1, z1, b1, w1) in enumerate(segs):
        for a2, z2, b2, w2 in segs[i + 1:]:
            if a2 >= b1:
                break
            lo, hi = max(a1, a2), min(b1, b2)
            if hi - lo < 1e-6:
                continue
            f = lambda s_: (z1 + (w1 - z1) * (s_ - a1) / (b1 - a1)) - (z2 + (w2 - z2) * (s_ - a2) / (b2 - a2))
            f0, f1 = f(lo), f(hi)
            if f0 * f1 < 0:
                bps.add(round((lo + (hi - lo) * f0 / (f0 - f1)) % L, 6))
    ts = np.array(sorted(bps))
    # envelope pieces between consecutive breakpoints: one segment is on top over the whole piece (no crossing
    # inside); where a tile's edge ends the envelope may jump -> each piece keeps its own end heights
    segs2 = segs + [(a_ + L, za_, b_ + L, zb_) for a_, za_, b_, zb_ in segs]
    t_ext = np.r_[ts, ts[0] + L]
    piece = []
    for k in range(len(ts)):
        t0, t1 = t_ext[k], t_ext[k + 1]; m_ = (t0 + t1) / 2
        best = None
        for a_, za_, b_, zb_ in segs2:
            if a_ - 1e-9 <= m_ <= b_ + 1e-9:
                zm = za_ + (zb_ - za_) * (m_ - a_) / (b_ - a_)
                if best is None or zm > best[0]:
                    best = (zm, a_, za_, b_, zb_)
        if best is None:
            piece.append(None); continue
        _, a_, za_, b_, zb_ = best
        piece.append((za_ + (zb_ - za_) * (t0 - a_) / (b_ - a_), za_ + (zb_ - za_) * (t1 - a_) / (b_ - a_)))
    ts_x = np.r_[ts - L, ts, ts + L]
    XY_t = shapely.get_coordinates(shapely.line_interpolate_point(ring_line, ts))
    XY_x = np.concatenate([XY_t, XY_t, XY_t])

    def zter(u, v):
        """terrain edge heights at u and v (u < v inside one envelope piece)"""
        m_ = (u + v) / 2
        mm = (m_ - ts[0]) % L + ts[0]; sh = mm - m_
        k = int(np.searchsorted(t_ext, mm, "right")) - 1
        k = min(max(k, 0), len(ts) - 1)
        pc = piece[k]
        if pc is None:
            return None, None
        t0, t1 = t_ext[k], t_ext[k + 1]
        f = lambda t: pc[0] + (pc[1] - pc[0]) * ((t + sh) - t0) / (t1 - t0)
        return f(u), f(v)
    verts, faces, uvs = [], [], []
    vkey = {}

    def vid(p, s):
        k = (round(p[0] * 1e4), round(p[1] * 1e4), round(p[2] * 1e4))
        i = vkey.get(k)
        if i is None:
            i = len(verts); vkey[k] = i; verts.append(tuple(p)); uvs.append((s, p[2]))
        return i

    def face(pts, ss, terrain_higher):
        P = np.array(pts)
        if len({(round(p[0], 4), round(p[1], 4), round(p[2], 4)) for p in pts}) < 3:
            return
        q = np.roll(P, -1, axis=0)
        n = np.array([np.sum((P[:, 1] - q[:, 1]) * (P[:, 2] + q[:, 2])), np.sum((P[:, 2] - q[:, 2]) * (P[:, 0] + q[:, 0])),
                      np.sum((P[:, 0] - q[:, 0]) * (P[:, 1] + q[:, 1]))])
        if np.linalg.norm(n) < 1e-7:
            return
        c = P.mean(0); radial = np.array([c[0], c[1], 0.0])
        want = -radial if terrain_higher else radial   # seen from inside when the terrain is higher
        if np.dot(n, want) < 0:
            pts = pts[::-1]; ss = ss[::-1]
        faces.append([vid(p, s_) for p, s_ in zip(pts, ss)])
    n_seg = 0; hmax = 0.0
    for a, b in E:
        pa, pb = V[a], V[b]
        sa = float(ring_line.project(shapely.Point(pa[0], pa[1]))); sb = float(ring_line.project(shapely.Point(pb[0], pb[1])))
        if sb < sa:
            pa, pb, sa, sb = pb, pa, sb, sa
        if sb - sa > L / 2:          # edge across s = 0
            pa, pb, sa, sb = pb, pa, sb, sa + L
        inner = (ts_x > sa + 1e-4) & (ts_x < sb - 1e-4)
        S = np.r_[sa, ts_x[inner], sb]
        XY = np.vstack([pa[:2], XY_x[inner], pb[:2]])
        ZZ = pa[2] + (pb[2] - pa[2]) * (S - sa) / (sb - sa)
        for i in range(len(S) - 1):
            zu, zv = zter(S[i], S[i + 1])
            if zu is None:
                continue
            ZT = {i: zu, i + 1: zv}
            d0 = ZT[i] - ZZ[i]; d1 = ZT[i + 1] - ZZ[i + 1]
            hmax = max(hmax, abs(d0), abs(d1))
            if abs(d0) < 1e-3 and abs(d1) < 1e-3:
                continue
            Z0 = (XY[i][0], XY[i][1], ZZ[i]); Z1 = (XY[i + 1][0], XY[i + 1][1], ZZ[i + 1])
            T0 = (XY[i][0], XY[i][1], ZT[i]); T1 = (XY[i + 1][0], XY[i + 1][1], ZT[i + 1])
            if d0 * d1 >= 0 or abs(d0) < 1e-3 or abs(d1) < 1e-3:
                up = (d0 + d1) > 0
                if abs(d0) < 1e-3:
                    face([Z0, Z1, T1], [S[i], S[i + 1], S[i + 1]], up)
                elif abs(d1) < 1e-3:
                    face([Z0, Z1, T0], [S[i], S[i + 1], S[i]], up)
                else:
                    face([Z0, Z1, T1, T0], [S[i], S[i + 1], S[i + 1], S[i]], up)
            else:
                t = d0 / (d0 - d1)
                sx = S[i] + (S[i + 1] - S[i]) * t
                xy = XY[i] + (XY[i + 1] - XY[i]) * t
                X = (xy[0], xy[1], ZZ[i] + (ZZ[i + 1] - ZZ[i]) * t)
                face([Z0, X, T0], [S[i], sx, S[i]], d0 > 0)
                face([X, Z1, T1], [sx, S[i + 1], S[i + 1]], d1 > 0)
        n_seg += 1
    if not faces:
        log("seam ribbon: zone and terrain edges coincide, nothing to close")
        return
    mat = bpy.data.materials.get(("Z_Seam_Ribbon_Soil", None)) or mat_noise("Z_Seam_Ribbon_Soil", (0.26, 0.23, 0.19), (0.40, 0.37, 0.31), 1.2, 0.95, 0.3)
    me = bpy.data.meshes.new("Z1_Seam_Ribbon")
    me.from_pydata(verts, [], faces)
    me.materials.append(mat)
    uvl = me.uv_layers.new(name="UVMap")
    lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv)
    uvl.data.foreach_set("uv", np.asarray(uvs, np.float32)[lv].ravel())
    me.validate(clean_customdata=False); me.update()
    ob = bpy.data.objects.new("Z1_Seam_Ribbon", me)
    get_col(ROOTCOL).objects.link(ob)
    log("seam ribbon: zone edge segments", n_seg, "terrain edge points", len(ts), "faces", len(faces), "max height m", round(hmax, 2))


# ----------------------------------------------------------------------------- plot walls (duval)
def build_plot_walls():
    PW = Z["PW"] if "PW" in Z.files else np.zeros((0, 6))
    if len(PW) == 0:
        return
    mat = mat_noise("Z_Plot_Wall_Duval", (0.45, 0.40, 0.33), (0.62, 0.57, 0.48), 1.5, 0.9, 0.3)
    cap = mat_noise("Z_Wall_Cap_Concrete", (0.40, 0.39, 0.37), (0.55, 0.54, 0.51), 6.0, 0.85, 0.2)
    col = get_col("Z1_Plot_Walls", get_col(ROOTCOL))
    H, TH = 2.2, 0.25
    tiles = {}
    for x0, y0, x1, y1, za, zb in PW:
        d = np.array([x1 - x0, y1 - y0]); L = float(np.hypot(*d))
        if L < 0.2:
            continue
        d /= L
        nl = np.array([-d[1], d[0]]) * TH  # plot interior is on the left of a->b
        k = (int(math.floor((x0 + x1) / 2 / TILE)), int(math.floor((y0 + y1) / 2 / TILE)))
        v, f, m = tiles.setdefault(k, ([], [], []))
        s = len(v)
        a = (x0, y0); b = (x1, y1); ai = (x0 + nl[0], y0 + nl[1]); bi = (x1 + nl[0], y1 + nl[1])
        for (px, py), z in ((a, za), (b, zb), (bi, zb), (ai, za)):
            v.append((px, py, z - 0.3))
        for (px, py), z in ((a, za), (b, zb), (bi, zb), (ai, za)):
            v.append((px, py, z + H))
        f += [[s + 0, s + 1, s + 5, s + 4], [s + 2, s + 3, s + 7, s + 6], [s + 4, s + 5, s + 6, s + 7],
              [s + 1, s + 2, s + 6, s + 5], [s + 3, s + 0, s + 4, s + 7]]
        m += [0, 0, 1, 0, 0]
    allv, allf, allm = [], [], []
    for k, (v, f, m) in tiles.items():
        o_ = len(allv); allv += v; allf += [[i + o_ for i in poly] for poly in f]; allm += m
    tiles = {"all": (allv, allf, allm)}
    for k, (v, f, m) in tiles.items():
        me = bpy.data.meshes.new("WALLS_Private_Plot_Duval")
        me.from_pydata(v, [], f)
        me.materials.append(mat); me.materials.append(cap)
        me.polygons.foreach_set("material_index", m)
        uvl = me.uv_layers.new(name="UVMap")
        co = np.array(v); uv = []
        for poly in f:
            p0, p1 = co[poly[0]], co[poly[1]]
            dd = p1[:2] - p0[:2]; LL = float(np.hypot(*dd)) or 1; dd /= LL
            for i in poly:
                uv.append((float(co[i, 0] * dd[0] + co[i, 1] * dd[1]), float(co[i, 2])))
        uvl.data.foreach_set("uv", np.array(uv, dtype=np.float32).ravel())
        me.validate(); me.update()
        col.objects.link(bpy.data.objects.new(me.name, me))
    log("plot walls", len(PW))


# ----------------------------------------------------------------------------- LOD2 buildings in zone
def _ground_min_sampler():
    """lowest height of the partition's top surface inside (footprint + r): exact on the clipped triangle planes"""
    import shapely
    from shapely.strtree import STRtree
    V = Z["V"]; T = Z["T"]
    tri = shapely.polygons(V[T][:, :, :2])
    tree = STRtree(tri)
    P0 = V[T[:, 0]]; Nf = np.cross(V[T[:, 1]] - P0, V[T[:, 2]] - P0)

    def f(poly, r):
        region = poly.buffer(r)
        ids = tree.query(region, predicate="intersects")
        if not len(ids):
            return None
        clip = shapely.intersection(tri[ids], region)
        xy, gi = shapely.get_coordinates(clip, return_index=True)
        if not len(xy):
            return None
        t = ids[gi]; nz = Nf[t, 2]; ok = np.abs(nz) > 1e-12
        if not ok.any():
            return None
        t = t[ok]; xy = xy[ok]
        z = P0[t, 2] - (Nf[t, 0] * (xy[:, 0] - P0[t, 0]) + Nf[t, 1] * (xy[:, 1] - P0[t, 1])) / Nf[t, 2]
        return float(z.min())
    return f


def build_zone_buildings():
    from shapely.geometry import Polygon as SPoly, Point as SPt
    from shapely import segmentize as shapely_segmentize
    from shapely.strtree import STRtree
    import geo
    fps = json.load(open(os.path.join(DATADIR, "zone_footprints_local.json")))
    polys = [SPoly(f["outer"], f["inner"]) for f in fps]
    polys = [p if p.is_valid else p.buffer(0) for p in polys]
    # 1) remove the v1 LOD1 faces of these buildings
    tree = STRtree([p.buffer(0.35) for p in polys])
    removed = 0
    for o in ([] if CITY else bpy.data.objects):   # city tile files hold no v1 model (integration step removes it)
        if not o.name.startswith("Bld_") or o.type != "MESH":
            continue
        xs = [v[0] for v in o.bound_box]; ys = [v[1] for v in o.bound_box]
        if min(xs) > RZ + 50 or max(xs) < -RZ - 50 or min(ys) > RZ + 50 or max(ys) < -RZ - 50:
            continue
        bm = bmesh.new(); bm.from_mesh(o.data)
        cents = [f.calc_center_median() for f in bm.faces]
        pts = [SPt(c.x, c.y) for c in cents]
        hit = set()
        if pts:
            inp, _ = tree.query(pts, predicate="intersects")
            hit = set(inp.tolist())
        kill = [f for i, f in enumerate(bm.faces) if i in hit]
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        removed += len(kill)
        bm.to_mesh(o.data); bm.free(); o.data.update()
    log("v1 faces removed in zone", removed)
    # 2) rebuild: houses (small, rectangular) get hip roofs; others flat roof + parapet
    zdat = np.load(os.path.join(ROOT, "data", "dtm_crop.npz"))
    dem = geo.DEM(zdat["dtm"], float(zdat["lon_min_edge"]), float(zdat["lat_max_edge"]), float(zdat["d"]), float(zdat["d"]))
    kx = 111320.0 * math.cos(math.radians(geo.LAT0)); ky = 110574.0

    def zs(xy):
        xy = np.asarray(xy)
        lon = geo.LON0 + xy[:, 0] / kx; lat = geo.LAT0 + xy[:, 1] / ky
        for _ in range(6):
            cx, cy = geo.to_local(lon, lat); lon = lon + (xy[:, 0] - cx) / kx; lat = lat + (xy[:, 1] - cy) / ky
        return dem.sample(lon, lat)

    ctp_ = os.path.join(ROOT, "data", "city", "osm", f"T_{CITY[0]}_{CITY[1]}.json") if CITY else ""
    if CITY and os.path.exists(ctp_):
        B = json.load(open(ctp_, encoding="utf-8"))["buildings"]
    elif os.path.exists(os.path.join(ROOT, "data", "zone_raw.json")):
        B = json.load(open(os.path.join(ROOT, "data", "zone_raw.json"), encoding="utf-8"))["buildings"]
    else:
        B = json.load(open(os.path.join(ROOT, "data", "osm", "extract", "buildings.json"), encoding="utf-8"))
    # tag lookup by footprint centroid
    tag_pts, tag_list = [], []
    for b in B:
        o_ = np.asarray(b["polys"][0]["outer"]); x, y = geo.to_local(o_[:, 0], o_[:, 1])
        tag_pts.append(SPt(float(x.mean()), float(y.mean()))); tag_list.append(b["tags"])
    ttree = STRtree(tag_pts)
    tp_ = os.path.join(DATADIR, "tile_building_tags.json")
    TILE_TAGS = json.load(open(tp_)) if os.path.exists(tp_) else []
    walls_m = mat_noise("Z_House_Plaster", (0.55, 0.50, 0.42), (0.72, 0.68, 0.60), 0.8, 0.85, 0.2)
    apt_m = mat_brick("Z_Apartment_Brick", (0.46, 0.33, 0.22), (0.55, 0.41, 0.28), (0.5, 0.48, 0.44), 0.25, 0.075, 0.85)
    roof_m = bpy.data.materials.get(("Z_Roof_Metal", None)) or bpy.data.materials.new("Z_Roof_Metal")
    nt, bsdf, uv = _nodes(roof_m)
    at = nt.nodes.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = "roof_col"; at.location = (-600, 200)
    cr = nt.nodes.new("ShaderNodeValToRGB"); cr.location = (-350, 200); cr.color_ramp.interpolation = "CONSTANT"
    pal = [(0.35, 0.06, 0.05), (0.10, 0.22, 0.12), (0.10, 0.16, 0.30), (0.42, 0.42, 0.40), (0.25, 0.25, 0.24)]
    cr.color_ramp.elements[0].color = (*pal[0], 1); cr.color_ramp.elements[1].position = 0.2; cr.color_ramp.elements[1].color = (*pal[1], 1)
    for i, c in enumerate(pal[2:]):
        e = cr.color_ramp.elements.new(0.4 + 0.2 * i); e.color = (*c, 1)
    nt.links.new(at.outputs["Fac"], cr.inputs["Fac"]); nt.links.new(cr.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Metallic"].default_value = 0.4; bsdf.inputs["Roughness"].default_value = 0.5
    wave = nt.nodes.new("ShaderNodeTexWave"); wave.location = (-400, -250); wave.inputs["Scale"].default_value = 30.0
    nt.links.new(uv.outputs["UV"], wave.inputs["Vector"]); _bump(nt, wave.outputs["Fac"], 0.15, bsdf)
    flat_m = mat_noise("Z_Flat_Roof_Bitumen", (0.08, 0.08, 0.08), (0.18, 0.18, 0.17), 1.0, 0.9, 0.2)
    zroot = get_col(ROOTCOL)
    col_h = get_col("Z1_Buildings_Houses", zroot)
    col_a = get_col("Z1_Buildings_Apartments_Other", zroot)
    rng = np.random.default_rng(3)
    ground_min = _ground_min_sampler()
    tiles = {}
    n_hip = 0
    n_sunk = 0
    for fi_, p in enumerate(polys):
        if p.area < 4:
            continue
        c = p.centroid
        ti = ttree.nearest(c)
        tags = tag_list[ti] if tag_pts[ti].distance(c) < 30 else {}
        for tb in TILE_TAGS:   # buildings added from close imagery carry their own level count
            if abs(tb["c"][0] - c.x) < 2.0 and abs(tb["c"][1] - c.y) < 2.0:
                tags = {"building": "yes", "building:levels": str(tb.get("levels") or 1)}
                break
        lv = None
        try:
            lv = float(str(tags.get("building:levels", "")).replace(",", "."))
        except Exception:
            lv = None
        area = p.area
        house = area < 350 and tags.get("building", "yes") in ("yes", "house", "detached", "residential", "semidetached_house", "bungalow")
        if lv is None:
            lv = 1 if area < 220 else (2 if area < 350 else (3 if area < 1200 else 5))
        eave = lv * 3.0 + 0.4
        ext = np.array(p.exterior.coords)[:-1]
        g = zs(ext)
        dense = np.concatenate([np.array(shapely_segmentize(r, 1.0).coords) for r in [p.exterior, *p.interiors]])
        base = float(zs(dense).min()) - 0.8   # QA: bases floated on the downhill side / beside aryks
        gmin = ground_min(p, 1.3)              # QA: lowest modelled ground (aryk, canal bank, kerb) within 1.3 m
        if gmin is not None and gmin - 0.1 < base:
            base = gmin - 0.1; n_sunk += 1
        top = float(g.mean()) + 0.15 + eave
        addr = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])) or tags.get("name") or ""
        k = (len(tiles), ("H_" if house else "B_") + (addr.replace(" ", "_")[:40] if addr else f"{c.x:.0f}_{c.y:.0f}"), house, fi_)
        v, f, m, rc = tiles.setdefault(k, ([], [], [], []))
        wall_mat = 0 if house else 1
        rings = [ext] + [np.array(r.coords)[:-1] for r in p.interiors]
        for ri, r in enumerate(rings):
            ar = 0.5 * float(np.dot(r[:, 0], np.roll(r[:, 1], -1)) - np.dot(r[:, 1], np.roll(r[:, 0], -1)))
            if (ri == 0 and ar < 0) or (ri > 0 and ar > 0):
                r = r[::-1]
            s = len(v); n = len(r)
            for q in r: v.append((q[0], q[1], base))
            for q in r: v.append((q[0], q[1], top))
            for i in range(n):
                j = (i + 1) % n
                f.append([s + i, s + j, s + n + j, s + n + i]); m.append(wall_mat); rc.append(0.0)
        mrr = p.minimum_rotated_rectangle
        rect = np.array(mrr.exterior.coords)[:-1] if mrr.geom_type == "Polygon" else None
        if house and rect is not None and area / max(mrr.area, 1e-6) > 0.78:
            e = [np.linalg.norm(rect[(i + 1) % 4] - rect[i]) for i in range(4)]
            i0 = 0 if e[0] >= e[1] else 1
            A_, B_, C_, D_ = rect[i0], rect[(i0 + 1) % 4], rect[(i0 + 2) % 4], rect[(i0 + 3) % 4]
            Lv = B_ - A_; Wv = D_ - A_
            L = np.linalg.norm(Lv); W = np.linalg.norm(Wv)
            ul, uw = Lv / L, Wv / W
            ov = 0.45
            A2 = A_ - ul * ov - uw * ov; B2 = B_ + ul * ov - uw * ov; C2 = C_ + ul * ov + uw * ov; D2 = D_ - ul * ov + uw * ov
            W2 = W + 2 * ov; L2 = L + 2 * ov
            hr = (W2 / 2) * math.tan(math.radians(rng.uniform(20, 30)))
            mid = (A2 + C2) / 2
            half_ridge = max((L2 - W2) / 2, 0.0)
            R1 = mid - ul * half_ridge; R2 = mid + ul * half_ridge
            zr = top + hr
            s = len(v)
            for q in (A2, B2, C2, D2):
                v.append((q[0], q[1], top))
            v.append((R1[0], R1[1], zr)); v.append((R2[0], R2[1], zr))
            col_idx = float(rng.integers(0, 5)) / 5.0 + 0.05
            quads = [[s + 0, s + 1, s + 5, s + 4], [s + 2, s + 3, s + 4, s + 5]]
            tris_ = [[s + 1, s + 2, s + 5], [s + 3, s + 0, s + 4]]
            for q in quads + tris_:
                f.append(q); m.append(2); rc.append(col_idx)
            # soffit (underside of eaves)
            f.append([s + 3, s + 2, s + 1, s + 0]); m.append(0); rc.append(0.0)
            n_hip += 1
        else:
            from mathutils import Vector as V3
            from mathutils.geometry import tessellate_polygon
            flat = [[V3((q[0], q[1], 0)) for q in r] for r in rings]
            allp = [q for r in rings for q in r]
            s = len(v)
            for q in allp: v.append((q[0], q[1], top))
            for t in tessellate_polygon(flat):
                a_, b_, c_ = allp[t[0]], allp[t[1]], allp[t[2]]
                cz = (b_[0] - a_[0]) * (c_[1] - a_[1]) - (b_[1] - a_[1]) * (c_[0] - a_[0])
                tri = [s + t[0], s + t[1], s + t[2]]
                f.append(tri if cz > 0 else tri[::-1]); m.append(3); rc.append(0.0)
    for k, (v, f, m, rc) in tiles.items():
        me = bpy.data.meshes.new(k[1])
        me.from_pydata(v, [], f)
        for mm in (walls_m, apt_m, roof_m, flat_m):
            me.materials.append(mm)
        me.polygons.foreach_set("material_index", m)
        a = me.attributes.new("roof_col", "FLOAT", "FACE"); a.data.foreach_set("value", rc)
        uvl = me.uv_layers.new(name="UVMap")
        co = np.array(v); uvs = []
        for poly in f:
            nz = 0.0
            p0, p1 = co[poly[0]], co[poly[1]]
            vert = abs(p0[2] - co[poly[2]][2]) > 0.5 and len(poly) == 4 and abs(p0[2] - p1[2]) < 1e-3
            if vert:
                dd = p1[:2] - p0[:2]; LL = float(np.hypot(*dd)) or 1; dd /= LL
                for i in poly: uvs.append((float(co[i, 0] * dd[0] + co[i, 1] * dd[1]), float(co[i, 2])))
            else:
                for i in poly: uvs.append((float(co[i, 0]), float(co[i, 1])))
        uvl.data.foreach_set("uv", np.array(uvs, dtype=np.float32).ravel())
        # drop unused material slots so each building carries only what it uses
        me.validate(); me.update()
        ob = bpy.data.objects.new(me.name, me)
        ob["fp_index"] = int(k[3])   # index into data/zone_footprints_local.json (QA uses the real footprint)
        (col_h if k[2] else col_a).objects.link(ob)
        # origin at the footprint centre (easier to select / replace in UE)
        cxy = np.array(v)[:, :2].mean(0); zmin = float(np.array(v)[:, 2].min())
        me.transform(__import__("mathutils").Matrix.Translation((-cxy[0], -cxy[1], -zmin)))
        ob.location = (cxy[0], cxy[1], zmin)
    log("zone buildings", len(polys), "hip roofs", n_hip, "bases lowered to the adjacent ground", n_sunk)


def main():
    # single working file, updated in place
    src = os.environ.get("BISHKEK_BLEND", os.path.join(ROOT, "Bishkek_35km.blend"))
    out = os.environ.get("BISHKEK_OUT", src)
    if CITY:
        # one .blend per city tile, built from an empty scene; linked into the main file by 15_integrate_city.py
        out = os.path.join(ROOT, "city", f"tile_{CITY[0]}_{CITY[1]}.blend")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.unit_settings.system = "METRIC"
    else:
        bpy.ops.wm.open_mainfile(filepath=src)
    # speed: the working file links ~260 city tiles; keep them out of the view layer while the zone is rebuilt
    # (every operator would otherwise evaluate them), restore the viewer's choice before saving
    _tiles_state = {}
    for lc in bpy.context.view_layer.layer_collection.children:
        if lc.name == "CITY_1km_Tiles":
            _tiles_state = {c.name: c.exclude for c in lc.children}
            _tiles_state["__root__"] = lc.exclude
            lc.exclude = True
    old = bpy.data.collections.get(("Z1_DetailZone_1km", None))
    if old:
        for o in list(old.all_objects):
            bpy.data.objects.remove(o, do_unlink=True)
        for c in list(old.children_recursive):
            bpy.data.collections.remove(c)
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)   # linked: 260 tile libraries -> minutes
    if not CITY:
        cleanup_v1()
        cut_terrain()
    M = build_materials()
    # SHEF E5: distinct PBR textures per surface type (asphalt / paving / concrete / soil ...), module 07b
    import importlib.util
    for nm in ("07b_zone_materials.py", "zone_materials.py"):
        mp_ = os.path.join(ROOT, "scripts", nm)
        if os.path.exists(mp_):
            try:
                spec = importlib.util.spec_from_file_location("zone_materials_07b", mp_)
                m07b = importlib.util.module_from_spec(spec); spec.loader.exec_module(m07b)
                m07b.upgrade_materials(M, ROOT, log=log)
            except Exception as e:
                log("WARNING 07b materials failed:", e)
            break
    build_ground(M)
    # the seam ribbon closes the zone edge against the terrain; not needed where city tiles (15_integrate_city) surround the zone
    if not CITY and not bpy.data.collections.get(("CITY_1km_Tiles", None)):
        build_seam_ribbon()
    build_plot_walls()
    build_zone_buildings()
    build_trees()
    # stage 08: close any remaining holes in the ground surface (see repair_ground.py)
    import importlib.util
    for nm in ("08_repair_ground.py", "repair_ground.py"):
        rp = os.path.join(ROOT, "scripts", nm)
        if os.path.exists(rp):
            spec = importlib.util.spec_from_file_location("repair_ground", rp)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            sys.modules["repair_ground"] = mod
            mod.repair_ground(log=log)
            break
    if _tiles_state:
        for lc in bpy.context.view_layer.layer_collection.children:
            if lc.name == "CITY_1km_Tiles":
                lc.exclude = _tiles_state.get("__root__", False)
                for c in lc.children:
                    if c.name in _tiles_state:
                        c.exclude = _tiles_state[c.name]
    bpy.context.preferences.filepaths.save_version = 0  # no .blend1 backups next to the working file
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    log("SAVED", out)


if __name__ == "__main__":
    main()
