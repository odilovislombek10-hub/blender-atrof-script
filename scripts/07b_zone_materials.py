"""07b_zone_materials.py - PBR ground materials for the 1 km detail zone (Z1).

Upgrades the procedural Z_* ground materials made by 07_zone_blender.build_materials() to
image-based PBR (Poly Haven, CC0) so every surface type reads clearly and differently:
asphalt / worn asphalt / paving (bruschatka) / large slabs / concrete / soil / grass / ...

Textures: <root>/textures/pbr/<slot>/*.jpg, listed in <root>/textures/pbr/manifest.json
          {slot: {id, name, size_m:[x, y], diffuse, normal, rough}}  (paths relative to textures/pbr)
UVs:      layer "UVMap" is world metres on horizontal faces (along-wall metres, z on walls),
          so a texture of size_m tiles with scale 1/size_m.

API
    upgrade_materials(M, root, log=print)   M = {category: bpy material}, e.g. from build_materials()
    apply_to_open_scene(root=None, log=print)  finds GROUND_<Category> objects in the current scene

Idempotent: every call rebuilds the node trees of the given materials (and the shared
PBR07b_<slot> node groups) from scratch; images are loaded with check_existing=True.
The crosswalk / parking-bay stripe masks (face attribute "xw_angle") of the original
materials are kept and painted on top of the asphalt texture.
A slot without textures (e.g. download failed) falls back to a procedural look.
"""
import os
import json
import bpy

VERSION = "07b-r9.1"
PBR_SUB = ("textures", "pbr")
UVMAP = "UVMap"
MARK = "pbr07b"                       # material custom property: recipe marker
STRIPE_NODE = "PBR07b_stripe_mask"    # reroute that keeps the original stripe mask
SKIP = ("Water", "Water_Channel")     # kept as they are


def _lin(c):
    """sRGB (0-1) -> linear."""
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


# Solid-view colours (sRGB) - one readable colour per surface type
VIEW = {
    "Asphalt_Road": (0.20, 0.20, 0.21), "Parking_Asphalt": (0.27, 0.27, 0.29),
    "Parking_Lane": (0.24, 0.24, 0.26), "Crosswalk": (0.44, 0.44, 0.46),
    "Road_Marking": (0.94, 0.94, 0.90), "Cycleway": (0.78, 0.20, 0.16),
    "Yard_Hard": (0.47, 0.47, 0.47),
    "Sidewalk_Paving": (0.71, 0.65, 0.56), "Path_Paving": (0.67, 0.62, 0.54),
    "Entrance_Paving": (0.76, 0.59, 0.48), "Forecourt_Paving": (0.89, 0.82, 0.67),
    "Curb": (0.82, 0.82, 0.80), "Apron_Concrete": (0.76, 0.76, 0.74),
    "Aryk": (0.68, 0.70, 0.70), "Channel_Bank": (0.72, 0.72, 0.70),
    "Bare_Soil": (0.50, 0.33, 0.18), "Dirt_Track": (0.60, 0.48, 0.34),
    "Private_Plot": (0.52, 0.46, 0.26), "Lawn": (0.25, 0.56, 0.18),
    "Street_Green": (0.52, 0.53, 0.24), "Trees_Ground": (0.42, 0.41, 0.22),
    "Playground": (0.80, 0.40, 0.26), "Sport_Pitch": (0.12, 0.80, 0.25),
}

# Layer = colour grading of one texture slot:
#   hue (0.5 = none), sat / val multipliers, tint = (colour, factor) with COLOR blend,
#   rough = (mul, add) on the roughness map, nrm = normal-map strength
ASPH = dict(slot="asphalt", sat=0.35, val=0.72, rough=(0.8, 0.14), nrm=0.8)
GRASS_LAWN = dict(slot="grass", val=0.55, tint=((0.16, 0.36, 0.07), 0.60), rough=(0.5, 0.42), nrm=0.9)

