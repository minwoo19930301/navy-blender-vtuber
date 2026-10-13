"""드라이버 검증용 임시 가중치: 뼈 선분까지의 거리로 나눈다 (body_rig 의 가중치가 나오기 전까지 팔·손 구동을 확인하는 용도).
  Blender --background --python rig/driver/quick_weights.py -- public/navy.glb public/wip/driver-test.glb
"""
import sys
import bpy
import numpy as np
from mathutils import Vector

SRC, OUT = sys.argv[sys.argv.index('--') + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
body = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
print('mesh', body.name, len(body.data.vertices), 'bones', [b.name for b in arm.data.bones])

mw = body.matrix_world
V = np.empty(len(body.data.vertices) * 3, dtype=np.float32)
body.data.vertices.foreach_get('co', V)
V = V.reshape(-1, 3)
M = np.array(mw)
V = V @ M[:3, :3].T + M[:3, 3]

bones = [b for b in arm.data.bones if b.name != 'neutral_bone']
segs = []
for b in bones:
    h = np.array(arm.matrix_world @ b.head_local)
    t = np.array(arm.matrix_world @ b.tail_local)
    segs.append((h, t))
names = [b.name for b in bones]


def dist_to_seg(P, a, b):
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(ab @ ab, 1e-9), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


D = np.stack([dist_to_seg(V, a, b) for a, b in segs], axis=1)
# 뼈 두께 가정: 몸통 뼈는 두껍게, 손가락은 얇게 (거리를 뼈 반경으로 나눠 비교)
rad = np.array([0.6 if n in ('hips', 'spine', 'chest') else 0.3 if n in ('neck', 'head') else 0.2 if n.startswith('shoulder') else 0.15 for n in names])
S = D / rad
W = 1.0 / (S ** 5 + 1e-4)
W /= W.sum(axis=1, keepdims=True)
# 팔 영역(몸통 폭 바깥)은 몸통 뼈 영향을 끈다
ax = np.abs(V[:, 0])
arm_zone = np.clip((ax - 0.55) / 0.12, 0, 1)
for i, n in enumerate(names):
    if n in ('hips', 'spine', 'chest', 'neck', 'head'):
        W[:, i] *= (1 - arm_zone)
# 머리 위는 head 고정
head_i = names.index('head')
head_y = segs[head_i][0][2] if False else None
vz = V[:, 2]
# Blender Z 위. head 뼈 head 의 z
hz = arm.matrix_world @ bones[head_i].head_local
t = np.clip((vz - (hz.z - 0.1)) / 0.15, 0, 1)
W[:, :] *= (1 - t[:, None])
W[:, head_i] += t
# 상위 4개만
idx = np.argsort(-W, axis=1)[:, :4]
body.vertex_groups.clear()  # 가져오기로 딸려 온 neutral_bone/head 그룹을 지운다
for i, n in enumerate(names):
    body.vertex_groups.new(name=n)
for k in range(4):
    for gi, n in enumerate(names):
        sel = np.where(idx[:, k] == gi)[0]
        if len(sel) == 0:
            continue
        w = W[sel, gi]
        for vi, ww in zip(sel.tolist(), w.tolist()):
            if ww > 1e-4:
                body.vertex_groups[n].add([vi], ww, 'ADD')
bpy.context.view_layer.objects.active = body
bpy.ops.object.vertex_group_normalize_all(lock_active=False)
bpy.ops.object.vertex_group_limit_total(limit=4)
bpy.ops.object.vertex_group_normalize_all(lock_active=False)
for m in body.modifiers:
    print('mod', m.name, m.type)
if not any(m.type == 'ARMATURE' for m in body.modifiers):
    md = body.modifiers.new('Armature', 'ARMATURE'); md.object = arm
body.parent = arm
for o in bpy.context.scene.objects:
    o.select_set(o.type in ('ARMATURE', 'MESH'))
bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', use_selection=True, export_yup=True, export_skins=True, export_animations=False)
print('exported', OUT)
