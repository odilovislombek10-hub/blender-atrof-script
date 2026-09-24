import bpy, math, os, sys, mathutils
ROOT = os.environ["BISHKEK_ROOT"]; OUT = os.path.join(ROOT, "qa"); os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=os.environ["BISHKEK_BLEND"])
sc = bpy.context.scene
eng = os.environ.get("ENGINE", "CYCLES")
try:
    sc.render.engine = eng
except TypeError:
    sc.render.engine = "BLENDER_EEVEE_NEXT"
if sc.render.engine == "CYCLES":
    sc.cycles.device = "CPU"; sc.cycles.samples = int(os.environ.get("SAMPLES", "12")); sc.cycles.use_denoising = False
    sc.cycles.max_bounces = 2
sc.render.resolution_x = int(os.environ.get("RX", "1000")); sc.render.resolution_y = int(os.environ.get("RY", "625"))
w = sc.world or bpy.data.worlds.new("W"); sc.world = w; w.use_nodes = True
bg = w.node_tree.nodes.get("Background"); bg.inputs[0].default_value = (0.55, 0.7, 0.95, 1); bg.inputs[1].default_value = 0.6
sun = bpy.data.lights.new("QA_Sun", "SUN"); sun.energy = 4.0; so = bpy.data.objects.new("QA_Sun", sun); sc.collection.objects.link(so)
so.rotation_euler = (math.radians(40), math.radians(10), math.radians(210))
for o in bpy.data.objects:
    if o.name.startswith("Ring_") or o.name.startswith("CAM_"): o.hide_render = True
def look(name, loc, target, lens=35, ortho=None):
    cd = bpy.data.cameras.new(name); cd.clip_start = 0.5; cd.clip_end = 100000
    if ortho: cd.type = "ORTHO"; cd.ortho_scale = ortho
    else: cd.lens = lens
    co = bpy.data.objects.new(name, cd); sc.collection.objects.link(co)
    co.location = loc
    d = mathutils.Vector(target) - mathutils.Vector(loc)
    co.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return co
Z = 815.0
shots = [(os.environ.get("SHOT","all"))]
cams = {
 "A_top_220m": look("QA_A", (0, 0, Z + 400), (0, 0, Z), ortho=220),
 "B_street_Toktonalieva": look("QA_B", (22, -60, Z + 7), (15, 30, Z + 1), lens=24),
 "C_oblique_600m": look("QA_C", (350, -420, Z + 260), (0, 0, Z), lens=35),
 "D_yards_east": look("QA_D", (60, 120, Z + 35), (180, 40, Z), lens=28),
}
sel = os.environ.get("SHOTS", ",".join(cams)).split(",")
for name in sel:
    sc.camera = cams[name]
    sc.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)
    print("rendered", name, flush=True)