# Recipe per category: base layer, optional second layer blended by a large noise mask
# ("mix": (layer, coverage 0-1, feature size m)), large-scale value variation "var",
# "stripes" keeps the original xw_angle stripe mask, "paint" for road-marking polygons,
# "joints" = (w, h, mortar m, darken) slab joints, "proc" = procedural material.
RECIPES = {
    "Asphalt_Road": dict(base=ASPH, var=0.12),
    "Parking_Asphalt": dict(base=dict(ASPH, val=0.82), var=0.10, stripes=True),
    "Parking_Lane": dict(base=dict(ASPH, val=0.76), var=0.10, stripes=True),
    "Crosswalk": dict(base=ASPH, var=0.10, stripes=True),
    "Road_Marking": dict(base=ASPH, var=0.05, paint=True),
    "Cycleway": dict(base=dict(slot="asphalt", val=1.25, tint=((0.55, 0.13, 0.09), 0.85),
                               rough=(0.8, 0.14), nrm=0.7), var=0.10),
    "Yard_Hard": dict(base=dict(slot="asphalt_worn", sat=0.5, val=1.5, rough=(0.8, 0.15), nrm=0.9), var=0.15),
    "Sidewalk_Paving": dict(base=dict(slot="paving", nrm=1.0), var=0.10),
    "Path_Paving": dict(base=dict(slot="paving", sat=0.9, val=0.96, nrm=1.0), var=0.12),
    "Entrance_Paving": dict(base=dict(slot="paving", val=1.02, tint=((0.62, 0.40, 0.30), 0.40), nrm=1.0), var=0.08),
    "Forecourt_Paving": dict(base=dict(slot="paving_large", val=1.55, tint=((0.80, 0.72, 0.58), 0.45), nrm=0.9), var=0.08),
    "Curb": dict(base=dict(slot="concrete", val=3.3, rough=(0.6, 0.38), nrm=0.6), var=0.08),
    "Apron_Concrete": dict(base=dict(slot="concrete", val=3.0, rough=(0.6, 0.38), nrm=0.6), var=0.12),
    "Aryk": dict(base=dict(slot="concrete", val=2.3, sat=1.2, rough=(0.6, 0.30), nrm=0.8), var=0.15),
    "Channel_Bank": dict(base=dict(slot="concrete", val=2.6, rough=(0.6, 0.38), nrm=0.7), var=0.12,
                         joints=(1.0, 1.0, 0.012, 0.45)),
    "Bare_Soil": dict(base=dict(slot="soil", rough=(0.4, 0.58), nrm=1.0), var=0.15),
    "Dirt_Track": dict(base=dict(slot="soil", val=1.1, rough=(0.4, 0.58), nrm=1.0), var=0.12,
                       mix=(dict(slot="gravel", val=0.8, sat=1.3, rough=(0.5, 0.45), nrm=1.0), 0.35, 3.0)),
    "Private_Plot": dict(base=dict(slot="soil", val=0.95, rough=(0.4, 0.58), nrm=1.0), var=0.12,
                         mix=(dict(GRASS_LAWN, val=0.55, tint=((0.24, 0.34, 0.09), 0.6)), 0.5, 6.0)),
    "Lawn": dict(base=GRASS_LAWN, var=0.14),
    "Street_Green": dict(base=dict(slot="dry_grass", hue=0.53, sat=0.85, val=1.5,
                                   tint=((0.40, 0.42, 0.16), 0.45), rough=(0.8, 0.18), nrm=0.8), var=0.14),
    "Trees_Ground": dict(base=dict(slot="dry_grass", hue=0.52, sat=0.8, val=1.2,
                                   tint=((0.36, 0.36, 0.15), 0.35), rough=(0.8, 0.18), nrm=0.8), var=0.14,
                         mix=(dict(slot="soil", val=0.7, rough=(0.4, 0.58), nrm=1.0), 0.40, 4.0)),
    "Playground": dict(base=dict(slot="rubber", val=1.1, tint=((0.62, 0.22, 0.12), 0.35), rough=(1.0, 0.0), nrm=0.6), var=0.06),
    "Sport_Pitch": dict(proc="turf", var=0.06),
}

# stochastic surfaces get a 2-sample anti-tiling blend; regular patterns (pavers) do not
ANTITILE = {"asphalt", "asphalt_worn", "concrete", "soil", "gravel", "grass", "dry_grass", "rubber"}

