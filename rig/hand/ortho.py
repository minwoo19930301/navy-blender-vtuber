"""손 GLB 를 세워서 직교 렌더 한 장을 만든다. 보는 방향은 front(-Y→+Y)·side(+X→-X)·top(+Z→-Z).

  Blender --background --python rig/hand/ortho.py -- IN.glb OUT.png RES VIEW [--gray]
  OUT.json: {res, view, ortho_scale, center, cam_origin, right, up, fwd}  (Blender 좌표, 모델 = GLB 를 X축 -90° 세운 것)
"""
import json, math, sys
from pathlib import Path
import bpy
from mathutils import Vector

a = sys.argv[sys.argv.index('--') + 1:]
src, out, res, view = a[0], Path(a[1]).resolve(), int(a[2]), a[3]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
for o in objs:
    o.rotation_mode = 'XYZ'
    o.rotation_euler.x += math.radians(-90)  # front_ortho.py 와 같은 변환
    for m in o.data.materials:
        m.use_backface_culling = False
if '--gray' in a:
    g = bpy.data.materials.new('gray')
    for o in objs:
        o.data.materials.clear(); o.data.materials.append(g)
        for p in o.data.polygons: p.use_smooth = True
bpy.context.view_layer.update()
lo = Vector((1e9,) * 3); hi = Vector((-1e9,) * 3)
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
ctr = (lo + hi) / 2
scale = max(hi - lo) * 1.1
sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x = sc.render.resolution_y = res
sc.view_settings.view_transform = 'Standard'
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
w.node_tree.nodes['Background'].inputs[1].default_value = 1.0
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = scale
R = 10
# 월드광만으로는 면 구분이 안 돼 MediaPipe 가 못 찾는다 → 카메라 쪽 위에서 햇빛 + 월드광은 약하게
w.node_tree.nodes['Background'].inputs[1].default_value = 0.6
for o in objs:
    for p in o.data.polygons: p.use_smooth = True
ld = bpy.data.lights.new('sun', 'SUN'); ld.energy = 3.0
lo_ = bpy.data.objects.new('sun', ld); sc.collection.objects.link(lo_)
lo_.rotation_euler = (math.radians(50), 0, math.radians(35)) if view == 'front' else (math.radians(50), 0, math.radians(125))
if view == 'front':
    cam.location = ctr + Vector((0, -R, 0)); cam.rotation_euler = (math.radians(90), 0, 0)
elif view == 'side':
    cam.location = ctr + Vector((R, 0, 0)); cam.rotation_euler = (math.radians(90), 0, math.radians(90))
elif view == 'top':
    cam.location = ctr + Vector((0, 0, R)); cam.rotation_euler = (0, 0, 0)
bpy.context.view_layer.update()
M = cam.matrix_world.to_3x3()
right, up, fwd = M @ Vector((1, 0, 0)), M @ Vector((0, 1, 0)), M @ Vector((0, 0, -1))
sc.render.filepath = str(out)
bpy.ops.render.render(write_still=True)
json.dump({'res': res, 'view': view, 'ortho_scale': scale, 'center': list(ctr), 'right': list(right), 'up': list(up), 'fwd': list(fwd),
           'bbox_lo': list(lo), 'bbox_hi': list(hi)}, open(out.with_suffix('.json'), 'w'), indent=1)
print('[hand ortho] wrote', out)
