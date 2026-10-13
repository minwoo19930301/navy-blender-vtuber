"""
3D 입: 구운 미소 선을 따라 메시를 가르고(입술), 턱 뼈로 아래 입술·턱을 내려 연다. 안쪽에는 입 속 주머니와 혀를 둔다.

rig.py 가 부른다 (좌표는 rig.py 의 앱 좌표, Blender Z 위·정면 -Y).
1. rip(): 입꼬리 두 점 사이를 텍스처가 가장 어두운 길(구운 입선)로 잇는 가장자리 경로를 찾아 그 모서리를 가른다.
   양 끝(입꼬리)은 붙어 있어서 닫히면 이음매가 안 보인다.
2. jaw_weights(): 입선 아래·입 폭 안·턱 앞쪽 정점에 턱 가중치 (부드럽게 줄어든다). 갈라진 아래 입술 정점은 1.0.
3. add_cavity(): 입 속 주머니(어두운 붉은색, 위 절반 head·아래 절반 jaw)와 혀(jaw).
"""
import heapq
import math

import bmesh
import numpy as np
from mathutils import Vector


def _ss(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def vertex_luminance(obj, mat_index):
    """정점마다 텍스처 밝기 (그 재질 면의 모서리 UV 평균). 재질이 다르면 1.0"""
    me = obj.data
    m = me.materials[mat_index]
    img = next(n.image for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    arr = px.reshape(h, w, 4)
    lum = np.ones(len(me.vertices))
    acc = np.zeros(len(me.vertices))
    cnt = np.zeros(len(me.vertices))
    uv = me.uv_layers.active.data
    for p in me.polygons:
        if p.material_index != mat_index:
            continue
        for li in p.loop_indices:
            u, v = uv[li].uv
            c = arr[min(h - 1, int(v % 1.0 * h)), min(w - 1, int(u % 1.0 * w))]
            vi = me.loops[li].vertex_index
            acc[vi] += 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
            cnt[vi] += 1
    ok = cnt > 0
    lum[ok] = acc[ok] / cnt[ok]
    return lum


def remove_inner_behind_mouth(obj, center, mw, log=print):
    """입 뒤의 안쪽 껍질을 지운다. TRELLIS 머리는 얼굴 겉면 바로 뒤에 피부색 안쪽 면이 한 겹 더 있어서,
    입술을 갈라 벌려도 그 면이 틈을 메워 입이 안 열려 보인다. 정면에서 쏜 광선의 첫 교점보다 1.2cm 이상 뒤에 있는 면(깊이 0.3 까지)을 지운다."""
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bvh = BVHTree.FromBMesh(bm)
    dead = []
    for f in bm.faces:
        c = f.calc_center_median()
        if abs(c.x - center.x) > 0.8 * mw or abs(c.z - center.z) > 0.16 or c.y > center.y + 0.3:
            continue
        hit = bvh.ray_cast(Vector((c.x, center.y - 1.0, c.z)), Vector((0, 1, 0)))
        if hit[0] is not None and c.y > hit[0].y + 0.006:
            dead.append(f)
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    log(f'mouth: removed {len(dead)} inner faces behind the mouth')


def smile_curve_from_texture(obj, center, mw, mat_index, log=print):
    """구운 미소 선을 텍스처에서 찾는다: 입 둘레 앞면 정점을 x 칸으로 나눠 칸마다 가장 어두운 점을 모으고 포물선을 맞춘다.
    돌려주는 값: (curve, x0, x1) 또는 None"""
    lum = vertex_luminance(obj, mat_index)
    me = obj.data
    P = np.array([v.co[:] for v in me.vertices])
    sel = (np.abs(P[:, 0] - center.x) < 0.65 * mw) & (np.abs(P[:, 2] - (center.z + 0.02)) < 0.09) & (P[:, 1] < center.y + 0.03)
    idx = np.nonzero(sel)[0]
    if len(idx) < 30:
        return None
    base = np.median(lum[idx])
    xs, zs, ws = [], [], []
    for x0 in np.arange(center.x - 0.65 * mw, center.x + 0.65 * mw, 0.012):
        b_ = idx[(P[idx, 0] >= x0) & (P[idx, 0] < x0 + 0.012)]
        if len(b_) < 3:
            continue
        j = b_[np.argmin(lum[b_])]
        dark = base - lum[j]
        if dark > 0.06:
            xs.append(P[j, 0]); zs.append(P[j, 2]); ws.append(dark)
    if len(xs) < 5:
        log(f'mouth: smile line not found in texture ({len(xs)} dark columns)')
        return None
    xs, zs, ws = map(np.array, (xs, zs, ws))
    coef = np.polyfit(xs, zs, 2, w=ws)
    # 한 번 튀는 점을 빼고 다시 맞춘다
    res = np.abs(np.polyval(coef, xs) - zs)
    keep = res < max(0.01, 2.5 * np.median(res))
    coef = np.polyfit(xs[keep], zs[keep], 2, w=ws[keep])
    x0, x1 = float(xs[keep].min()), float(xs[keep].max())
    log(f'mouth: smile from texture — {int(keep.sum())} columns, x {x0:+.3f}..{x1:+.3f}, z center {np.polyval(coef, center.x):.3f} corners {np.polyval(coef, x0):.3f}/{np.polyval(coef, x1):.3f}')
    return (lambda x: np.polyval(coef, x)), x0, x1


def lip_curve(cornerL, cornerR, lip_center):
    """입꼬리 둘과 입 가운데를 지나는 포물선 z(x) (구운 미소 선 ∪)"""
    xs = np.array([cornerR.x, lip_center.x, cornerL.x])
    zs = np.array([cornerR.z, lip_center.z, cornerL.z])
    a, b, c = np.polyfit(xs, zs, 2)
    return lambda x: a * x * x + b * x + c


def _weld_crack(bm, center, mw, log):
    """TRELLIS 얼굴은 가운데(x≈0)가 갈라져 좌우가 이어지지 않는다 → 입 둘레만 가까운 정점을 붙인다"""
    region = [v for v in bm.verts if abs(v.co.x - center.x) < 0.8 * mw and abs(v.co.z - center.z) < 0.12 and v.co.y < center.y + 0.08]
    bmesh.ops.remove_doubles(bm, verts=region, dist=0.008)


def rip(obj, cornerL, cornerR, lip_center, center, mw, log=print, found=None):
    """입선(포물선)을 따라 메시를 가른다. 입꼬리 안쪽(가장자리 0.012 들여)만 가르므로 양 끝은 붙어 있다.
    면을 곡선 위·아래로 나누고, 위 면과 아래 면 사이 모서리를 모두 가른다 (메시 간격만큼 계단지지만 틈 안은 어두운 입 속이라 안 보인다)."""
    if found:
        curve, x0, x1 = found[0], found[1] + 0.012, found[2] - 0.012
    else:
        curve = lip_curve(cornerL, cornerR, lip_center)
        x0, x1 = min(cornerL.x, cornerR.x) + 0.012, max(cornerL.x, cornerR.x) - 0.012
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    _weld_crack(bm, center, mw, log)
    bm.faces.ensure_lookup_table()

    def side(f):
        c = f.calc_center_median()
        if not (x0 - 0.02 < c.x < x1 + 0.02) or abs(c.z - curve(c.x)) > 0.06 or c.y > center.y + 0.06:
            return 0
        return -1 if c.z < curve(c.x) else 1
    sides = {f.index: side(f) for f in bm.faces}
    side_layer = bm.faces.layers.int.new('lip_side')
    for f in bm.faces:
        f[side_layer] = sides[f.index]
    cut = []
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        s0, s1 = sides[e.link_faces[0].index], sides[e.link_faces[1].index]
        mid = (e.verts[0].co + e.verts[1].co) / 2
        if s0 * s1 == -1 and x0 < mid.x < x1:
            cut.append(e)
    bmesh.ops.split_edges(bm, edges=cut)
    # 계단 모서리가 한 점에서만 만나는 곳은 정점 하나를 위·아래 면이 같이 써서 아래 입술이 뾰족하게 끌려 올라간다 → 그 정점도 아래 면 쪽으로 떼어 낸다
    n_sep = 0
    for v in list(bm.verts):
        if not v.is_valid or not (x0 + 0.01 < v.co.x < x1 - 0.01):   # 입꼬리는 붙여 둔다 (떼면 구멍)
            continue
        sd = {f[side_layer] for f in v.link_faces}
        if -1 in sd and 1 in sd:
            for f in [f for f in v.link_faces if f[side_layer] == -1]:
                if len(v.link_faces) > 1:
                    bmesh.utils.face_vert_separate(f, v)
                    n_sep += 1
    log(f'mouth: separated {n_sep} corner verts')
    # 계단 모양 가장자리를 곡선 위로 펴 준다: 갈라진 가장자리 정점의 z 를 곡선 높이로 (위·아래 두 벌 모두 → 닫히면 이음매가 매끈한 선)
    snapped = 0
    for v in bm.verts:
        c = v.co
        if x0 - 0.002 < c.x < x1 + 0.002 and abs(c.z - curve(c.x)) < 0.03 and c.y < center.y + 0.06 \
                and any(e.is_boundary for e in v.link_edges):
            v.co.z = float(curve(c.x))
            snapped += 1
    log(f'mouth: snapped {snapped} lip edge verts onto the curve')
    # 입술 정점 표시 (뒤 단계에서 정점 번호가 바뀌어도 남게 정점 그룹에): 아래쪽 면만 쓰는 정점 = 'lip_lower', 위쪽 면을 쓰는 정점 = 'lip_upper'
    deform = bm.verts.layers.deform.verify()
    gl = (obj.vertex_groups.get('lip_lower') or obj.vertex_groups.new(name='lip_lower')).index
    gu = (obj.vertex_groups.get('lip_upper') or obj.vertex_groups.new(name='lip_upper')).index
    n_low = n_up = 0
    for v in bm.verts:
        sd = {f[side_layer] for f in v.link_faces} - {0}
        if 1 in sd:
            v[deform][gu] = 1.0
            n_up += 1
        elif sd == {-1}:
            v[deform][gl] = 1.0
            n_low += 1
    bm.faces.layers.int.remove(side_layer)
    log(f'mouth: tagged lower {n_low}, upper {n_up} verts')
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    log(f'mouth: lip curve cut {len(cut)} edges, x {x0:+.3f}..{x1:+.3f}, center z {float(curve(lip_center.x)):.3f}')
    return curve, (x0, x1)


def lip_sides(obj, curve=None, xr=None, center=None):
    """rip() 이 정점 그룹으로 표시한 아래 입술('lip_lower')·윗입술('lip_upper') 정점. 읽은 뒤 그룹은 지운다"""
    out = []
    for name in ('lip_lower', 'lip_upper'):
        vg = obj.vertex_groups.get(name)
        ids = set()
        if vg:
            gi = vg.index
            for v in obj.data.vertices:
                if any(g.group == gi and g.weight > 0.5 for g in v.groups):
                    ids.add(v.index)
            obj.vertex_groups.remove(vg)
        out.append(ids)
    return out[0], out[1]


def jaw_weights(P, curve, center, mw, chin_z, head_y, lower, upper=(), xr=None):
    """정점마다 턱 가중치 0..1. 입선 바로 아래부터 크게, 턱 밑(목)과 옆 뺨·얼굴 뒤로 가면 0"""
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    lz = curve(x)
    below = _ss(lz - z, -0.001, 0.01)                        # 입선 아래 (윗입술은 0)
    lateral = 1 - _ss(np.abs(x - center.x), 0.5 * mw, 0.95 * mw)
    front = 1 - _ss(y - head_y, -0.18, -0.04)              # 얼굴 앞쪽만 (턱 밑·목 앞이 안 끌려 내려가게)
    chin = 1 - _ss((chin_z + 0.02) - z, 0.0, 0.05)         # 턱끝 아래로 가면 빨리 0
    w = below * lateral * front * chin
    # 입 가운데만 크게 열리고 입꼬리 쪽은 거의 닫힌 채로 (입꼬리까지 똑같이 내려가면 웃는 선 전체가 검게 벌어져 무섭다)
    if xr is not None:
        mid, half = (xr[0] + xr[1]) / 2, (xr[1] - xr[0]) / 2
        taper = np.cos(np.pi / 2 * np.clip(np.abs(x - mid) / half, 0, 1)) ** 0.8
    else:
        taper = np.ones_like(x)
    w = w * (0.25 + 0.75 * taper)
    for i in lower:
        if i < len(w):
            w[i] = float(taper[i])
    for i in upper:
        if i < len(w):
            w[i] = 0.0
    return w


def add_cavity(bpy, arm, center, mw, y_front, log=print):
    """입 속 주머니와 혀. center: 입 가운데(앱 좌표), y_front: 입 표면 깊이(-Y 가 앞)"""
    def ellipsoid(name, c, r, rgb, groups):
        me = bpy.data.meshes.new(name)
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=1.0)
        for v in bm.verts:
            v.co = Vector((c.x + v.co.x * r[0], c.y + v.co.y * r[1], c.z + v.co.z * r[2]))
        bm.to_mesh(me)
        bm.free()
        for p in me.polygons:
            p.use_smooth = True
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        lin = [cc / 12.92 if cc <= 0.04045 else ((cc + 0.055) / 1.055) ** 2.4 for cc in rgb]
        bsdf = mat.node_tree.nodes['Principled BSDF']
        bsdf.inputs['Base Color'].default_value = (*lin, 1)
        bsdf.inputs['Roughness'].default_value = 0.6
        me.materials.append(mat)
        for gname, fn in groups.items():
            vg = ob.vertex_groups.new(name=gname)
            for v in me.vertices:
                wv = fn(v.co)
                if wv > 1e-4:
                    vg.add([v.index], float(wv), 'REPLACE')
        ob.parent = arm
        mod = ob.modifiers.new('Armature', 'ARMATURE')
        mod.object = arm
        return ob

    cz = center.z - 0.012
    cav_c = Vector((center.x, y_front + 0.08, cz))
    split = lambda co: float(_ss(np.array(cz - co.z), -0.02, 0.02))  # noqa: E731  아래쪽일수록 1
    pocket = ellipsoid('navy_mouth', cav_c, (0.4 * mw, 0.07, 0.065), (0.47, 0.17, 0.19),
                       {'jaw': split, 'head': lambda co: 1 - split(co)})
    # 혀: 아래 입술 바로 뒤, 벌리면 입 속 아래쪽에 살짝 보이게
    # 혀: 입 속 아래쪽, 아래 입술 바로 뒤 (앞으로 나오면 턱 밖으로 비친다)
    tongue = ellipsoid('navy_tongue', Vector((center.x, y_front + 0.07, cz - 0.03)), (0.24 * mw, 0.045, 0.022), (0.9, 0.5, 0.52),
                       {'jaw': lambda co: 1.0})
    log(f'mouth: cavity at ({cav_c.x:+.3f},{cav_c.y:+.3f},{cav_c.z:+.3f}) width {mw:.3f}')
    return [pocket, tongue]
