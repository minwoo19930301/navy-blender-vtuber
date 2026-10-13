"""새 손 메시 붙이기 (rig.py 가 불러 쓴다. Blender 안에서만 돈다).

입력 계약 (손 담당과의 약속)
  rig/hand/hand_R.glb   캐릭터 오른손 메시 (텍스처 포함, 한 메시).
  rig/hand/hand_R.json  {"pts": [[x,y,z] * 21], "palm_normal": [x,y,z] (선택), "palm_len": 0.24 (선택), "frame": "..."}
      pts 는 MediaPipe 손 21점 순서이고, 좌표계는 두 가지 중 하나다.
        - TRELLIS 관례 (손 담당의 hand_R.json, "frame" 에 "X축 -90" 이 들어 있다): GLB 파일 좌표 (x,y,z) 를 그대로 Blender Z-up 으로 읽는다.
          불러올 때 눕혀 나오는 메시를 X 로 -90° 세우면 이 점들과 같은 공간이 된다.
        - glTF 관례 ("frame" 없음): GLB 에 저장된 glTF 좌표 (Y 위). 불러온 메시와 같은 공간.
      0 손목, 1~4 엄지(CMC,MCP,IP,TIP), 5~8 검지(MCP,PIP,DIP,TIP), 9~12 중지, 13~16 약지, 17~20 새끼.
      palm_normal 이 없으면 오른손 기준 cross(pts[5]-pts[0], pts[17]-pts[0]) 방향을 손바닥 바깥으로 본다
      (오른손 손바닥을 내 쪽으로 향하고 손가락을 위로 들면 엄지가 오른쪽 → 법선이 나를 향한다).
      palm_len: 손목→중지 MCP 길이를 앱 단위로 이만큼 맞춘다 (없으면 기본값 PALM_LEN).
왼손은 오른손을 x 로 거울 반전해서(면 방향 뒤집기) 만든다.

배치: 손목 점이 소매 끝 안쪽 (손목 관절 − INSET·팔뚝축) 에 오고, 중지 방향이 팔뚝 축, 손바닥은 몸 안쪽을 본다.
뼈: hand(손목→중지 MCP), thumb1..3, index1..3, middle1..3, ring1..3, pinky1..3 (각 뼈 머리 = 랜드마크, 꼬리 = 다음 랜드마크).
가중치: 손가락 사슬별 거리 게이트 + 관절 이등분 평면 램프. 손목 안쪽(소매 속)은 forearm 과 섞는다.
"""
import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

PALM_LEN = 0.28       # 손목→중지 MCP 앱 단위 길이 (손 너비 ≈ 얼굴 너비의 0.4)
SKIN = None           # (r,g,b) sRGB 0..1. rig.py 가 몸 텍스처에서 재서 넣는다. 있으면 손 재질 색을 이 값으로 바꾼다
INSET = 0.09          # 손목 점을 소매 안쪽으로 밀어 넣는 깊이
FLARE_K, FLARE_LEN = 1.45, 0.10   # 소매 끝 근처 손목을 소매 안쪽 반지름에 맞추는 배율, 그 배율에서 1.0 까지 풀리는 길이
CUFF_R = 0.165                     # 소매 안쪽 반지름 (바깥 0.19)
FINGERS = ['thumb', 'index', 'middle', 'ring', 'pinky']
FIRST = {'thumb': 1, 'index': 5, 'middle': 9, 'ring': 13, 'pinky': 17}


def ss(x, a, b):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / (np.linalg.norm(v) + 1e-12)


def available(hand_dir):
    d = Path(hand_dir)
    return (d / 'hand_R.glb').exists() and (d / 'hand_R.json').exists()


def _gltf_to_bl(p):
    return np.array([p[0], -p[2], p[1]], dtype=np.float64)


def _import_mesh(glb, stand=False):
    """GLB 를 불러 메시 하나를 월드 변환까지 구워서 돌려준다 (불러온 다른 오브젝트는 지운다)"""
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    new = [o for o in bpy.context.scene.objects if o not in before]
    meshes = [o for o in new if o.type == 'MESH']
    assert len(meshes) == 1, f'손 GLB 는 메시 하나여야 한다: {len(meshes)}'
    m = meshes[0]
    m.parent = None
    mw = m.matrix_world.copy()
    m.data.transform(mw)
    if stand:
        m.data.transform(Matrix.Rotation(math.radians(-90), 4, 'X'))   # TRELLIS 가 눕혀 낸 메시를 세운다
    m.matrix_world = Matrix.Identity(4)
    for o in new:
        if o is not m:
            bpy.data.objects.remove(o)
    return m


