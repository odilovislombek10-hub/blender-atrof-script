"""Assign the painted Sentinel-2 terrain textures to the terrain tiles (run with blender -b)."""
import os, sys, json, math
import bpy
import numpy as np
ROOT = os.environ.get("BISHKEK_ROOT", r"D:\Bishkek_35km")
TILE = 5000.0
SRC = os.environ.get("BISHKEK_BLEND", os.path.join(ROOT, "Bishkek_35km.blend"))
OUT = os.environ.get("BISHKEK_OUT", SRC)  # single working file, updated in place
bpy.ops.wm.open_mainfile(filepath=SRC)
meta = json.load(open(os.path.join(ROOT, "textures", "terrain", "tiles.json")))


def terrain_mat(name, img_path):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (700, 0)
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled"); bs.location = (400, 0)
    bs.inputs["Roughness"].default_value = 0.92
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.location = (-400, 0)
    img = bpy.data.images.load(img_path, check_existing=True)
    tex.image = img; tex.interpolation = "Cubic"; tex.extension = "EXTEND"
    uv = nt.nodes.new("ShaderNodeUVMap"); uv.location = (-600, 0); uv.uv_map = "UVMap"
    bc = nt.nodes.new("ShaderNodeBrightContrast"); bc.location = (-100, 0); bc.label = "Terrain Brightness/Contrast"
    hs = nt.nodes.new("ShaderNodeHueSaturation"); hs.location = (150, 0); hs.label = "Terrain Hue/Sat"
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], bc.inputs["Color"])
    nt.links.new(bc.outputs["Color"], hs.inputs["Color"])
    nt.links.new(hs.outputs["Color"], bs.inputs["Base Color"])
    nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"])
    return m


n = 0
for o in bpy.data.objects:
    if o.type != "MESH" or not o.name.startswith("Terrain_"):
        continue
    ix, iy = (int(v) for v in o.name.split("_")[1:3])
    t = meta.get(f"{ix},{iy}")
    if not t:
        continue
    me = o.data
    x0, y0 = ix * TILE, iy * TILE
    uvl = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    nl = len(me.loops)
    vi = np.empty(nl, np.int32); me.loops.foreach_get("vertex_index", vi)
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    uv = np.stack([(co[vi, 0] - x0) / TILE, (co[vi, 1] - y0) / TILE], 1).astype(np.float32)
    uvl.data.foreach_set("uv", uv.ravel())
    mat = terrain_mat(f"T_Terrain_{ix:+03d}_{iy:+03d}", "//textures/terrain/" + t["file"])
    me.materials.clear(); me.materials.append(mat)
    n += 1
print("[tex] terrain tiles textured", n, flush=True)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True, relative_remap=True)
print("[tex] SAVED", OUT, flush=True)
