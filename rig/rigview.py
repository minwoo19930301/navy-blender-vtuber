"""rig.py 확인용 도구: 포즈 적용, 워크벤치 렌더(가중치 색·텍스처). Blender 안에서만 import 한다."""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

# 뼈마다 다른 색 (가중치 보기용)
PALETTE = [
    (0.55, 0.55, 0.55), (0.95, 0.35, 0.10), (0.95, 0.80, 0.10), (0.35, 0.80, 0.20), (0.10, 0.75, 0.80),
    (0.20, 0.30, 0.95), (0.70, 0.25, 0.90), (0.95, 0.30, 0.65), (0.55, 0.20, 0.10), (0.20, 0.45, 0.25),
    (0.60, 0.85, 0.95), (0.95, 0.60, 0.60), (0.40, 0.40, 0.75), (0.80, 0.70, 0.30), (0.25, 0.65, 0.55),
    (0.85, 0.45, 0.20), (0.30, 0.10, 0.45), (0.65, 0.95, 0.40), (0.15, 0.15, 0.15), (0.90, 0.90, 0.30),
    (0.45, 0.70, 0.95), (0.95, 0.15, 0.15), (0.15, 0.85, 0.45), (0.50, 0.50, 0.10), (0.90, 0.55, 0.85),
]


def three_to_bl(d):
    """three 방향(x 왼쪽+, y 위, z 앞) → Blender (x, -z, y)"""
    return Vector((d[0], -d[2], d[1])).normalized()


def aim(arm, name, d):
    """뼈의 Y 축(머리→꼬리)을 armature 공간 방향 d 로 돌린다 (최소 회전, 부모 포즈 반영)"""
    pb = arm.pose.bones[name]
    pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    cur = pb.matrix.to_3x3()  # 부모 포즈를 따라온 상태 (자기 회전은 항등)
    q = (cur @ Vector((0, 1, 0))).rotation_difference(Vector(d).normalized())
    m = (q.to_matrix() @ cur).to_4x4()
    m.translation = pb.matrix.translation
    pb.matrix = m
    bpy.context.view_layer.update()


def rot_about(arm, name, axis, ang, pivot=None):
    """뼈를 월드(armature) 축 axis 로 ang 만큼, pivot(기본 뼈 head) 기준으로 돌린다"""
    pb = arm.pose.bones[name]
    piv = Vector(pivot) if pivot is not None else pb.head.copy()
    r = Matrix.Rotation(ang, 4, Vector(axis))
    m = Matrix.Translation(piv) @ r @ Matrix.Translation(-piv) @ pb.matrix
    pb.matrix = m
    bpy.context.view_layer.update()