def _flat_png(path, rgb8, n=8):
    """단색 n×n PNG (표준 라이브러리만 사용)"""
    import struct
    import zlib

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)

    row = b'\x00' + bytes(rgb8) * n
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', n, n, 8, 2, 0, 0, 0)) \
        + chunk(b'IDAT', zlib.compress(row * n)) + chunk(b'IEND', b'')
    Path(path).write_bytes(png)


def set_skin(obj, rgb):
    """손 재질 알베도를 단색(sRGB 0..1)으로 바꾼다. 앱 재질이 baseColorFactor 를 무시하고 map 만 쓰므로 작은 단색 텍스처로 준다"""
    import tempfile
    rgb8 = tuple(int(round(c * 255)) for c in rgb)
    path = Path(tempfile.gettempdir()) / f'navy_skin_{rgb8[0]}_{rgb8[1]}_{rgb8[2]}.png'
    _flat_png(path, rgb8)
    img = bpy.data.images.load(str(path))
    img.colorspace_settings.name = 'sRGB'
    img.pack()
    for m in obj.data.materials:
        m.use_nodes = True
        nt = m.node_tree
        bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
        for l in list(bsdf.inputs['Base Color'].links):
            nt.links.remove(l)
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])


WRIST_KEEP = 0.07  # 손바닥 밑에서 남길 손목 길이 (세운 손 좌표, 손 길이 1 기준)


def trim_wrist(obj, z_cut=-0.49, iters=3):
    """손목 자른 면(뚜껑)을 지우고 열린 가장자리 고리를 라플라시안으로 3번 다듬는다 (세운 손 좌표, 자른 면 z≈-0.5)"""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    caps = [f for f in bm.faces if all(v.co.z < z_cut for v in f.verts)]
    bmesh.ops.delete(bm, geom=caps, context='FACES_ONLY')
    bm.verts.ensure_lookup_table()
    ring = [v for v in bm.verts if v.is_boundary]
    for _ in range(iters):
        new = {}
        for v in ring:
            nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
            if nb:
                new[v] = sum((n.co for n in nb), Vector()) / len(nb)
        for v, c in new.items():
            v.co = v.co * 0.5 + c * 0.5
    bm.to_mesh(obj.data)
    bm.free()


def flare_wrist(obj, W, fa, s):
    """소매 끝 근처 손목을 소매 안쪽 반지름으로 벌린다. 자른 면은 소매 속 깊이 있어 안 보이지만,
    소매 끝 높이의 손목이 소매 안쪽보다 가늘어 어두운 속이 비치므로 그 둘레를 키운다.
    축 방향 a(손목 점 기준)가 소매 끝 이하이면 FLARE_K 배, 소매 끝 + FLARE_LEN 에서 1.0"""
    me = obj.data
    a_ = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get('co', a_)
    P = a_.reshape(-1, 3).astype(np.float64)
    ax = unit(fa)
    t = (P - W) @ ax
    rad = P - W - np.outer(t, ax)
    a_c = INSET - 0.02                   # 소매 끝 면의 축 위치 (손목 점 기준)
    w = 1 - ss(t, a_c - 0.02, a_c + FLARE_LEN)
    k = 1 + (FLARE_K - 1) * w
    # 이미 소매 안쪽 반지름보다 큰 곳은 더 키우지 않는다
    r = np.linalg.norm(rad, axis=1)
    k = np.minimum(k, np.maximum(1.0, CUFF_R / np.maximum(r, 1e-6)))
    P2 = W + np.outer(t, ax) + rad * k[:, None]
    me.vertices.foreach_set('co', P2.astype(np.float32).ravel())
    me.update()