# procedural fallbacks when a slot has no textures: (colour1, colour2, noise scale, roughness)
FALLBACK = {
    "asphalt": ((0.03, 0.03, 0.034), (0.085, 0.085, 0.09), 6.0, 0.82),
    "asphalt_worn": ((0.10, 0.10, 0.10), (0.22, 0.22, 0.21), 3.0, 0.85),
    "paving": ((0.30, 0.28, 0.25), (0.40, 0.38, 0.35), 10.0, 0.8),
    "paving_large": ((0.40, 0.38, 0.34), (0.50, 0.48, 0.44), 4.0, 0.8),
    "concrete": ((0.40, 0.40, 0.38), (0.58, 0.57, 0.54), 8.0, 0.8),
    "soil": ((0.18, 0.12, 0.07), (0.30, 0.22, 0.13), 3.0, 0.92),
    "gravel": ((0.30, 0.28, 0.24), (0.45, 0.42, 0.37), 20.0, 0.9),
    "grass": ((0.05, 0.13, 0.03), (0.12, 0.24, 0.05), 2.0, 0.9),
    "dry_grass": ((0.12, 0.12, 0.05), (0.24, 0.24, 0.10), 2.0, 0.92),
    "rubber": ((0.35, 0.09, 0.05), (0.50, 0.15, 0.08), 8.0, 0.9),
}


# ----------------------------------------------------------------------------- helpers
def _pbr_dir(root):
    return os.path.join(root, *PBR_SUB)


def load_manifest(root):
    p = os.path.join(_pbr_dir(root), "manifest.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _image(root, rel, non_color):
    if not rel:
        return None
    path = os.path.normpath(os.path.join(_pbr_dir(root), *rel.replace("\\", "/").split("/")))
    if not os.path.exists(path):
        return None
    im = bpy.data.images.load(path, check_existing=True)
    want = "Non-Color" if non_color else "sRGB"
    if im.colorspace_settings.name != want:
        im.colorspace_settings.name = want
    if bpy.data.filepath and not im.filepath.startswith("//"):
        try:
            im.filepath = bpy.path.relpath(path)   # portable: //textures/pbr/...
        except ValueError:                          # other drive
            pass
    return im


def _sock(sockets, ident):
    for s in sockets:
        if s.identifier == ident:
            return s
    return sockets[ident]


def _mix(nt, kind, fac, a, b, loc, blend="MIX"):
    """kind: FLOAT / RGBA. fac/a/b: socket or constant."""
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = kind
    if kind == "RGBA":
        m.blend_type = blend
    m.location = loc
    suf = "Float" if kind == "FLOAT" else "Color"
    for ident, v in (("Factor_Float", fac), ("A_" + suf, a), ("B_" + suf, b)):
        s = _sock(m.inputs, ident)
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, s)
        else:
            s.default_value = v if kind == "FLOAT" or ident.startswith("Factor") else (*v[:3], 1.0)
    return _sock(m.outputs, "Result_" + suf)


def _math(nt, op, a, b=None, loc=(0, 0), clamp=False, c=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    n.location = loc
    for i, v in enumerate((a, b, c)):
        if v is None:
            continue
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, n.inputs[i])
        else:
            n.inputs[i].default_value = v
    return n.outputs[0]


def _noise(nt, vec, scale, detail, loc, rough=0.5):
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = loc
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    nt.links.new(vec, n.inputs["Vector"])
    return n.outputs["Fac"]


def _maprange(nt, val, f0, f1, t0, t1, loc, smooth=True):
    n = nt.nodes.new("ShaderNodeMapRange")
    n.location = loc
    n.interpolation_type = "SMOOTHSTEP" if smooth else "LINEAR"
    n.clamp = True
    nt.links.new(val, n.inputs["Value"])
    n.inputs["From Min"].default_value = f0
    n.inputs["From Max"].default_value = f1
    n.inputs["To Min"].default_value = t0
    n.inputs["To Max"].default_value = t1
    return n.outputs["Result"]


