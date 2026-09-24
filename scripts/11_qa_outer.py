import bpy, math, os, mathutils
ROOT = r"D:\Bishkek_35km"; OUT = os.path.join(ROOT, "qa"); os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=os.path.join(ROOT, "Bishkek_35km_v3.blend"))
sc = bpy.context.scene
try:
    sc.render.engine = "BLENDER_EEVEE"
except TypeError:
    sc.render.engine = "BLENDER_EEVEE_NEXT"
sc.render.resolution_x = 1600; sc.render.resolution_y = 900
w = sc.world or bpy.data.worlds.new("W"); sc.world = w; w.use_nodes = True
bg = w.node_tree.nodes.get("Background"); bg.inputs[0].default_value = (0.55, 0.7, 0.95, 1); bg.inputs[1].default_value = 0.7
sun = bpy.data.lights.new("QA_Sun", "SUN"); sun.energy = 4.0; so = bpy.data.objects.new("QA_Sun", sun); sc.collection.objects.link(so)
so.rotation_euler = (math.radians(45), math.radians(10), math.radians(200))
for o in bpy.data.objects:
    if o.name.startswith("Ring_") or o.name.startswith("CAM_") or o.name.startswith("SITE_"): o.hide_render = True
def look(name, loc, target, lens=35):
    cd = bpy.data.cameras.new(name); cd.clip_start = 1; cd.clip_end = 200000; cd.lens = lens
    co = bpy.data.objects.new(name, cd); sc.collection.objects.link(co); co.location = loc
    co.rotation_euler = (mathutils.Vector(target) - mathutils.Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return co
Z = 815.0
cams = {"E_city_to_mountains": look("QA_E", (1500, 9000, Z + 700), (0, -6000, Z + 300), 30),
        "F_oblique_3km": look("QA_F", (-1800, 2200, Z + 900), (300, -300, Z), 35),
        "G_zone_edge_1200m": look("QA_G", (900, 1300, Z + 180), (300, 350, Z), 35)}
for n, c in cams.items():
    sc.camera = c; sc.render.filepath = os.path.join(OUT, n + ".png")
    bpy.ops.render.render(write_still=True); print("rendered", n, flush=True)