def load_and_place(hand_dir, J, cuff_info, palm_len=None, log=print):
    """양손을 불러 앱 좌표에 놓는다. {tag: {'obj': 메시 오브젝트, 'pts': (21,3) 앱 좌표}} 를 돌려준다"""
    hand_dir = Path(hand_dir)
    meta = json.load(open(hand_dir / 'hand_R.json'))
    stand = 'X축 -90' in str(meta.get('frame', ''))
    conv = (lambda p: np.asarray(p, dtype=np.float64)) if stand else _gltf_to_bl
    pts0 = np.array([conv(p) for p in meta['pts']])
    assert len(pts0) == 21, '손 관절 점은 21개여야 한다'
    palm_len = palm_len or meta.get('palm_len') or PALM_LEN
    if 'palm_normal' in meta:
        n0 = unit(conv(meta['palm_normal']))
    else:
        n0 = unit(np.cross(pts0[5] - pts0[0], pts0[17] - pts0[0]))
    out = {}
    for side, tag in ((1, 'L'), (-1, 'R')):
        obj = _import_mesh(hand_dir / 'hand_R.glb', stand)
        if stand:
            # 손목 그루터기를 손바닥 밑(관절 0)에서 조금만 남기고 자른다. 길게 두면 손이 아래팔과 각을 이룰 때
            # 그루터기가 소매 옆구리를 뚫고 나와 분홍 조각으로 보인다
            trim_wrist(obj, z_cut=float(pts0[0][2]) - WRIST_KEEP)
        obj.name = f'navy_hand_{tag}'
        obj.data.name = f'navy_hand_{tag}'
        pts, n = pts0.copy(), n0.copy()
        if tag == 'L':
            # 거울: x 반전 + 면 뒤집기
            obj.data.transform(Matrix.Scale(-1, 4, Vector((1, 0, 0))))
            obj.data.flip_normals()
            pts[:, 0] *= -1
            n[0] *= -1
        fa = np.asarray(cuff_info[tag]['fa'])
        f_h = unit(pts[9] - pts[0])
        n_h = unit(n - f_h * (n @ f_h))
        H = np.stack([np.cross(f_h, n_h), f_h, n_h], axis=1)          # 손 공간 기저 (열)
        n_t = np.array([-side, 0.0, 0.0])
        n_t = unit(n_t - fa * (n_t @ fa))
        Tm = np.stack([np.cross(fa, n_t), fa, n_t], axis=1)           # 앱 공간 기저
        R = Tm @ H.T
        s = palm_len / np.linalg.norm(pts[9] - pts[0])
        W = np.array(J[f'wrist_{tag}']) - fa * INSET
        placed = (pts - pts[0]) @ R.T * s + W
        M = np.eye(4)
        M[:3, :3] = R * s
        M[:3, 3] = W - (pts[0] @ R.T) * s
        obj.data.transform(Matrix(M.tolist()))
        flare_wrist(obj, W, fa, s)
        obj.data.update()
        for m in obj.data.materials:
            m.use_backface_culling = False
        if SKIN is not None:
            set_skin(obj, SKIN)
        out[tag] = {'obj': obj, 'pts': placed, 'palm': n_t}
        log(f'hand {tag}: placed, scale {s:.3f}, wrist ({W[0]:+.3f},{W[1]:+.3f},{W[2]:+.3f})')
    return out


def chains(pts):
    """손가락 사슬: {이름: [(bone_name_suffix, head, tail), ...]} (이름 접미사는 1..3)"""
    res = {}
    for f in FINGERS:
        i0 = FIRST[f]
        res[f] = [(f'{f}{k + 1}', pts[i0 + k], pts[i0 + k + 1]) for k in range(3)]
    return res


def add_bones(eb, pts, tag, J, bone):
    """edit 모드 뼈 만들기. hand 뼈는 rig.py 가 이미 만들어 두었고 꼬리를 중지 MCP 로 옮긴다"""
    hb = eb[f'hand_{tag}']
    hb.tail = Vector(pts[9])
    for f, ch in chains(pts).items():
        prev = None
        for k, (name, h, t) in enumerate(ch):
            if k == 0:
                bone(f'{name}_{tag}', Vector(h), Vector(t), f'hand_{tag}', False)
            else:
                bone(f'{name}_{tag}', Vector(h), Vector(t), f'{ch[k - 1][0]}_{tag}', True)
    for f, ch in chains(pts).items():
        for name, h, t in ch:
            J[f'{name}_{tag}'] = Vector(h)
    J[f'hand_tip_{tag}'] = Vector(pts[9])