# ----------------------------------------------------------------------------- slot node groups
def _slot_group(root, slot, entry, log):
    """Node group PBR07b_<slot>: UV (world m) -> Color, Roughness, Normal (tangent-space colour)."""
    name = "PBR07b_" + slot
    ng = bpy.data.node_groups.get((name, None))
    if ng is None:
        ng = bpy.data.node_groups.new(name, "ShaderNodeTree")
    if not ng.interface.items_tree:
        ng.interface.new_socket("UV", in_out="INPUT", socket_type="NodeSocketVector")
        ng.interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        s = ng.interface.new_socket("Roughness", in_out="OUTPUT", socket_type="NodeSocketFloat")
        s.default_value = 0.8
        s = ng.interface.new_socket("Normal", in_out="OUTPUT", socket_type="NodeSocketColor")
        s.default_value = (0.5, 0.5, 1.0, 1.0)
    nt = ng
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    gi = nt.nodes.new("NodeGroupInput"); gi.location = (-1400, 0)
    go = nt.nodes.new("NodeGroupOutput"); go.location = (400, 0)
    uv = gi.outputs["UV"]

    imgs = {}
    if entry:
        imgs = {"diffuse": _image(root, entry.get("diffuse"), False),
                "rough": _image(root, entry.get("rough"), True),
                "normal": _image(root, entry.get("normal"), True)}
    if not imgs.get("diffuse"):
        c1, c2, sc, r = FALLBACK.get(slot, ((0.2, 0.2, 0.2), (0.3, 0.3, 0.3), 5.0, 0.8))
        f = _noise(nt, uv, sc, 6.0, (-900, 100))
        ramp = nt.nodes.new("ShaderNodeValToRGB"); ramp.location = (-600, 100)
        ramp.color_ramp.elements[0].color = (*c1, 1); ramp.color_ramp.elements[1].color = (*c2, 1)
        nt.links.new(f, ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], go.inputs["Color"])
        go.inputs["Roughness"].default_value = r
        go.inputs["Normal"].default_value = (0.5, 0.5, 1.0, 1.0)
        ng[MARK] = "fallback"
        log("[07b] slot %s: no textures -> procedural fallback" % slot)
        return ng

    sx, sy = (entry.get("size_m") or [2.0, 2.0])[:2]
    vm = nt.nodes.new("ShaderNodeVectorMath"); vm.operation = "MULTIPLY"; vm.location = (-1150, 150)
    nt.links.new(uv, vm.inputs[0]); vm.inputs[1].default_value = (1.0 / sx, 1.0 / sy, 1.0)
    uvs = [vm.outputs[0]]
    mask = None
    if slot in ANTITILE:
        rot = nt.nodes.new("ShaderNodeVectorRotate"); rot.rotation_type = "Z_AXIS"; rot.location = (-1150, -100)
        rot.inputs["Angle"].default_value = 0.93
        nt.links.new(uv, rot.inputs["Vector"])
        vb = nt.nodes.new("ShaderNodeVectorMath"); vb.operation = "MULTIPLY_ADD"; vb.location = (-950, -100)
        nt.links.new(rot.outputs[0], vb.inputs[0])
        vb.inputs[1].default_value = (0.87 / sx, 0.87 / sy, 1.0)
        vb.inputs[2].default_value = (0.37, 0.61, 0.0)
        uvs.append(vb.outputs[0])
        mask = _maprange(nt, _noise(nt, uv, 0.07, 2.0, (-950, -350)), 0.44, 0.56, 0.0, 1.0, (-750, -350))

    out = {}
    y = 300
    for key, kind in (("diffuse", "RGBA"), ("rough", "FLOAT"), ("normal", "RGBA")):
        im = imgs.get(key)
        if im is None:
            out[key] = None
            continue
        samples = []
        for j, v in enumerate(uvs):
            t = nt.nodes.new("ShaderNodeTexImage"); t.location = (-700 + 260 * j, y)
            t.image = im; t.interpolation = "Linear"; t.extension = "REPEAT"
            t.label = "%s %s" % (slot, key)
            nt.links.new(v, t.inputs["Vector"])
            samples.append(t.outputs["Color"])
        if len(samples) == 1:
            out[key] = samples[0]
        else:
            out[key] = _mix(nt, kind if kind == "RGBA" else "FLOAT", mask, samples[0], samples[1], (-150, y))
        y -= 300
    nt.links.new(out["diffuse"], go.inputs["Color"])
    if out["rough"] is not None:
        nt.links.new(out["rough"], go.inputs["Roughness"])
    else:
        go.inputs["Roughness"].default_value = 0.8
    if out["normal"] is not None:
        nt.links.new(out["normal"], go.inputs["Normal"])
    else:
        go.inputs["Normal"].default_value = (0.5, 0.5, 1.0, 1.0)
    ng[MARK] = "%s %s %s" % (VERSION, entry.get("id"), "x".join(str(s) for s in (sx, sy)))
    return ng


