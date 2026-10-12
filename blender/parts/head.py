"""머리: 두개골 피부, 귀, 코, 얼굴 데칼 판. 전부 head 노드(두개골 중심) 자식이고 원점도 두개골 중심."""
import math

import bmesh

from common import DIMS, T, apply_mods, get_mat, mesh_obj, sphere_bm


def build(ctx):
    head = ctx['head']
    C = DIMS['HEAD_C']
    HR = DIMS['HEAD_R']
    SKIN, SKIN_DARK = get_mat('skin'), get_mat('skin_shade')

    def head_shape(x, y, z):
        ny = y / HR[1]
        if ny < 0:
            x *= 1 - 0.07 * (-ny) ** 2.0
            z *= 1 - 0.10 * (-ny) ** 2
        x *= 1 + math.exp(-((ny + 0.35) / 0.25) ** 2) * 0.04
        if z > 0:
            z *= 0.93
        return x, y, z

    hs = mesh_obj('head_skin', sphere_bm(C, HR, 64, 48, head_shape), SKIN, head, origin=C)
    ctx['head_skin'] = hs
    mesh_obj('nose', sphere_bm((C[0], C[1] - 0.40, C[2] + 0.56), (0.066, 0.054, 0.05), 24, 16), SKIN, head, origin=C)
    for side, tag in ((1, 'L'), (-1, 'R')):
        ex, ey, ez = C[0] + side * 0.67, C[1] - 0.17, C[2] - 0.02
        mesh_obj(f'ear_{tag}', sphere_bm((ex, ey, ez), (0.085, 0.18, 0.13), 24, 16), SKIN, head, origin=C)
        mesh_obj(f'ear_in_{tag}', sphere_bm((ex + side * 0.04, ey + 0.005, ez + 0.01), (0.035, 0.11, 0.07), 20, 12), SKIN_DARK, head, origin=C)

    # 얼굴 데칼: 얼굴 앞쪽에 붙인 촘촘한 판. UV 는 three.js(face.ts)가 머리 로컬 위치로 다시 계산한다
    x0, x1, y0, y1 = DIMS['DECAL']
    dbm = bmesh.new()
    N = 48
    grid = [[dbm.verts.new(T(C[0] + x0 + (x1 - x0) * j / N, C[1] + y0 + (y1 - y0) * i / N, C[2] + 1.2))
             for j in range(N + 1)] for i in range(N + 1)]
    for i in range(N):
        for j in range(N):
            dbm.faces.new((grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j]))
    decal = mesh_obj('face_decal', dbm, get_mat('face_decal'), head, origin=C)
    sw = decal.modifiers.new('wrap', 'SHRINKWRAP')
    sw.target = hs
    sw.wrap_method = 'PROJECT'
    sw.use_project_y = True
    sw.use_negative_direction = True
    sw.use_positive_direction = True
    sw.offset = 0.004
    apply_mods(decal)
    bm = bmesh.new()
    bm.from_mesh(decal.data)
    bad = [v for v in bm.verts if v.co.y < -1.0]  # 투사 실패(앞에 남은) 정점
    bmesh.ops.delete(bm, geom=bad, context='VERTS')
    bm.to_mesh(decal.data)
    bm.free()