def weights(obj, pts, J, tag, names):
    """손 메시 정점 가중치 (N, B). names = 뼈 이름 순서(armature 전체)"""
    idx = {n: i for i, n in enumerate(names)}
    me = obj.data
    a = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get('co', a)
    P = a.reshape(-1, 3).astype(np.float64)
    N = len(P)
    W0 = np.array(J[f'wrist_{tag}'])
    scale = np.linalg.norm(pts[9] - pts[0])

    def seg(a_, b_):
        ab = b_ - a_
        L = np.linalg.norm(ab)
        u = ab / L
        t = (P - a_) @ u
        c = a_ + np.clip(t, 0, L)[:, None] * u
        return np.linalg.norm(P - c, axis=1), t

    # 사슬 게이트: palm(손바닥 선분 여러 개) vs 다섯 손가락
    r_palm = 0.55 * scale
    d_palm = np.minimum.reduce([seg(pts[0], pts[i])[0] for i in (5, 9, 13, 17)] + [seg(pts[5], pts[9])[0], seg(pts[9], pts[13])[0], seg(pts[13], pts[17])[0]]) / r_palm
    dn = {'palm': d_palm}
    for f, ch in chains(pts).items():
        r_f = 0.22 * scale if f != 'thumb' else 0.26 * scale
        dn[f] = np.minimum.reduce([seg(h, t)[0] for _, h, t in ch]) / r_f
    keys = ['palm'] + FINGERS
    inv = np.stack([np.maximum(dn[k], 0.05) ** -4.0 for k in keys], axis=1)
    c = inv / inv.sum(axis=1, keepdims=True)

    Wt = np.zeros((N, len(names)))
    hand_w = c[:, 0].copy()
    for j, f in enumerate(FINGERS):
        ch = chains(pts)[f]
        cf = c[:, j + 1]
        # 손바닥 → 첫 마디: MCP(엄지는 CMC) 관절 이등분 평면
        base = pts[FIRST[f]]
        d_in = unit(base - pts[0]) if f != 'thumb' else unit(pts[2] - pts[1])
        d1 = unit(ch[0][2] - ch[0][1])
        bw = 0.18 * scale
        a1 = ss((P - base) @ unit(d_in + d1), -bw, bw)
        d2 = unit(ch[1][2] - ch[1][1])
        d3 = unit(ch[2][2] - ch[2][1])
        a2 = ss((P - ch[1][1]) @ unit(d1 + d2), -0.12 * scale, 0.12 * scale)
        a3 = ss((P - ch[2][1]) @ unit(d2 + d3), -0.12 * scale, 0.12 * scale)
        hand_w += cf * (1 - a1)
        Wt[:, idx[f'{ch[0][0]}_{tag}']] += cf * a1 * (1 - a2)
        Wt[:, idx[f'{ch[1][0]}_{tag}']] += cf * a1 * a2 * (1 - a3)
        Wt[:, idx[f'{ch[2][0]}_{tag}']] += cf * a1 * a2 * a3
    # 손목: 소매 속 부분은 forearm 과 섞는다
    fa = unit(pts[0] - (np.array(J[f'elbow_{tag}'])))
    wr = ss((P - W0) @ fa, -0.05, 0.05)       # 0 = 소매 안쪽(forearm), 1 = 손 쪽
    Wt[:, idx[f'hand_{tag}']] += hand_w * wr
    Wt[:, idx[f'forearm_{tag}']] += hand_w * (1 - wr)
    for f in FINGERS:
        for k in (1, 2, 3):
            Wt[:, idx[f'{f}{k}_{tag}']] *= wr
        Wt[:, idx[f'forearm_{tag}']] += (1 - wr) * 0  # 손가락이 소매 속에 있을 일은 없다
    s = Wt.sum(axis=1, keepdims=True)
    Wt = Wt / np.maximum(s, 1e-9)
    # 최대 4 영향
    thr = np.sort(Wt, axis=1)[:, -4][:, None]
    Wt = np.where(Wt >= thr, Wt, 0.0)
    return Wt / np.maximum(Wt.sum(axis=1, keepdims=True), 1e-9)