# ----------------------------------------------------------------------------- material building
def _layer(nt, groups, uv, L, x, y):
    """Graded texture layer -> (color, roughness, normal colour, normal strength)."""
    g = nt.nodes.new("ShaderNodeGroup"); g.node_tree = groups[L["slot"]]; g.location = (x, y)
    g.label = L["slot"]
    nt.links.new(uv, g.inputs["UV"])
    col = g.outputs["Color"]
    if L.get("hue", 0.5) != 0.5 or L.get("sat", 1.0) != 1.0 or L.get("val", 1.0) != 1.0:
        h = nt.nodes.new("ShaderNodeHueSaturation"); h.location = (x + 220, y + 60)
        h.inputs["Hue"].default_value = L.get("hue", 0.5)
        h.inputs["Saturation"].default_value = L.get("sat", 1.0)
        h.inputs["Value"].default_value = L.get("val", 1.0)
        nt.links.new(col, h.inputs["Color"])
        col = h.outputs["Color"]
    if L.get("tint"):
        tc, tf = L["tint"]
        col = _mix(nt, "RGBA", tf, col, _lin(tc), (x + 420, y + 60), blend="COLOR")
    rm, ra = L.get("rough", (1.0, 0.0))
    rough = g.outputs["Roughness"]
    if (rm, ra) != (1.0, 0.0):
        rough = _math(nt, "MULTIPLY_ADD", rough, rm, (x + 220, y - 120), clamp=True, c=ra)
    return col, rough, g.outputs["Normal"], L.get("nrm", 0.8)


def _stripe_source(mat):
    """Existing stripe mask socket + paint colour; prunes the tree to the mask subgraph."""
    nt = mat.node_tree
    src, paint = None, None
    rr = nt.nodes.get(STRIPE_NODE)
    first = True
    if rr is not None and rr.inputs[0].is_linked:
        src = rr.inputs[0].links[0].from_socket
        paint = tuple(mat.get("pbr07b_paint", (0.78, 0.78, 0.75)))
        first = False
    else:
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is not None and bsdf.inputs["Base Color"].is_linked:
            mix = bsdf.inputs["Base Color"].links[0].from_node
            if mix.type == "MIX":
                f = _sock(mix.inputs, "Factor_Float")
                if f.is_linked:
                    src = f.links[0].from_socket
                    b = _sock(mix.inputs, "B_Color")
                    paint = tuple(b.default_value)[:3]
    if src is None:
        return None, None
    keep, stack = set(), [src.node]
    while stack:
        n = stack.pop()
        if n.name in keep:
            continue
        keep.add(n.name)
        for i in n.inputs:
            for l in i.links:
                stack.append(l.from_node)
    for n in list(nt.nodes):
        if n.name not in keep:
            nt.nodes.remove(n)
    if first:  # move the kept stripe subgraph out of the way (once)
        for n in nt.nodes:
            n.location = (n.location[0] - 1400, n.location[1] + 900)
    return src, paint


