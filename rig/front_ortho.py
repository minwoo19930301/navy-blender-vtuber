"""TRELLIS GLB 를 세워서 정면 직교 렌더를 만든다. 픽셀 ↔ 모델 좌표 변환값을 json 으로 남긴다.

  Blender --background --python rig/front_ortho.py -- IN.glb OUT.png [RES]
  Blender --background --python rig/front_ortho.py -- IN.glb OUT.png RES CX CZ SCALE   (부분 확대: 중심·폭을 모델 좌표로)
  OUT.json: {res, ortho_scale, cx, cz}  (Blender 좌표: x 오른쪽, z 위. 정면 카메라는 -Y 에서 +Y 를 본다)
"""
import json, math, sys
from pathlib import Path
import bpy
from mathutils import Vector

a = sys.argv[sys.argv.index('--') + 1:]
src, out = a[0], Path(a[1]).resolve()
res = int(a[2]) if len(a) > 2 else 1024
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
for o in objs:
    o.rotation_mode = 'XYZ'
    o.rotation_euler.x += math.radians(float(__import__('os').environ.get('ROTX', '-90')))  # TRELLIS(로컬) GLB 는 눕혀서 나온다. Space GLB 는 ROTX=0
    for m in o.data.materials:
        m.use_backface_culling = False
bpy.context.view_layer.update()
lo = Vector((1e9,) * 3); hi = Vector((-1e9,) * 3)
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
ctr = (lo + hi) / 2
scale = max(hi.x - lo.x, hi.z - lo.z) * 1.08
if len(a) > 5:  # 부분 확대
    ctr = Vector((float(a[3]), ctr.y, float(a[4])))
    scale = float(a[5])
sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x = sc.render.resolution_y = res
sc.view_settings.view_transform = 'Standard'
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
w.node_tree.nodes['Background'].inputs[1].default_value = 1.0
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = scale
cam.location = Vector((ctr.x, lo.y - 5, ctr.z)); cam.rotation_euler = (math.radians(90), 0, 0)
sc.render.filepath = str(out)
bpy.ops.render.render(write_still=True)
json.dump({'res': res, 'ortho_scale': scale, 'cx': ctr.x, 'cz': ctr.z, 'bbox_lo': list(lo), 'bbox_hi': list(hi)},
          open(out.with_suffix('.json'), 'w'), indent=1)
print('[ortho] wrote', out)
