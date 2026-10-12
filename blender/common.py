"""
Blender 모델 공용 도구와 치수 계약.

좌표는 전부 three.js 기준(Y 위, +Z 카메라 쪽)으로 적고 T()로 Blender(Z 위, -Y 정면)로 바꾼다.
glTF 내보내기가 다시 Y 위로 돌려 주므로 three.js에서는 적은 좌표 그대로 나온다.
책상 윗면이 y=0, 캐릭터 가운데가 x=0이다. side=+1이 +x(화면 오른쪽) 쪽이다.

DIMS 는 부위끼리, 그리고 three.js 리그(src/model/rig.ts)와 맞물리는 치수다.
값을 바꾸면 src/model/rig.ts 의 같은 이름 상수도 같이 바꿔야 한다.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

# ───────────────────────── 치수 계약 (three 좌표, 단위 = three 단위)
DIMS = {
    # 몸통: 책상(y=0) 아래로 조금 묻힌다
    'BODY_BOTTOM': -0.30,
    # 목 피벗 (고개 회전 중심). head_pivot 노드 위치
    'NECK_PIVOT': (0.0, 1.30, 0.0),
    # 두개골 중심 = head 노드 위치. 머리 로컬 좌표의 원점
    'HEAD_C': (0.0, 1.98, 0.04),
    # 두개골 반지름 (x 반폭, y 반높이, z 반깊이) — 머리카락·얼굴 데칼이 이 위에 얹힌다
    'HEAD_R': (0.68, 0.78, 0.62),
    # 어깨 관절 (side=+1 기준, x 는 side 를 곱한다). 위팔 소매 원점
    'SHOULDER': (0.86, 0.92, -0.05),
    # 위팔·아래팔 길이 (관절→관절). 소매 메시는 원점에서 +Y 로 이만큼 뻗는다
    'UPPER_LEN': 0.62,
    'LOWER_LEN': 0.60,
    # 쉼 자세 방향 (side=+1 기준, x 에 side 를 곱한다). three 리그의 기본 자세와 같다
    'REST_UPPER': (0.25, -0.95, 0.15),
    'REST_LOWER': (-0.75, -0.15, 0.62),
    'REST_HAND': (-0.25, -0.08, 1.0),   # 손가락 방향
    'REST_PALM': (0.0, -1.0, 0.0),      # 손바닥이 보는 방향 (책상)
    # 얼굴 데칼 범위 (머리 로컬 x0, x1, y0, y1). src/model/face.ts 의 DECAL 과 같다
    'DECAL': (-0.56, 0.56, -0.68, 0.52),
}


def T(x, y, z=None):
    if z is None:  # T(vec3)
        x, y, z = x
    return Vector((x, -z, y))


def three(v):
    """Blender 좌표 → three 좌표 튜플"""
    return (v.x, v.z, -v.y)


def scene():
    return bpy.context.scene


def deselect_all():
    for ob in bpy.context.selected_objects:
        ob.select_set(False)


def update():
    bpy.context.view_layer.update()


def world_to_local(v, parent):
    if parent is None:
        return v
    return parent.matrix_world.inverted() @ v


def empty(name, pos=(0, 0, 0), parent=None):
    """three 월드 좌표 pos 에 놓인 빈 노드 (회전 없음)"""
    o = bpy.data.objects.new(name, None)
    scene().collection.objects.link(o)
    if parent is not None:
        o.parent = parent
        o.matrix_parent_inverse = Matrix.Identity(4)
    update()
    o.location = world_to_local(T(*pos), parent)
    update()
    return o


def mesh_obj(name, bm, material, parent=None, origin=(0, 0, 0), smooth=True):
    """bm 정점은 Blender 월드 좌표(T 로 만든 값). origin(three 월드)을 오브젝트 원점으로 둔다.
    부모는 회전이 없는 노드여야 한다 (모든 빈 노드는 회전 없이 만든다)."""
    me = bpy.data.meshes.new(name)
    o_w = T(*origin)
    for v in bm.verts:
        v.co -= o_w
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = smooth
    if material is not None:
        me.materials.append(material)
    o = bpy.data.objects.new(name, me)
    scene().collection.objects.link(o)
    if parent is not None:
        o.parent = parent
        o.matrix_parent_inverse = Matrix.Identity(4)
    update()
    o.location = world_to_local(o_w, parent)
    update()
    return o


def adopt(o, parent, origin=(0, 0, 0)):
    """이미 월드에 있는 오브젝트(메타볼 변환 결과 등)를 변환을 메시에 구워 parent 아래 origin 원점으로 옮긴다"""
    o.data.transform(o.matrix_world)
    o.data.transform(Matrix.Translation(-T(*origin)))
    o.parent = parent
    o.matrix_parent_inverse = Matrix.Identity(4)
    o.matrix_basis = Matrix.Identity(4)
    update()
    o.location = world_to_local(T(*origin), parent)
    update()
    return o


def activate(o):
    deselect_all()
    bpy.context.view_layer.objects.active = o
    o.select_set(True)


def apply_mods(o):
    activate(o)
    for m in list(o.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


def subsurf(o, levels=2):
    m = o.modifiers.new('sub', 'SUBSURF')
    m.levels = levels
    m.render_levels = levels
    apply_mods(o)


def shade_smooth(o, auto_angle=None):
    for p in o.data.polygons:
        p.use_smooth = True


def sphere_bm(center, radii, seg=48, rings=32, deform=None):
    """three 좌표 center·radii 의 타원체. deform(x, y, z) 는 중심 기준 three 좌표를 받아 바꾼다"""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=rings, radius=1.0)
    for v in bm.verts:
        x, y, z = v.co.x, v.co.z, -v.co.y
        x, y, z = x * radii[0], y * radii[1], z * radii[2]
        if deform:
            x, y, z = deform(x, y, z)
        v.co = T(center[0] + x, center[1] + y, center[2] + z)
    return bm


def loft_bm(rings_def, seg=32, cap=True):
    """rings_def: [(y, rx, rz, cx, cz)] 를 three Y 축으로 쌓은 관. 양 끝은 뾰족하지 않은 캡"""
    bm = bmesh.new()
    rings = []
    for (y, rx, rz, cx, cz) in rings_def:
        ring = []
        for j in range(seg):
            a = j / seg * math.tau
            ring.append(bm.verts.new(T(cx + math.cos(a) * rx, y, cz + math.sin(a) * rz)))
        rings.append(ring)
    for i in range(len(rings) - 1):
        for j in range(seg):
            a, b = rings[i][j], rings[i][(j + 1) % seg]
            c, d = rings[i + 1][(j + 1) % seg], rings[i + 1][j]
            bm.faces.new((a, b, c, d))
    if cap:
        for idx in (0, -1):
            ring = rings[idx]
            ctr = sum((v.co for v in ring), Vector()) / seg
            y0 = rings_def[idx][0]
            dy = (rings_def[1][0] - y0) if idx == 0 else (rings_def[-2][0] - y0)
            tip = bm.verts.new(ctr + T(0, -0.35 * dy, 0))
            for j in range(seg):
                a, b = ring[j], ring[(j + 1) % seg]
                bm.faces.new((a, b, tip))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def bezier(p, t):
    n = len(p) - 1
    out = Vector((0, 0, 0))
    for i, q in enumerate(p):
        out += Vector(q) * (math.comb(n, i) * (1 - t) ** (n - i) * t ** i)
    return out


def metaballs_to_mesh(objs):
    """메타볼 오브젝트들을 메시로 바꿔 돌려준다 (이름 유지)"""
    out = []
    for o in objs:
        name = o.name
        activate(o)
        bpy.ops.object.convert(target='MESH')
        m = bpy.context.view_layer.objects.active
        m.name = name
        m.data.name = name
        out.append(m)
    deselect_all()
    return out


def srgb(h):
    h = h.lstrip('#')
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)


def get_mat(name):
    """materials.py 가 만든 머티리얼. 없으면 회색 임시 머티리얼"""
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
    return m
