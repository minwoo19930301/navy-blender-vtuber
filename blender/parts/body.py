"""몸통: 재킷 몸판·앞섶·라펠, 흰 티셔츠, 목깃, 목. 전부 body 노드의 자식."""
import bpy

from common import DIMS, T, apply_mods, activate, get_mat, loft_bm, mesh_obj, subsurf
import bmesh


def conform_panel(name, outline, material, offset, thickness, parent, target):
    """정면 외곽선(x, y)을 채운 판을 target 앞면에 shrinkwrap 으로 붙이고 두께를 준다."""
    bm = bmesh.new()
    verts = [bm.verts.new(T(x, y, 1.5)) for x, y in outline]
    bm.faces.new(verts)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    o = mesh_obj(name, bm, material, parent)
    activate(o)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.tris_convert_to_quads()
    bpy.ops.mesh.subdivide(number_cuts=10)
    bpy.ops.mesh.subdivide(number_cuts=2)
    bpy.ops.object.mode_set(mode='OBJECT')
    sw = o.modifiers.new('wrap', 'SHRINKWRAP')
    sw.target = target
    sw.wrap_method = 'PROJECT'
    sw.use_project_y = True
    sw.use_negative_direction = True
    sw.use_positive_direction = True
    sw.offset = offset
    so = o.modifiers.new('thick', 'SOLIDIFY')
    so.thickness = thickness
    so.offset = 1
    apply_mods(o)
    sm = o.modifiers.new('smooth', 'CORRECTIVE_SMOOTH')
    sm.iterations = 4
    apply_mods(o)
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def build(ctx):
    body = ctx['body']
    JACKET, SHIRT, SKIN = get_mat('jacket'), get_mat('shirt'), get_mat('skin')
    b = DIMS['BODY_BOTTOM']
    torso_sections = [
        (b, 0.80, 0.44, 0, -0.02),
        (0.10, 0.82, 0.46, 0, -0.02),
        (0.50, 0.85, 0.47, 0, -0.03),
        (0.80, 0.88, 0.46, 0, -0.04),
        (0.98, 0.84, 0.42, 0, -0.05),
        (1.10, 0.62, 0.36, 0, -0.05),
        (1.18, 0.34, 0.27, 0, -0.04),
        (1.21, 0.24, 0.21, 0, -0.03),
    ]
    torso = mesh_obj('torso', loft_bm(torso_sections, seg=48), JACKET, body)
    subsurf(torso, 2)
    neck = mesh_obj('neck', loft_bm([(1.02, 0.17, 0.16, 0, 0.0), (1.20, 0.17, 0.16, 0, 0.0), (1.42, 0.18, 0.17, 0, -0.01)], seg=24), SKIN, body)
    subsurf(neck, 1)
    conform_panel('shirt', [(-0.27, 1.16), (-0.14, 1.08), (0.0, 1.05), (0.14, 1.08), (0.27, 1.16),
                            (0.30, 0.9), (0.26, -0.2), (-0.26, -0.2), (-0.30, 0.9)], SHIRT, 0.004, 0.012, body, torso)
    for side in (-1, 1):
        s = side
        tag = 'L' if side > 0 else 'R'
        conform_panel(f'jacket_front_{tag}',
                      [(s * 0.25, 1.17), (s * 0.52, 1.08), (s * 0.78, 0.94), (s * 0.80, -0.2), (s * 0.20, -0.2), (s * 0.24, 0.5)],
                      JACKET, 0.012, 0.03, body, torso)
        conform_panel(f'lapel_{tag}',
                      [(s * 0.23, 1.19), (s * 0.42, 1.15), (s * 0.52, 0.98), (s * 0.44, 0.94), (s * 0.54, 0.84), (s * 0.30, 0.36), (s * 0.24, 0.5)],
                      JACKET, 0.045, 0.03, body, torso)
    collar_bm = bmesh.new()
    bmesh.ops.create_cone(collar_bm, cap_ends=False, segments=32, radius1=0.2, radius2=0.2, depth=0.05)
    for v in collar_bm.verts:
        x, y, z = v.co.x, v.co.z, -v.co.y
        v.co = T(x * 1.05, 1.17 + y, z * 0.95)
    collar = mesh_obj('collar', collar_bm, SHIRT, body)
    so = collar.modifiers.new('thick', 'SOLIDIFY')
    so.thickness = 0.04
    apply_mods(collar)
    subsurf(collar, 1)