def _turf(nt, uv, x, y):
    """Procedural artificial turf: two greens, 5 m mowing bands, fine fibre bump."""
    f = _noise(nt, uv, 0.6, 4.0, (x, y + 200))
    ramp = nt.nodes.new("ShaderNodeValToRGB"); ramp.location = (x + 200, y + 200)
    ramp.color_ramp.elements[0].color = (0.035, 0.20, 0.045, 1)
    ramp.color_ramp.elements[1].color = (0.060, 0.28, 0.060, 1)
    nt.links.new(f, ramp.inputs["Fac"])
    sep = nt.nodes.new("ShaderNodeSeparateXYZ"); sep.location = (x, y - 50)
    nt.links.new(uv, sep.inputs[0])
    band = _math(nt, "PINGPONG", sep.outputs["X"], 5.0, (x + 200, y - 50))
    band = _math(nt, "GREATER_THAN", band, 2.5, (x + 380, y - 50))
    band = _math(nt, "MULTIPLY_ADD", band, 0.12, (x + 540, y - 50), c=0.94)
    col = _mix(nt, "RGBA", 1.0, ramp.outputs["Color"], band, (x + 700, y + 100), blend="MULTIPLY")
    fine = _noise(nt, uv, 180.0, 2.0, (x + 200, y - 300))
    bump = nt.nodes.new("ShaderNodeBump"); bump.location = (x + 700, y - 300)
    bump.inputs["Strength"].default_value = 0.35
    nt.links.new(fine, bump.inputs["Height"])
    return col, 0.72, bump.outputs["Normal"]


def _build(mat, cat, R, groups, log):
    mat.use_nodes = True
    nt = mat.node_tree
    src, paint = (None, None)
    if R.get("stripes"):
        src, paint = _stripe_source(mat)
        if src is None:
            log("[07b] %s: no stripe mask found, plain asphalt" % mat.name)
    if src is None:
        for n in list(nt.nodes):
            nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (1500, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (1150, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.location = (-1500, 0); uvn.uv_map = UVMAP
    uv = uvn.outputs["UV"]

    bump_normal = None
    if R.get("proc") == "turf":
        col, rough, bump_normal = _turf(nt, uv, -1100, 0)
        nrm_col, nrm_s = None, 0.0
    else:
        col, rough, nrm_col, nrm_s = _layer(nt, groups, uv, R["base"], -1100, 0)
        if R.get("mix"):
            L2, cov, size = R["mix"]
            c2, r2, n2, s2 = _layer(nt, groups, uv, L2, -1100, -700)
            t = 0.5 + (0.5 - cov) * 0.25
            m = _maprange(nt, _noise(nt, uv, 1.0 / size, 6.0, (-700, -1100), 0.6), t - 0.04, t + 0.04, 0.0, 1.0, (-500, -1100))
            col = _mix(nt, "RGBA", m, col, c2, (-150, 150))
            rough = _mix(nt, "FLOAT", m, rough, r2, (-150, -100))
            nrm_col = _mix(nt, "RGBA", m, nrm_col, n2, (-150, -300))
            nrm_s = (nrm_s + s2) * 0.5

    if R.get("joints"):
        w, h, mortar, dark = R["joints"]
        br = nt.nodes.new("ShaderNodeTexBrick"); br.location = (-500, 500)
        br.offset = 0.0
        br.inputs["Scale"].default_value = 1.0
        br.inputs["Brick Width"].default_value = w
        br.inputs["Row Height"].default_value = h
        br.inputs["Mortar Size"].default_value = mortar
        br.inputs["Mortar Smooth"].default_value = 0.3
        nt.links.new(uv, br.inputs["Vector"])
        col = _mix(nt, "RGBA", br.outputs["Fac"], col, _mix(nt, "RGBA", 1.0 - dark, (0, 0, 0), col, (-150, 500)),
                   (0, 400))

    # large-scale value variation so big areas do not tile visibly
    v = R.get("var", 0.1)
    if v > 0:
        n1 = _noise(nt, uv, 0.03, 3.0, (-300, 800))
        n2 = _noise(nt, uv, 0.17, 2.0, (-300, 600))
        avg = _math(nt, "MULTIPLY_ADD", n1, 0.6, (-100, 700), c=0.0)
        avg = _math(nt, "MULTIPLY_ADD", n2, 0.4, (50, 700), c=avg)
        k = _maprange(nt, avg, 0.3, 0.7, 1.0 - v, 1.0 + v, (200, 700), smooth=False)
        col = _mix(nt, "RGBA", 1.0, col, k, (400, 300), blend="MULTIPLY")

    # paint on top: kept stripe mask (crosswalk / parking bays) or road-marking polygons
    pmask = None
    if src is not None:
        rr = nt.nodes.get(STRIPE_NODE)
        if rr is None:
            rr = nt.nodes.new("NodeReroute"); rr.name = STRIPE_NODE; rr.label = "stripe mask (xw_angle)"
            nt.links.new(src, rr.inputs[0])
        rr.location = (100, 1100)
        pmask = rr.outputs[0]
        mat["pbr07b_paint"] = list(paint or (0.78, 0.78, 0.75))
        pcol = tuple(paint or (0.78, 0.78, 0.75))
    elif R.get("paint"):
        wear = _noise(nt, uv, 2.5, 8.0, (-300, 1100))
        pmask = _math(nt, "LESS_THAN", wear, 0.66, (-100, 1100))
        pcol = (0.72, 0.72, 0.69)
    if pmask is not None:
        col = _mix(nt, "RGBA", pmask, col, pcol, (700, 300))
        rough = _mix(nt, "FLOAT", pmask, rough, 0.55, (700, 0))
        nrm_s_sock = _math(nt, "MULTIPLY_ADD", pmask, -0.7 * nrm_s, (700, -250), c=nrm_s)
    else:
        nrm_s_sock = None

    nt.links.new(col, bsdf.inputs["Base Color"])
    if isinstance(rough, bpy.types.NodeSocket):
        nt.links.new(rough, bsdf.inputs["Roughness"])
    else:
        bsdf.inputs["Roughness"].default_value = rough
    if bump_normal is not None:
        nt.links.new(bump_normal, bsdf.inputs["Normal"])
    elif nrm_col is not None:
        nm = nt.nodes.new("ShaderNodeNormalMap"); nm.location = (900, -300)
        nm.space = "TANGENT"; nm.uv_map = UVMAP
        nt.links.new(nrm_col, nm.inputs["Color"])
        if nrm_s_sock is not None:
            nt.links.new(nrm_s_sock, nm.inputs["Strength"])
        else:
            nm.inputs["Strength"].default_value = nrm_s
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])

    if cat in VIEW:
        mat.diffuse_color = (*_lin(VIEW[cat]), 1.0)
    mat.roughness = 0.8
    mat.metallic = 0.0
    mat[MARK] = "%s %s" % (VERSION, R.get("proc") or R["base"]["slot"] +
                           ("+" + R["mix"][0]["slot"] if R.get("mix") else ""))