def reset_pose(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()


def arm_pose(arm, tag, upper, lower, hand=None):
    """three 방향(캐릭터 왼팔 기준, x 는 호출 쪽에서 side 를 곱해서 준다)으로 상완·전완·손을 맞춘다"""
    aim(arm, f'upper_arm_{tag}', three_to_bl(upper))
    aim(arm, f'forearm_{tag}', three_to_bl(lower))
    if hand is not None:
        aim(arm, f'hand_{tag}', three_to_bl(hand))


def pose(arm, name):
    """검증용 포즈. 앱 프리셋(src/harness/presets.ts)과 같은 방향을 쓴다"""
    reset_pose(arm)
    P = {
        'bind': {},
        'idle': {'L': ((0.25, -0.95, 0.15), (-0.75, -0.15, 0.62), (-0.25, -0.08, 1.0)),
                 'R': ((0.25, -0.95, 0.15), (-0.75, -0.15, 0.62), (-0.25, -0.08, 1.0))},
        'tpose': {'L': ((1, 0, 0), (1, 0, 0), (1, 0, 0)), 'R': ((1, 0, 0), (1, 0, 0), (1, 0, 0))},
        'wave': {'L': ((0.92, -0.25, 0.25), (0.15, 0.98, 0.1), (0.1, 0.99, 0.05)), 'R': ((0.25, -0.95, 0.15), (-0.75, -0.15, 0.62), (-0.25, -0.08, 1.0))},
        'armsup': {'L': ((0.35, 0.94, 0), (0.25, 0.97, 0), (0.2, 0.98, 0)), 'R': ((0.35, 0.94, 0), (0.25, 0.97, 0), (0.2, 0.98, 0))},
        'forward': {'L': ((0.12, -0.05, 0.99), (0.05, 0, 1), (0.05, 0, 1)), 'R': ((0.12, -0.05, 0.99), (0.05, 0, 1), (0.05, 0, 1))},
        'fist': {'L': ((0.5, -0.8, 0.3), (-0.1, 0.15, 0.98), (0, 0.55, 0.83)), 'R': ((0.5, -0.8, 0.3), (-0.1, 0.15, 0.98), (0, 0.55, 0.83))},
        'hang': {'L': ((0.05, -1, 0), (0.05, -1, 0), (0.05, -1, 0)), 'R': ((0.05, -1, 0), (0.05, -1, 0), (0.05, -1, 0))},
    }
    spec = P.get(name)
    if spec is not None:
        for tag, side in (('L', 1), ('R', -1)):
            if tag in spec:
                u, l, h = spec[tag]
                arm_pose(arm, tag, (side * u[0], u[1], u[2]), (side * l[0], l[1], l[2]), (side * h[0], h[1], h[2]))
    elif name == 'curl':
        for tag, side in (('L', 1), ('R', -1)):
            curl(arm, tag, side)
    elif name in ('yawL', 'yawR'):
        arm_pose(arm, 'L', (0.25, -0.95, 0.15), (-0.75, -0.15, 0.62))
        arm_pose(arm, 'R', (-0.25, -0.95, 0.15), (0.75, -0.15, 0.62))
        rot_about(arm, 'head', (0, 0, 1), math.radians(35 if name == 'yawL' else -35))
    elif name == 'twist':
        arm_pose(arm, 'L', (0.25, -0.95, 0.15), (-0.75, -0.15, 0.62))
        arm_pose(arm, 'R', (-0.25, -0.95, 0.15), (0.75, -0.15, 0.62))
        rot_about(arm, 'chest', (0, 0, 1), math.radians(22))
        rot_about(arm, 'spine', (0, 0, 1), math.radians(8))
    elif name == 'lean':
        rot_about(arm, 'chest', (0, 1, 0), math.radians(10))
        rot_about(arm, 'chest', (1, 0, 0), math.radians(10))
        rot_about(arm, 'spine', (0, 1, 0), math.radians(5))
    elif name == 'shrug':
        for tag, side in (('L', 1), ('R', -1)):
            rot_about(arm, f'shoulder_{tag}', (0, 1, 0), math.radians(-18 * side))
    bpy.context.view_layer.update()


def curl(arm, tag, side, deg=70, thumb_deg=40):
    """손가락을 손바닥 쪽으로 만다 (검증용). 축 = 손가락 방향 × 손바닥 법선(몸 안쪽)"""
    n = Vector((-side, 0, 0))
    for f in ('thumb', 'index', 'middle', 'ring', 'pinky'):
        for k in (1, 2, 3):
            nm = f'{f}{k}_{tag}'
            if nm not in arm.pose.bones:
                return
            pb = arm.pose.bones[nm]
            d = (pb.tail - pb.head).normalized()
            ax = d.cross(n - d * n.dot(d))
            if ax.length < 1e-6:
                continue
            rot_about(arm, nm, ax.normalized(), math.radians(thumb_deg if f == 'thumb' else deg))


def setup_workbench(res, color_type):
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.film_transparent = False
    sh = sc.display.shading
    sh.light = 'STUDIO' if color_type == 'TEXTURE' else 'FLAT'
    sh.color_type = color_type
    sh.show_cavity = False
    sh.show_object_outline = False
    sc.view_settings.view_transform = 'Standard'
    w = bpy.data.worlds.new('w')
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    sc.display.shading.background_type = 'WORLD'
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = 'ORTHO'
    return cam


def setup_eevee(res):
    """텍스처가 보이는 일반 렌더 (look.py 와 같은 조명)"""
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.view_settings.view_transform = 'Standard'
    w = bpy.data.worlds.new('w')
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    w.node_tree.nodes['Background'].inputs[1].default_value = 0.55
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(-35))
    sc.collection.objects.link(sun)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = 'ORTHO'
    return cam


def snap(cam, path, az, center, scale):
    """az: 0 정면(-Y 에서 봄), 90 캐릭터 왼쪽(+x)에서 봄 ... center 는 Blender 좌표"""
    t = math.radians(az)
    d = Vector((math.sin(t), -math.cos(t), 0.0))
    cam.location = Vector(center) + d * 30
    cam.rotation_euler = (math.radians(90), 0, t)
    cam.data.ortho_scale = scale
    cam.data.clip_end = 100
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def set_vertex_colors(obj, rgb):
    me = obj.data
    if 'dbg' in me.color_attributes:
        me.color_attributes.remove(me.color_attributes['dbg'])
    ca = me.color_attributes.new('dbg', 'FLOAT_COLOR', 'POINT')
    arr = np.ones((len(me.vertices), 4), dtype=np.float32)
    arr[:, :3] = rgb
    ca.data.foreach_set('color', arr.ravel())
    me.color_attributes.active_color = ca


def bone_vis(arm, color=(1, 0, 1), r=0.012):
    """뼈 구간을 가는 막대로 만들어 눈에 보이게 한다 (rest 위치)"""
    bm = bmesh.new()
    for b in arm.data.bones:
        h, t = b.head_local, b.tail_local
        d = t - h
        if d.length < 1e-5:
            continue
        m = Matrix.Translation((h + t) / 2) @ d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=r, radius2=r, depth=d.length, matrix=m)
        bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=6, radius=r * 1.8, matrix=Matrix.Translation(h))
    me = bpy.data.meshes.new('bonevis')
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new('bonevis', me)
    bpy.context.scene.collection.objects.link(ob)
    ob.show_in_front = True
    set_vertex_colors(ob, color)
    return ob
