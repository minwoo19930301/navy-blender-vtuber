"""머리카락: 메타볼 덩어리. 덩어리마다 다른 패밀리라 서로 안 섞여 결이 남는다. head 노드 자식, 원점 = 두개골 중심."""
import math

import bpy
from mathutils import Vector

from common import DIMS, T, adopt, bezier, get_mat, metaballs_to_mesh, scene

HS = 1.12


def hair_lock(name, pts, r0, r1, flat=0.55, steps=14, resolution=0.025):
    C = DIMS['HEAD_C']
    mb = bpy.data.metaballs.new(name)
    mb.resolution = resolution
    mb.render_resolution = resolution
    mb.threshold = 0.6
    o = bpy.data.objects.new(name, mb)
    scene().collection.objects.link(o)
    for i in range(steps + 1):
        t = i / steps
        p = bezier(pts, t) * HS
        r = r0 + (r1 - r0) * t ** 1.3
        e = mb.elements.new(type='ELLIPSOID')
        e.co = T(C[0] + p.x, C[1] + p.y, C[2] + p.z)
        e.radius = r * 1.6
        e.size_x, e.size_y, e.size_z = 1.0, 1.0, flat
        n = Vector((p.x, -p.z, p.y)).normalized()
        e.rotation = Vector((0, 0, 1)).rotation_difference(n)
        e.stiffness = 2.0
    return o


def build(ctx):
    C = DIMS['HEAD_C']
    objs = []
    cap = bpy.data.metaballs.new('hair_cap')
    cap.resolution = 0.03
    cap.render_resolution = 0.03
    cap.threshold = 0.6
    cap_o = bpy.data.objects.new('hair_cap', cap)
    scene().collection.objects.link(cap_o)
    e = cap.elements.new(type='ELLIPSOID')
    e.co = T(C[0], C[1] + 0.16, C[2] - 0.05)
    e.radius = 1.0
    e.size_x, e.size_y, e.size_z = 0.78, 0.74, 0.80
    e.stiffness = 2.0
    objs.append(cap_o)
    fringe = [
        [(0.30, 0.80, 0.10), (0.02, 0.90, 0.36), (-0.34, 0.60, 0.50), (-0.52, 0.22, 0.40)],
        [(0.26, 0.76, 0.22), (0.06, 0.80, 0.48), (-0.22, 0.46, 0.58), (-0.36, 0.14, 0.54)],
        [(0.24, 0.72, 0.32), (0.12, 0.68, 0.54), (-0.06, 0.36, 0.60), (-0.16, 0.12, 0.58)],
        [(0.26, 0.68, 0.40), (0.24, 0.56, 0.57), (0.14, 0.34, 0.60), (0.08, 0.18, 0.59)],
        [(-0.10, 0.90, -0.05), (-0.40, 0.80, 0.20), (-0.60, 0.45, 0.30), (-0.64, 0.10, 0.18)],
        [(0.10, 0.92, -0.20), (-0.30, 0.88, -0.05), (-0.62, 0.55, 0.0), (-0.66, 0.05, -0.05)],
    ]
    for i, pts in enumerate(fringe):
        objs.append(hair_lock(f'hair_f{i}', pts, 0.21, 0.10))
    for i, pts in enumerate([
        [(0.30, 0.78, 0.18), (0.50, 0.70, 0.30), (0.62, 0.42, 0.30), (0.60, 0.12, 0.26)],
        [(0.34, 0.82, 0.02), (0.56, 0.72, 0.10), (0.68, 0.40, 0.10), (0.66, 0.08, 0.08)],
        [(0.30, 0.86, -0.20), (0.56, 0.72, -0.20), (0.68, 0.40, -0.18), (0.64, 0.05, -0.15)],
    ]):
        objs.append(hair_lock(f'hair_r{i}', pts, 0.17, 0.06))
    for i in range(4):
        a = -0.9 + i * 0.6
        objs.append(hair_lock(f'hair_b{i}', [(math.sin(a) * 0.2, 0.9, -0.25), (math.sin(a) * 0.5, 0.65, -0.5),
                                             (math.sin(a) * 0.62, 0.20, -0.48), (math.sin(a) * 0.55, -0.15, -0.40)], 0.16, 0.08))
    HAIR = get_mat('hair')
    for m in metaballs_to_mesh(objs):
        m.data.materials.clear()
        m.data.materials.append(HAIR)
        for p in m.data.polygons:
            p.use_smooth = True
        adopt(m, ctx['head'], C)
