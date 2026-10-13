"""손 붙이기(handattach.py)를 시험하기 위한 가짜 손. 진짜 손은 rig/hand/ 에 따로 온다.

  Blender --background --python rig/standin_hand.py -- rig/standin_hand

OUTDIR/hand_R.glb + hand_R.json 을 만든다. 좌표는 glTF(Y 위): 손목이 원점, 손가락이 +Y, 손바닥 바깥이 +Z, 엄지가 +X (오른손).
단위는 손바닥 길이 1 (rig.py 가 palm_len 에 맞춰 줄인다).
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

out = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
out.mkdir(parents=True, exist_ok=True)

# MediaPipe 21점 (glTF 좌표, 손바닥 길이 1)
mcp = {'index': (0.40, 0.95), 'middle': (0.13, 1.0), 'ring': (-0.14, 0.97), 'pinky': (-0.40, 0.88)}
seglen = {'index': (0.42, 0.28, 0.24), 'middle': (0.46, 0.30, 0.25), 'ring': (0.42, 0.28, 0.24), 'pinky': (0.34, 0.22, 0.20)}
pts = [(0.0, 0.0, 0.0)]
pts += [(0.30, 0.18, 0.10), (0.58, 0.42, 0.12), (0.76, 0.62, 0.12), (0.90, 0.80, 0.12)]   # 엄지 1~4
for f in ('index', 'middle', 'ring', 'pinky'):
    x, y = mcp[f]
    p = [(x, y, 0.0)]
    for L in seglen[f]:
        p.append((x, p[-1][1] + L, 0.0))
    pts += p
radius = {'palm': 0.42}


def bl(p):
    return Vector((p[0], -p[2], p[1]))


bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()
P = [bl(p) for p in pts]


def capsule(a, b, r):
    d = b - a
    m = Matrix.Translation((a + b) / 2) @ d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=r, radius2=r, depth=d.length, matrix=m)
    for c in (a, b):
        bmesh.ops.create_uvsphere(bm, u_segments=10, v_segments=6, radius=r, matrix=Matrix.Translation(c))


# 손바닥: 납작한 상자 (손목~MCP 줄)
cx, cy = 0.0, 0.5
bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation(bl((cx, cy, 0.0))) @ Matrix.Diagonal((0.95, 0.42, 1.0, 1.0)) @ Matrix.Diagonal((1, 1, 1, 1)))
# 손목 원통
capsule(P[0], bl((0, 0.15, 0)), 0.30)
for i, (f, i0) in enumerate((('thumb', 1), ('index', 5), ('middle', 9), ('ring', 13), ('pinky', 17))):
    for k in range(3):
        capsule(P[i0 + k], P[i0 + k + 1], 0.12 if f != 'pinky' else 0.10)
# 손등 쪽 두께: 상자 y 축이 앞뒤라 위에서 정의한 대로 z(=Blender -y)가 두께
me = bpy.data.meshes.new('hand_R')
bm.to_mesh(me)
bm.free()
ob = bpy.data.objects.new('hand_R', me)
bpy.context.scene.collection.objects.link(ob)
for p in me.polygons:
    p.use_smooth = True
mat = bpy.data.materials.new('skin')
mat.use_nodes = True
mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.95, 0.68, 0.62, 1)
me.materials.append(mat)
bpy.context.view_layer.objects.active = ob
ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(out / 'hand_R.glb'), export_format='GLB', use_selection=True, export_yup=True)
json.dump({'pts': [list(p) for p in pts], 'palm_len': 0.24}, open(out / 'hand_R.json', 'w'), indent=1)
print('[standin] wrote', out)
