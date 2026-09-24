import bpy, math, os, sys
ROOT = r"D:\Bishkek_35km"
OUT = os.path.join(ROOT, "previews"); os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=os.path.join(ROOT, "Bishkek_35km.blend"))
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sh = sc.display.shading
sh.light = "STUDIO"; sh.color_type = "MATERIAL"; sh.show_shadows = True; sh.show_cavity = True
sc.display.shadow_focus = 0.2
sc.render.resolution_x = 1600; sc.render.resolution_y = 1000; sc.render.resolution_percentage = 100
sc.render.film_transparent = False
sc.world = sc.world or bpy.data.worlds.new("W")
sc.world.color = (0.55, 0.65, 0.8)
for o in bpy.data.objects:
    if o.name.startswith("Ring_"): o.hide_render = True
def cam(name, loc, rot, ortho=None, lens=35, clip=250000):
    cd = bpy.data.cameras.new(name); cd.clip_start = 1; cd.clip_end = clip
    if ortho: cd.type = "ORTHO"; cd.ortho_scale = ortho
    else: cd.lens = lens
    co = bpy.data.objects.new(name, cd); sc.collection.objects.link(co)
    co.location = loc; co.rotation_euler = rot
    return co
Z = 815
shots = [
  ("01_site_top_600m", (0, 0, Z + 800), (0, 0, 0), 600),
  ("02_site_top_2km", (0, 0, Z + 1500), (0, 0, 0), 2000),
  ("03_city_top_12km", (0, 0, Z + 5000), (0, 0, 0), 12000),
  ("04_full_top_72km", (0, 0, Z + 20000), (0, 0, 0), 72000),
  ("05_persp_site_from_NE", (260, 330, Z + 180), (math.radians(62), 0, math.radians(142)), None),
  ("06_persp_city_to_mountains", (0, 6000, Z + 900), (math.radians(80), 0, math.radians(180)), None),
]
for name, loc, rot, ortho in shots:
    c = cam("CAM_" + name, loc, rot, ortho)
    sc.camera = c
    sc.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)
    print("rendered", name, flush=True)
# keep cameras in the file for the user
bpy.ops.wm.save_mainfile()
print("PREVIEWS DONE", flush=True)