# ----------------------------------------------------------------------------- public API
def upgrade_materials(M, root, log=print):
    """M: {category: material}. Rebuilds each known category's material in place. Returns {category: recipe}."""
    man = load_manifest(root)
    if not man:
        log("[07b] WARNING: no manifest at %s - procedural fallbacks only" % os.path.join(_pbr_dir(root), "manifest.json"))
    need = set()
    for cat, R in RECIPES.items():
        if cat in M and not R.get("proc"):
            need.add(R["base"]["slot"])
            if R.get("mix"):
                need.add(R["mix"][0]["slot"])
    groups = {s: _slot_group(root, s, man.get(s), log) for s in sorted(need)}
    done = {}
    for cat, mat in M.items():
        if mat is None or cat in SKIP or cat not in RECIPES:
            continue
        R = RECIPES[cat]
        _build(mat, cat, R, groups, log)
        done[cat] = mat[MARK]
    for cat in sorted(done):
        log("[07b] %-17s %-28s %s" % (cat, M[cat].name, done[cat]))
    missing = [c for c in RECIPES if c not in M]
    if missing:
        log("[07b] categories not in scene:", ", ".join(missing))
    return done


def apply_to_open_scene(root=None, log=print):
    """Upgrade the materials of the GROUND_<Category> objects in the current scene."""
    root = root or os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
    M = {}
    for o in bpy.context.scene.objects:
        if o.type != "MESH" or not o.name.startswith("GROUND_"):
            continue
        cat = o.name[len("GROUND_"):].split(".")[0]
        mats = [s.material for s in o.material_slots if s.material]
        if mats and cat not in M:
            M[cat] = mats[0]
    return upgrade_materials(M, root, log)


if __name__ == "__main__":
    apply_to_open_scene()
