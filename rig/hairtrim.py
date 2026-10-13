"""
옆머리 다듬기 (사용자 요청): 오른쪽 관자놀이의 짧은 가닥은 없애고, 귀 앞 긴 구레나룻은 그 짧은 가닥 길이로 자른다 (양쪽 같게).

rig.py 가 부른다 (앱 좌표, Blender Z 위·정면 -Y). 머리카락 = 베이스컬러 텍스처가 어두운 면.
지운 자리에 구멍이 나면 메우고, 근처 피부 색(UV)을 입힌다.
"""
import bmesh
import numpy as np


def base_color_images(me):
    """재질 번호 → (픽셀 배열, w, h). 베이스컬러에 연결된 이미지만 (거칠기 텍스처를 잘못 읽지 않게)"""
    out = {}
    for mi, m in enumerate(me.materials):
        if not m or not m.node_tree:
            continue
        for n in m.node_tree.nodes:
            if n.type == 'TEX_IMAGE' and n.image and any(l.to_socket.name == 'Base Color' for l in n.outputs['Color'].links):
                w, h = n.image.size
                px = np.empty(w * h * 4, np.float32)
                n.image.pixels.foreach_get(px)
                out[mi] = (px.reshape(h, w, 4), w, h)
                break
    return out


def trim_sideburns(obj, eye_z, log=print):
    me = obj.data
    imgs = base_color_images(me)
    bm = bmesh.new()
    bm.from_mesh(me)
    uvl = bm.loops.layers.uv.active
    bm.faces.ensure_lookup_table()

    def color(f):
        if f.material_index not in imgs:
            return None
        arr, w, h = imgs[f.material_index]
        u = sum(l[uvl].uv[0] for l in f.loops) / len(f.loops)
        v = sum(l[uvl].uv[1] for l in f.loops) / len(f.loops)
        return arr[min(h - 1, int(v % 1.0 * h)), min(w - 1, int(u % 1.0 * w)), :3]

    def in_side(c, top=0.115):
        return 0.45 < abs(c.x) < 0.72 and -0.32 < c.y < 0.15 and eye_z - 0.35 < c.z < eye_z + top

    # 짧은 가닥은 머리선까지(눈 + 0.16) 올라가 붙어 있어 조금 더 위까지 본다
    cols = {f.index: color(f) for f in bm.faces if in_side(f.calc_center_median(), 0.16)}
    hair = [f for f in bm.faces if f.index in cols and cols[f.index] is not None and cols[f.index].max() < 0.25]
    # 짧은 가닥: 구레나룻보다 앞(얼굴 쪽, y < -0.12)에 매달린 가닥. 양쪽 다 지운다
    short = [f for f in hair if -0.27 < f.calc_center_median().y < -0.12 and 0.5 < abs(f.calc_center_median().x) < 0.63]
    hair = [f for f in hair if f in short or f.calc_center_median().z < eye_z + 0.115]
    if short:
        cut_z = min(f.calc_center_median().z for f in short if f.calc_center_median().x < 0) if any(f.calc_center_median().x < 0 for f in short) \
            else min(f.calc_center_median().z for f in short)
    else:
        cut_z = eye_z + 0.005
        log('hair trim: short strand not found, using eye height')
    long_ = [f for f in hair if f not in short and f.calc_center_median().z < cut_z]
    # 메울 피부: 지울 면 근처의 밝은 피부 면 (재질·UV 를 빌린다)
    skins = [f for f in bm.faces if f.index in cols and cols[f.index] is not None
             and cols[f.index][0] > 0.8 and 0.1 < cols[f.index][0] - cols[f.index][2] < 0.3 and cols[f.index][1] > 0.6]   # 뺨 피부색 (회색·그림자 빼고)
    dead = set(short) | set(long_)
    # 지운 자리 둘레(구레나룻이 덮던 자리)의 어두운 테두리 면도 피부로 바꿀 대상 — 지운 면들의 위치 범위를 기억해 둔다
    foot = [f.calc_center_median().copy() for f in dead]
    bmesh.ops.delete(bm, geom=list(dead), context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    # 지운 자리의 열린 가장자리만 메운다 (입선 등 다른 열린 곳은 건드리지 않는다)
    bnd = [e for e in bm.edges if e.is_boundary and in_side((e.verts[0].co + e.verts[1].co) / 2, 0.17)]
    filled = bmesh.ops.holes_fill(bm, edges=bnd, sides=400)['faces'] if bnd else []
    if filled:
        filled = bmesh.ops.triangulate(bm, faces=filled)['faces']
    # 메운 면은 UV 가 비어 있다 → 가장 가까운 피부 면의 UV 한 점과 재질을 준다
    skin_pts = [(g.calc_center_median().copy(), g) for g in skins if g.is_valid]
    hair_pts = [(g.calc_center_median().copy(), g) for g in bm.faces if g.is_valid and g.index in cols and cols[g.index] is not None
                and cols[g.index].max() < 0.2 and g.calc_center_median().z > eye_z + 0.1]
    for f in filled:
        if not skin_pts:
            break
        c = f.calc_center_median()
        # 머리선 근처(눈 + 0.1 위)에 난 구멍은 머리카락 색, 아래는 피부색으로 메운다
        pool = hair_pts if (c.z > eye_z + 0.1 and hair_pts) else skin_pts
        _, g = min(pool, key=lambda t: (t[0] - c).length)
        su = sum(l[uvl].uv[0] for l in g.loops) / len(g.loops)
        sv = sum(l[uvl].uv[1] for l in g.loops) / len(g.loops)
        for l in f.loops:
            l[uvl].uv = (su, sv)
        f.material_index = g.material_index
    # 테두리 정리: 지운 자리 바로 둘레(0.03 안)·자른 높이 아래의 피부가 아닌 면(머리카락 가장자리의 어두운 띠)을 피부 UV 로
    from mathutils.kdtree import KDTree
    if foot and skin_pts:
        kd = KDTree(len(foot))
        for i, c in enumerate(foot):
            kd.insert(c, i)
        kd.balance()
        n_edge = 0
        for f in bm.faces:
            if not f.is_valid:
                continue
            c = f.calc_center_median()
            if c.z > cut_z - 0.004 or not in_side(c):
                continue
            if kd.find(c)[2] > 0.03:
                continue
            col = color(f)
            if col is None or (col[0] > 0.8 and 0.1 < col[0] - col[2] < 0.3 and col[1] > 0.6):
                continue
            _, g = min(skin_pts, key=lambda t: (t[0] - c).length)
            su = sum(l[uvl].uv[0] for l in g.loops) / len(g.loops)
            sv = sum(l[uvl].uv[1] for l in g.loops) / len(g.loops)
            for l in f.loops:
                l[uvl].uv = (su, sv)
            f.material_index = g.material_index
            n_edge += 1
        log(f'hair trim: cleaned {n_edge} outline faces')
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    me.update()
    log(f'hair trim: removed short strand {len(short)} faces, sideburns below z={cut_z:.3f} {len(long_)} faces, filled {len(filled)} faces')
    return cut_z


def blacken_eye_corner(obj, eye_c, half_w, half_h, side_sign, log=print):
    """눈 테두리 안의 밝은 초승달(흰자)을 검은 눈동자 색으로 칠해 눈을 꽉 찬 타원으로 만든다 (사용자: 눈 끝이 안쪽으로 파여 보인다).
    면 단위로 칠하면 계단지므로 텍스처를 텍셀 단위로 고친다: 눈 둘레 삼각형을 UV 공간에 래스터화해 텍셀마다 3D 위치를 구하고,
    어두운 눈동자 텍셀로 맞춘 타원 안 바깥 고리(반지름² 0.36~1.0)의 밝은 텍셀만 눈동자 색으로. 하이라이트(안쪽)·속눈썹 선(밖)은 그대로"""
    me = obj.data
    imgs = base_color_images(me)
    me.calc_loop_triangles()
    uvd = me.uv_layers.active.data
    V = np.array([v.co[:] for v in me.vertices])
    tris = []
    for t in me.loop_triangles:
        P = V[list(t.vertices)]
        c = P.mean(0)
        dx, dz = (c[0] - eye_c.x) / half_w, (c[2] - eye_c.z) / half_h
        if dx * dx + dz * dz < 4.0 and c[1] < eye_c.y + 0.15 and t.material_index in imgs:
            tris.append((t.material_index, P, np.array([uvd[li].uv[:] for li in t.loops])))
    if not tris:
        log('eye corner: no triangles')
        return
    mi = max({m for m, _, _ in tris}, key=lambda m: sum(1 for x in tris if x[0] == m))
    arr, w, h = imgs[mi]
    tex = arr.copy()
    pos, pix = [], []
    for m, P, UV in tris:
        if m != mi:
            continue
        px_ = np.stack([UV[:, 0] * w - 0.5, UV[:, 1] * h - 0.5], 1)
        x0, x1 = int(np.floor(px_[:, 0].min())), int(np.ceil(px_[:, 0].max()))
        y0, y1 = int(np.floor(px_[:, 1].min())), int(np.ceil(px_[:, 1].max()))
        e1, e2 = px_[1] - px_[0], px_[2] - px_[0]
        den = e1[0] * e2[1] - e2[0] * e1[1]
        if abs(den) < 1e-9 or x1 - x0 > 200 or y1 - y0 > 200:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        dxp, dyp = gx - px_[0, 0], gy - px_[0, 1]
        a_ = (dxp * e2[1] - e2[0] * dyp) / den
        b_ = (e1[0] * dyp - dxp * e1[1]) / den
        ins = (a_ >= -0.01) & (b_ >= -0.01) & (a_ + b_ <= 1.01)
        for yy, xx, aa, bb in zip(gy[ins], gx[ins], a_[ins], b_[ins]):
            if 0 <= xx < w and 0 <= yy < h:
                pos.append(P[0] + aa * (P[1] - P[0]) + bb * (P[2] - P[0]))
                pix.append((yy % h, xx % w))
    pos, pix = np.array(pos), np.array(pix)
    col = tex[pix[:, 0], pix[:, 1], :3]
    dark = col.max(1) < 0.12
    if dark.sum() < 30:
        log(f'eye corner: pupil texels not found ({int(dark.sum())})')
        return
    X = pos[dark][:, [0, 2]]
    m0, sd = X.mean(0), X.std(0)
    rx, rz = 2.0 * sd[0], 2.0 * sd[1]
    pupil = np.median(col[dark], 0)
    r = ((pos[:, 0] - m0[0]) / rx) ** 2 + ((pos[:, 2] - m0[1]) / rz) ** 2
    # 흰자·회색 테두리 = 채도가 낮은 밝은 텍셀 (피부는 붉은 기가 있어 빠진다). 눈동자 가운데 하이라이트(r² < 0.3)는 남긴다.
    # 눈 바깥 검은 테두리까지(r² < 2.6) 채워 눈 전체가 하나의 검은 타원이 되게 한다
    sat = np.abs(col[:, 0] - col[:, 2])
    grey = (col.max(1) > 0.12) & (sat < 0.12)        # 흰자·회색 테두리·옛 눈동자 경계의 회색 고리
    sel = (r > 0.3) & (r < 3.6) & grey
    tex[pix[sel, 0], pix[sel, 1], :3] = pupil
    # 이미지에 써 넣는다 (내보낼 때 바뀐 픽셀이 들어가게 새 이미지로)
    m = me.materials[mi]
    node = next(n for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image and any(l.to_socket.name == 'Base Color' for l in n.outputs['Color'].links))
    import bpy
    img = bpy.data.images.new(node.image.name + '_eye', w, h, alpha=True)
    img.pixels.foreach_set(tex.ravel())
    img.pack()
    node.image = img
    log(f'eye corner: pupil ellipse r=({rx:.3f},{rz:.3f}), painted {int(sel.sum())} texels')


def mirror_eye(obj, src_c, dst_c, rx, rz, log=print):
    """dst 눈(사용자: 왼쪽 눈 끝이 파여 보인다)을 괜찮은 src 눈의 좌우 반전으로 바꾼다 (텍셀 단위).
    dst 둘레 삼각형을 UV 공간에 래스터화해 텍셀마다 3D 위치를 구하고, 얼굴 가운데(두 눈 중점 x) 기준 거울 위치에서 가장 가까운
    src 텍셀 색을 가져온다. 타원 반지름 rx·rz 안은 그대로 바꾸고 가장자리 15% 는 섞는다."""
    import bpy
    from mathutils import Vector
    from mathutils.kdtree import KDTree
    me = obj.data
    imgs = base_color_images(me)
    me.calc_loop_triangles()
    uvd = me.uv_layers.active.data
    V = np.array([v.co[:] for v in me.vertices])
    cx = (src_c.x + dst_c.x) / 2

    def texels(center, scale):
        out = {}
        for t in me.loop_triangles:
            if t.material_index not in imgs:
                continue
            P = V[list(t.vertices)]
            c = P.mean(0)
            if ((c[0] - center.x) / (rx * scale)) ** 2 + ((c[2] - center.z) / (rz * scale)) ** 2 > 1.0 or c[1] > center.y + 0.1:
                continue
            arr, w, h = imgs[t.material_index]
            UV = np.array([uvd[li].uv[:] for li in t.loops])
            px_ = np.stack([UV[:, 0] * w - 0.5, UV[:, 1] * h - 0.5], 1)
            x0, x1 = int(np.floor(px_[:, 0].min())), int(np.ceil(px_[:, 0].max()))
            y0, y1 = int(np.floor(px_[:, 1].min())), int(np.ceil(px_[:, 1].max()))
            e1, e2 = px_[1] - px_[0], px_[2] - px_[0]
            den = e1[0] * e2[1] - e2[0] * e1[1]
            if abs(den) < 1e-9 or x1 - x0 > 200 or y1 - y0 > 200:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
            dxp, dyp = gx - px_[0, 0], gy - px_[0, 1]
            a_ = (dxp * e2[1] - e2[0] * dyp) / den
            b_ = (e1[0] * dyp - dxp * e1[1]) / den
            ins = (a_ >= -0.01) & (b_ >= -0.01) & (a_ + b_ <= 1.01) & (gx >= 0) & (gx < w) & (gy >= 0) & (gy < h)
            pos = P[0] + a_[ins, None] * (P[1] - P[0]) + b_[ins, None] * (P[2] - P[0])
            lst = out.setdefault(t.material_index, ([], []))
            lst[0].append(pos)
            lst[1].append(np.stack([gy[ins], gx[ins]], 1))
        return {k: (np.concatenate(a), np.concatenate(b)) for k, (a, b) in out.items() if a}

    src = texels(src_c, 1.6)
    dst = texels(dst_c, 1.35)
    if not src or not dst:
        log('mirror eye: texels not found')
        return
    smi = max(src, key=lambda k: len(src[k][0]))
    spos, spix = src[smi]
    sarr = imgs[smi][0]
    scol = sarr[spix[:, 0], spix[:, 1], :3]

    def skin(c):
        return (c[:, 0] > 0.55) & (c[:, 0] - c[:, 2] > 0.06) & (c[:, 1] > 0.4)
    # 눈 위쪽 끝(속눈썹 선 꼭대기): src 눈 가운데 열에서 눈 중심부터 위로 올라가며 눈 아닌(피부) 텍셀만 나오는 첫 높이. 그 위(눈썹)는 안 건드린다
    col_ = (np.abs(spos[:, 0] - src_c.x) < rx * 0.5)
    ne = col_ & ~skin(scol)
    zs = np.sort(spos[ne, 2][spos[ne, 2] > src_c.z])
    top = src_c.z + rz * 0.6
    if len(zs):
        gaps = np.nonzero(np.diff(zs) > 0.01)[0]
        top = zs[gaps[0]] if len(gaps) else zs[-1]
    zcap = top + 0.006
    # 거울 위치의 src 표면 점을 BVH 로 찾아 그 삼각형의 UV 를 무게중심 보간하고 텍스처를 이중선형으로 읽는다
    # (가장 가까운 텍셀 하나를 가져오면 가장자리가 계단지고 점이 튄다)
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import barycentric_transform
    tris_s = [t for t in me.loop_triangles if t.material_index == smi
              and ((V[list(t.vertices)].mean(0)[0] - src_c.x) / (rx * 1.7)) ** 2 + ((V[list(t.vertices)].mean(0)[2] - src_c.z) / (rz * 1.7)) ** 2 < 1.0]
    tv = [[Vector(V[i]) for i in t.vertices] for t in tris_s]
    tuv = [[Vector((uvd[li].uv[0], uvd[li].uv[1], 0.0)) for li in t.loops] for t in tris_s]
    verts_flat = [v for tri in tv for v in tri]
    bvh = BVHTree.FromPolygons(verts_flat, [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tv))])
    sh, sw = sarr.shape[0], sarr.shape[1]

    def bilinear(u, v):
        x = (u % 1.0) * sw - 0.5
        y = (v % 1.0) * sh - 0.5
        x0, y0 = int(np.floor(x)), int(np.floor(y))
        fx, fy = x - x0, y - y0
        x0c, x1c = min(max(x0, 0), sw - 1), min(max(x0 + 1, 0), sw - 1)
        y0c, y1c = min(max(y0, 0), sh - 1), min(max(y0 + 1, 0), sh - 1)
        c = (sarr[y0c, x0c, :3] * (1 - fx) * (1 - fy) + sarr[y0c, x1c, :3] * fx * (1 - fy)
             + sarr[y1c, x0c, :3] * (1 - fx) * fy + sarr[y1c, x1c, :3] * fx * fy)
        return c
    n = 0
    for mi, (pos, pix) in dst.items():
        arr = imgs[mi][0].copy()
        cur = arr[pix[:, 0], pix[:, 1], :3]
        new = np.empty_like(cur)
        okm = np.zeros(len(pos), bool)
        for i, p_ in enumerate(pos):
            if p_[2] >= zcap:
                continue
            hit = bvh.find_nearest(Vector((2 * cx - p_[0], p_[1], p_[2])), 0.03)
            if hit[0] is None:
                continue
            ti = hit[2]
            a3, b3, c3 = tv[ti]
            uvp = barycentric_transform(hit[0], a3, b3, c3, tuv[ti][0], tuv[ti][1], tuv[ti][2])
            new[i] = bilinear(uvp[0], uvp[1])
            okm[i] = True
        # 둘 다 피부인 곳은 그대로 (경계 자국이 안 생긴다). 눈썹 높이(zcap) 위는 안 건드린다
        sel = okm & ~(skin(cur) & skin(new))
        arr[pix[sel, 0], pix[sel, 1], :3] = new[sel]
        n += int(sel.sum())
        m = me.materials[mi]
        node = next(nd for nd in m.node_tree.nodes if nd.type == 'TEX_IMAGE' and nd.image and any(l.to_socket.name == 'Base Color' for l in nd.outputs['Color'].links))
        img = bpy.data.images.new(node.image.name + '_eye', arr.shape[1], arr.shape[0], alpha=True)
        img.pixels.foreach_set(arr.ravel())
        img.pack()
        node.image = img
        imgs[mi] = (arr, arr.shape[1], arr.shape[0])
    log(f'mirror eye: eye top z={top:.3f} (center {src_c.z:.3f})')
    log(f'mirror eye: copied {n} texels (face center x={cx:+.3f})')
