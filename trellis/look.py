"""GLB 하나를 불러와 정면·35°·옆·뒤 4면을 한 장으로 렌더한다.
  Blender --background --python trellis/look.py -- IN.glb OUT.png
"""
import math, subprocess, sys
from pathlib import Path
import bpy
from mathutils import Vector

a = sys.argv[sys.argv.index('--') + 1:]
src, out = a[0], Path(a[1]).resolve()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
# --rotx DEG: 축이 다른 GLB 를 세운다. --gray: 텍스처 대신 회색으로 모양만 본다
if '--rotx' in a:
    for o in objs:
        o.rotation_mode = 'XYZ'  # glTF 임포터는 쿼터니언 모드라 오일러를 바꾸려면 모드부터 바꾼다
        o.rotation_euler.x += math.radians(float(a[a.index('--rotx') + 1]))
    bpy.context.view_layer.update()
if '--twosided' in a:
    for o in objs:
        for m in o.data.materials:
            m.use_backface_culling = False
if '--gray' in a:
    g = bpy.data.materials.new('gray')
    for o in objs:
        o.data.materials.clear(); o.data.materials.append(g)
        for p in o.data.polygons: p.use_smooth = True
lo = Vector((1e9,) * 3); hi = Vector((-1e9,) * 3)
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
ctr, size = (lo + hi) / 2, hi - lo
print('[look] bbox size', tuple(round(v, 3) for v in size), 'tris', sum(len(o.data.polygons) for o in objs))
sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x = sc.render.resolution_y = 720
sc.view_settings.view_transform = 'Standard'
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
w.node_tree.nodes['Background'].inputs[1].default_value = 0.55
sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sun.data.energy = 3.5
sun.rotation_euler = (math.radians(50), 0, math.radians(-35)); sc.collection.objects.link(sun)
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
cam.data.lens = 85
d = max(size) * 3.2
parts = []
for i, az in enumerate([0, 35, 90, 180]):
    t = math.radians(az)
    cam.location = ctr + Vector((math.sin(t) * d, -math.cos(t) * d, size.z * 0.05))
    cam.rotation_euler = (ctr - cam.location).to_track_quat('-Z', 'Y').to_euler()
    p = out.with_name(f'{out.stem}-{az}.png'); sc.render.filepath = str(p)
    bpy.ops.render.render(write_still=True); parts.append(str(p))
subprocess.run(['ffmpeg', '-v', 'error', '-y', *sum([['-i', p] for p in parts], []), '-filter_complex', 'hstack=inputs=4', str(out)], check=True)
print('[look] wrote', out)
