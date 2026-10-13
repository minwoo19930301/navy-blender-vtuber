"""
'일하는 척' 리액션 소품: 헤드폰 + 노트북 (+ 항상 보이는 책상·idle 키보드) → public/props.glb

  Blender --background --python blender/props_export.py [-- OUT.glb] [--no-fit] [--hair-glb PATH]

- 모든 모양은 three 좌표(Y 위, 정면 +Z, 캐릭터 왼쪽 +x)로 직접 만들고 마지막에 Blender 좌표(x, -z, y)로 옮긴다.
  glTF 내보내기가 Y-up 으로 되돌리므로 three 에서 읽으면 그대로다.
- 헤드폰: 노드 'headphones' 의 원점 = 머리 꼭대기 앵커(navy-rig.json joints.head_top). 앱은 anchors.headTop 의 자식으로 그대로 붙인다.
  머리카락 바깥 윤곽을 public/navy.glb 에서 재서 띠가 머리카락을 안 뚫게 맞추고, 컵은 귀 바깥에 얹는다.
- 노트북: 노드 'laptop' 의 원점 = 밑판 바닥 가운데, +Z = 사용자 쪽 앞, 힌지는 뒤(-Z). 'laptop_lid' 는 힌지에 원점을 둔 뚜껑이고
  노드 회전이 열린 상태(105°)다. 닫은 상태는 항등 회전이라 앱이 항등 → 열림으로 보간해 뚜껑을 열 수 있다.
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = Path(argv[0]).resolve() if argv and not argv[0].startswith('--') else ROOT / 'public' / 'props.glb'
HAIR_GLB = Path(argv[argv.index('--hair-glb') + 1]) if '--hair-glb' in argv else ROOT / 'public' / 'navy.glb'
FIT = '--no-fit' not in argv

# ───────────────────────── 치수 (three 월드 단위, 머리 폭 ±0.78 기준)
HEAD_C = np.array([0.0, 1.95])         # 띠 곡선의 중심 (x, y): 귀 높이
BAND_Z = 0.12                          # 띠가 놓이는 평면의 z (귀 높이)
BAND_TILT = -0.12                      # 위로 갈수록 뒤로 눕는 기울기 (z / y): 레퍼런스처럼 정수리 뒤쪽을 지난다
CUP_Y = 1.96                           # 컵 중심 높이 (귀 관절 높이: 눈 y 2.0 바로 아래)
CUP_Z = 0.22                           # 컵 중심 z (옆면 측정: 귀 가운데는 머리 중심보다 앞)
EAR_X = 0.74                           # 귀 바깥 x (측정으로 덮어쓴다)
CUP_R_SCALE = 0.62                     # 컵 반지름 배율 (레퍼런스 컵 높이 = 머리 폭의 0.41)
CUP_D_SCALE = 0.7                      # 컵 깊이(X) 배율
DESK_TOP = 0.28                        # 책상 윗면 y (idle 손목 높이 - 0.02)
DESK_X, DESK_Z0, DESK_Z1, DESK_BOTTOM = 2.6, -0.45, 1.5, -0.7   # 책상 x 반폭(화면 밖까지 이어져 옆면이 안 보인다), 뒤·앞 가장자리 z, 바닥 y
LAPTOP_W, LAPTOP_D = 1.56, 1.04        # 밑판 폭·깊이
LAPTOP_BASE_H = 0.085
LID_H, LID_T = 0.86, 0.055              # 뚜껑 길이·두께
LID_OPEN = math.radians(105)

# 머티리얼 색 (sRGB 헥스). 레퍼런스의 남색 소품: 재킷보다 살짝 밝고 푸르다
COL = {
    'hp_shell': '3a4468', 'hp_pad': '474f72', 'hp_band': '343d62', 'hp_plate': '454e74',
    'lap_body': '2d3558', 'lap_deck': '20274a', 'lap_key': '181d38', 'lap_pad': '343c60',
    'lap_screen': '0a0e22', 'lap_hinge': '3a4266', 'hp_cushion': '3a4060', 'desk': 'b8946e',
}


def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_lin(h):
    return tuple(srgb_to_lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))


MATS = {}


def mat(name, rough=0.82, **kw):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*hex_lin(COL[name]), 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = 0
    for k, v in kw.items():
        if k in b.inputs:
            b.inputs[k].default_value = v
    MATS[name] = m
    return m


# ───────────────────────── 메시 빌더 (three 좌표 → Blender 오브젝트)
def to_b(v):
    """three (x, y, z) → Blender (x, -z, y)"""
    v = np.asarray(v, float)
    return np.stack([v[..., 0], -v[..., 2], v[..., 1]], axis=-1)


def make_obj(name, verts, faces, material, parent=None, loc=(0, 0, 0), smooth=True):
    """verts: three 좌표 (정점은 loc 기준 상대 좌표). 면은 바깥에서 볼 때 반시계가 되도록 쓴다(뒤집힘은 recalc 로 바로잡는다)"""
    me = bpy.data.meshes.new(name)
    me.from_pydata(to_b(np.asarray(verts)).tolist(), [], [list(map(int, f)) for f in faces])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    me.materials.append(material)
    if parent is not None:
        ob.parent = parent
    ob.location = to_b(loc).tolist() if loc is not None else (0, 0, 0)
    return ob


class MB:
    """정점·면 모으기"""
    def __init__(self):
        self.v = []
        self.f = []

    def add(self, verts, faces):
        o = len(self.v)
        self.v.extend(np.asarray(verts, float).tolist())
        self.f.extend([[i + o for i in f] for f in faces])
        return o

    def grid(self, pts, closed_u=False, closed_v=False, cap_u0=False, cap_u1=False):
        """pts[u][v] 격자 → 사각형 면. u 방향 양끝을 막을 수 있다"""
        pts = np.asarray(pts, float)
        nu, nv = pts.shape[:2]
        o = len(self.v)
        self.v.extend(pts.reshape(-1, 3).tolist())
        idx = lambda i, j: o + (i % nu if closed_u else i) * nv + (j % nv if closed_v else j)
        for i in range(nu - (0 if closed_u else 1)):
            for j in range(nv - (0 if closed_v else 1)):
                self.f.append([idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)])
        for cap, i in ((cap_u0, 0), (cap_u1, nu - 1)):
            if cap:
                c = pts[i].mean(axis=0)
                ci = len(self.v)
                self.v.append(c.tolist())
                for j in range(nv if closed_v else nv - 1):
                    self.f.append([idx(i, j), idx(i, j + 1), ci] if i == 0 else [idx(i, j + 1), idx(i, j), ci])
        return o


def rrect(w, h, r, n=5):
    """둥근 사각 단면 (폭 w, 높이 h, 모서리 반지름 r). 반시계, 점 4n 개"""
    r = min(r, w / 2, h / 2)
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for k in range(n):
            a = math.radians(a0 + 90 * k / (n - 1))
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


def sweep(path, section, up_hint, closed=False, caps=True):
    """path: (N,3) 중심선, section: (M,2) 단면 (a = 법선쪽 up_hint 가 아니라 side 방향, b = up_hint 방향).
    단면 좌표 (s, u): s = 진행 방향과 up_hint 에 수직인 옆 방향, u = up_hint 방향"""
    path = np.asarray(path, float)
    n = len(path)
    tang = np.gradient(path, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    mb = MB()
    rings = []
    up = np.asarray(up_hint, float)
    for i in range(n):
        side = np.cross(tang[i], up)
        side /= np.linalg.norm(side)
        u = np.cross(side, tang[i])
        rings.append([path[i] + side * s + u * v for s, v in section])
    mb.grid(rings, closed_v=True, cap_u0=caps, cap_u1=caps, closed_u=closed)
    return mb


def lathe(profile, axis_dir, center, up, seg=64, scale=(1, 1)):
    """프로필 [(축 방향 거리 a, 반지름 r)] 을 axis_dir 둘레로 돌린 회전체. scale = (up 방향, 나머지 방향) 타원 배율"""
    ax = np.asarray(axis_dir, float)
    ax /= np.linalg.norm(ax)
    e1 = np.asarray(up, float)
    e1 = e1 - ax * np.dot(e1, ax)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(ax, e1)
    rings = []
    for a, r in profile:
        ring = []
        for k in range(seg):
            t = 2 * math.pi * k / seg
            ring.append(np.asarray(center) + ax * a + e1 * (r * math.cos(t) * scale[0]) + e2 * (r * math.sin(t) * scale[1]))
        rings.append(ring)
    mb = MB()
    mb.grid(rings, closed_v=True, cap_u0=abs(profile[0][1]) > 1e-6, cap_u1=abs(profile[-1][1]) > 1e-6)
    return mb


def rbox_mb(cx, cy, cz, sx, sy, sz, r, seg=4):
    """둥근 상자 (반치수 sx, sy, sz, 모서리 반지름 r) — 구 한 조각을 잘라 붙이는 대신 8 모서리를 구면으로 부풀린 격자"""
    mb = MB()
    r = min(r, sx, sy, sz)
    # 면마다 격자를 만들되 정점을 모서리 구에 투영: 단순하게 각 정점을 (내부 상자) + r * 단위벡터 로 만든다
    n = seg * 2 + 1
    ts = [(-1 + 2 * i / (n - 1)) for i in range(n)]
    inner = np.array([sx - r, sy - r, sz - r])

    def pt(u, v, w):
        p = np.array([u, v, w], float)
        q = np.clip(p, -1, 1)
        v3 = q * np.array([sx, sy, sz])
        c = np.clip(v3, -inner, inner)
        d = v3 - c
        L = np.linalg.norm(d)
        if L > 1e-9:
            d = d / L * r
        return np.array([cx, cy, cz]) + c + d
    for axis in range(3):
        for sign in (-1, 1):
            g = []
            for a in ts:
                row = []
                for b in ts:
                    uvw = [0, 0, 0]
                    uvw[axis] = sign
                    uvw[(axis + 1) % 3] = a
                    uvw[(axis + 2) % 3] = b
                    row.append(pt(*uvw))
                g.append(row)
            if (axis + (sign > 0)) % 2 == 0:
                g = g[::-1]
            mb.grid(g)
    return mb


# ───────────────────────── 측정: 머리카락·귀
def measure_head():
    """navy.glb 에서 머리카락 윤곽(띠 평면 슬랩, 각도별 최대 반지름)과 귀 바깥 x 를 잰다. 없으면 기본값"""
    default = None
    if not (FIT and HAIR_GLB.exists()):
        return default
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(HAIR_GLB))
    new = [o for o in bpy.data.objects if o not in before]
    pts = []
    for o in new:
        if o.type == 'MESH' and 'body' in o.name:
            n = len(o.data.vertices)
            a = np.empty(n * 3)
            o.data.vertices.foreach_get('co', a)
            a = a.reshape(-1, 3)
            m = np.array(o.matrix_world)
            w = a @ m[:3, :3].T + m[:3, 3]
            pts.append(np.stack([w[:, 0], w[:, 2], -w[:, 1]], axis=1))  # Blender → three
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    if not pts:
        return default
    p = np.concatenate(pts)
    return p[p[:, 1] > 1.55]  # 머리 영역


def hair_profile(p, zb, half=0.12, bins=90):
    """띠 평면(z=zb ± half)의 x-y 점들을 HEAD_C 기준 극좌표로 바꿔 각도(0..180°) 구간별 최대 반지름"""
    s = p[np.abs(p[:, 2] - (zb + BAND_TILT * (p[:, 1] - HEAD_C[1]))) < half]
    d = s[:, :2] - HEAD_C
    ang = np.degrees(np.arctan2(d[:, 1], np.abs(d[:, 0])))  # 좌우 대칭으로 접어 0..90°
    r = np.linalg.norm(d, axis=1)
    prof = np.zeros(bins)
    edges = np.linspace(-30, 90, bins + 1)
    for i in range(bins):
        m = (ang >= edges[i]) & (ang < edges[i + 1]) & (d[:, 1] > -0.3)
        prof[i] = r[m].max() if m.any() else np.nan
    centers = (edges[:-1] + edges[1:]) / 2
    ok = ~np.isnan(prof)
    prof = np.interp(centers, centers[ok], prof[ok])
    # 이동 최대 → 가우시안: 띠가 머리카락 울퉁불퉁을 따라 출렁이지 않게
    k = 2
    pm = np.array([prof[max(0, i - k):i + k + 1].max() for i in range(bins)])
    g = np.exp(-0.5 * (np.arange(-6, 7) / 3.0) ** 2)
    g /= g.sum()
    pad = np.pad(pm, 6, mode='edge')
    ps = np.convolve(pad, g, mode='valid')
    return centers, np.maximum(ps, pm * 0.995)


# ───────────────────────── 헤드폰
def build_headphones(head, rig):
    O = np.array(rig['joints']['head_top'], float)   # 노드 원점 (three 월드)
    root = bpy.data.objects.new('headphones', None)
    bpy.context.scene.collection.objects.link(root)
    root.location = to_b(O).tolist()

    ear_x = EAR_X
    if head is not None:
        e = head[(np.abs(head[:, 1] - CUP_Y) < 0.12) & (np.abs(head[:, 2] - CUP_Z) < 0.2)]
        if len(e):
            ear_x = float(np.abs(e[:, 0]).max())
    print('[props] 귀 바깥 x', round(ear_x, 3))

    # ---- 띠 중심선: 머리카락 윤곽 + 여유, 각도 θ_end..180-θ_end
    bins_c, prof = hair_profile(head, BAND_Z) if head is not None else (np.linspace(-30, 90, 90), None)
    if prof is None:
        prof = np.interp(bins_c, [-30, 0, 45, 90], [0.8, 0.82, 1.0, 1.1])
    th_end = 22.0      # 띠가 컵 쪽으로 내려가는 끝 각도 (수평 기준)
    pad_t, shell_t = 0.022, 0.042      # 안쪽 패드·바깥 껍질 두께 (반지름 방향): 머리카락과 띠 사이 여유 ~0.02
    gap = 0.004
    angs = np.linspace(th_end, 180 - th_end, 90)
    path = []
    rin = []
    for a in angs:
        fa = a if a <= 90 else 180 - a
        r_h = float(np.interp(fa, bins_c, prof))
        rc = r_h + gap + pad_t + shell_t / 2
        rin.append(r_h + gap)
        yy = HEAD_C[1] + rc * math.sin(math.radians(a))
        path.append([HEAD_C[0] + rc * math.cos(math.radians(a)), yy, BAND_Z + BAND_TILT * (yy - HEAD_C[1])])
    path = np.array(path)
    print('[props] 띠 꼭대기 y', round(path[:, 1].max() + shell_t / 2, 3), '반경(옆)', round(float(prof[np.searchsorted(bins_c, 0)]), 3))
    # 껍질: 바깥 쪽 납작한 둥근 띠 (폭 z 0.15, 두께 shell_t)
    sect = rrect(0.12, shell_t, 0.02, 5)
    # 단면 좌표 (s = 옆(z), u = 반지름 바깥쪽): up_hint 는 평면 법선이 아니라 반지름 방향이어야 하므로 점마다 계산한다
    band = MB()
    rings = []
    tang = np.gradient(path, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    zax = np.array([0, 0, 1.0])
    for i, c in enumerate(path):
        outward = np.cross(tang[i], zax)   # 호가 반시계(위로 향함)이면 바깥 쪽
        outward /= np.linalg.norm(outward)
        if np.dot(outward, c - np.array([HEAD_C[0], HEAD_C[1], BAND_Z])) < 0:
            outward = -outward
        rings.append([c + zax * s + outward * u for s, u in sect])
    band.grid(rings, closed_v=True, cap_u0=True, cap_u1=True)
    make_obj('hp_band', np.array(band.v) - O, band.f, mat('hp_band', 0.8), root, (0, 0, 0))

    # 안쪽 패드 (머리 위쪽 호만, 두툼한 쿠션)
    pad = MB()
    rings = []
    sel = [i for i, a in enumerate(angs) if 52 <= a <= 128]
    sel_path = path[sel]
    sect2 = rrect(0.10, pad_t * 1.15, 0.01, 5)
    for k, i in enumerate(sel):
        c = path[i]
        outward = (c - np.array([HEAD_C[0], HEAD_C[1], BAND_Z]))
        outward[2] = 0
        outward /= np.linalg.norm(outward)
        # 패드 중심: 껍질 안쪽 면 바로 안
        cc = c - outward * (shell_t / 2 + pad_t * 0.5 - 0.004)
        sc = 0.55 + 0.45 * math.sin(math.pi * k / (len(sel) - 1)) ** 0.5   # 양끝은 가늘게
        rings.append([cc + zax * (s * sc) + outward * (u * (0.8 + 0.2 * sc)) for s, u in sect2])
    pad.grid(rings, closed_v=True, cap_u0=True, cap_u1=True)
    make_obj('hp_band_pad', np.array(pad.v) - O, pad.f, mat('hp_pad', 0.9), root, (0, 0, 0))

    # ---- 컵 + 요크 (좌우)
    for side, nm in ((1, 'L'), (-1, 'R')):
        ax = np.array([side, 0, 0.0])
        up = np.array([0, 1.0, 0])
        c_in = np.array([side * (ear_x + 0.0), CUP_Y, CUP_Z])    # 컵 안쪽 면 (귀 바깥에 닿는다)
        sc = (1.1, 1.0)                                       # 위아래로 조금 길쭉
        RS, DS = CUP_R_SCALE, CUP_D_SCALE
        # 쿠션 링 (귀를 감싸는 도넛, 컵보다 살짝 밝은 #3a4060): 컵과 머리 사이
        ring_prof = []
        R0, rt = 0.30 * RS * 1.1, 0.085 * RS
        for k in range(17):
            t = 2 * math.pi * k / 16
            ring_prof.append(((0.03 + rt * 0.55 * (1 + math.sin(t)) * 0.9) * DS, R0 + rt * math.cos(t)))
        padm = lathe(ring_prof, ax, c_in, up, seg=64, scale=sc)
        make_obj(f'hp_pad_{nm}', np.array(padm.v) - O, padm.f, mat('hp_cushion', 0.92), root, (0, 0, 0))
        # 쉘 (둥근 퍽): 프로필 (a: 안쪽 면에서 바깥으로 거리, r: 반지름), 바깥 면은 살짝 볼록
        prof = [(0.045, 0.0), (0.045, 0.30), (0.075, 0.31), (0.11, 0.312), (0.15, 0.30), (0.19, 0.275), (0.22, 0.23), (0.238, 0.18), (0.246, 0.11), (0.25, 0.0)]
        # 촘촘히 보간하고 이동 평균으로 각진 곳만 둥글린다 (양 끝점 고정)
        pa = np.array(prof)
        tt = np.linspace(0, len(pa) - 1, 48)
        ia = np.interp(tt, np.arange(len(pa)), pa[:, 0])
        ir = np.interp(tt, np.arange(len(pa)), pa[:, 1])
        def smooth(v, it=3):
            v = v.copy()
            for _ in range(it):
                v[1:-1] = (v[:-2] + 2 * v[1:-1] + v[2:]) / 4
            return v
        prof = list(zip(smooth(ia) * 1.12 * DS, smooth(ir) * 1.15 * RS))
        shell = lathe(prof, ax, c_in, up, seg=64, scale=sc)
        make_obj(f'hp_cup_{nm}', np.array(shell.v) - O, shell.f, mat('hp_shell', 0.85, **{'Sheen Weight': 0.0}), root, (0, 0, 0))
        # 바깥 면 원판 장식 (살짝 밝은 남색)
        d0 = 0.2755 * 1.12 / 1.12 * DS
        pl = lathe([(d0, 0.0), (d0, 0.18 * RS), (d0 + 0.009, 0.18 * RS), (d0 + 0.011, 0.0)], ax, c_in, up, seg=48, scale=sc)
        make_obj(f'hp_plate_{nm}', np.array(pl.v) - O, pl.f, mat('hp_plate', 0.85), root, (0, 0, 0))
        # 요크: 띠 끝에서 컵 위쪽 바깥 가장자리로 내려오는 슬라이더 (둥근 막대)
        end = path[0] if side > 0 else path[-1]
        top = np.array([side * (ear_x + 0.09), CUP_Y + 0.37 * RS * sc[0] * 1.15 * 1.0, CUP_Z])
        mid = np.array([end[0] + (top[0] - end[0]) * 0.35, (end[1] + top[1]) / 2, BAND_Z + (CUP_Z - BAND_Z) * 0.5])
        yp = []
        for k in range(14):
            u = k / 13
            q = (1 - u) ** 2 * end + 2 * (1 - u) * u * mid + u ** 2 * top
            yp.append(q)
        ys = sweep(np.array(yp), rrect(0.09, 0.04, 0.018, 4), (0, 0, 1))
        make_obj(f'hp_yoke_{nm}', np.array(ys.v) - O, ys.f, mat('hp_band', 0.85), root, (0, 0, 0))
    return root


# ───────────────────────── 노트북
def build_laptop():
    root = bpy.data.objects.new('laptop', None)
    bpy.context.scene.collection.objects.link(root)
    W, D, H = LAPTOP_W, LAPTOP_D, LAPTOP_BASE_H
    foot = 0.012
    # 밑판 (둥근 상자)
    b = rbox_mb(0, foot + H / 2, 0, W / 2, H / 2, D / 2, 0.035, 4)
    make_obj('laptop_base', b.v, b.f, mat('lap_body', 0.7, **{'Sheen Weight': 0.15}), root)
    # 키보드 덮개 면 (살짝 어두운 패널) — 윗면 위에 얇게
    top_y = foot + H
    deck = rbox_mb(0, top_y + 0.002, -0.07, W / 2 - 0.1, 0.004, D / 2 - 0.15, 0.003, 2)
    make_obj('laptop_deck', deck.v, deck.f, mat('lap_deck', 0.8), root)
    # 키: 5줄 × 13칸, 윗면이 살짝 좁은 사다리꼴 기둥
    keys = MB()
    pitch, kw = 0.1, 0.086
    rows = 5
    cols = 13
    x0 = -(cols - 1) * pitch / 2
    z0 = -D / 2 + 0.17
    for r in range(rows):
        for c in range(cols):
            cx = x0 + c * pitch
            cz = z0 + r * pitch
            h = 0.022
            kb = rbox_mb(cx, top_y + 0.004 + h / 2, cz, kw / 2, h / 2, kw / 2, 0.012, 2)
            keys.add(kb.v, kb.f)
    # 스페이스바 줄
    sb = rbox_mb(0.0, top_y + 0.004 + 0.011, z0 + rows * pitch, 0.32, 0.011, kw / 2, 0.01, 2)
    keys.add(sb.v, sb.f)
    make_obj('laptop_keys', keys.v, keys.f, mat('lap_key', 0.55), root)
    # 트랙패드
    tp = rbox_mb(0, top_y + 0.004, D / 2 - 0.2, 0.3, 0.004, 0.14, 0.006, 2)
    make_obj('laptop_pad', tp.v, tp.f, mat('lap_pad', 0.6), root)
    # 힌지 (뒤쪽 가는 원통)
    hy = top_y + 0.01
    hz = -D / 2 + 0.012
    hinge = lathe([(-0.55, 0.0), (-0.55, 0.036), (0.55, 0.036), (0.55, 0.0)], (1, 0, 0), (0, hy, hz), (0, 1, 0), seg=24)
    make_obj('laptop_hinge', hinge.v, hinge.f, mat('lap_hinge', 0.5), root)

    # 뚜껑: 힌지에 원점. 닫힌 상태(밑판 위에 눕힌 모양)로 만들고 노드 회전으로 연다
    lid_root = bpy.data.objects.new('laptop_lid', None)
    bpy.context.scene.collection.objects.link(lid_root)
    lid_root.parent = root
    pivot = np.array([0, hy, hz])
    lid_root.location = to_b(pivot).tolist()
    lid_root.rotation_mode = 'XYZ'
    lid_root.rotation_euler = (-LID_OPEN, 0, 0)       # three X 회전 = Blender X 회전 (위 주석)
    lid = rbox_mb(0, LID_T / 2 + 0.004, LID_H / 2 + 0.02, W / 2, LID_T / 2, LID_H / 2, 0.026, 4)
    make_obj('laptop_lid_shell', lid.v, lid.f, mat('lap_body', 0.68, **{'Sheen Weight': 0.15}), lid_root)
    # 화면: 안쪽 면(뚜껑이 닫혔을 때 아래 면, y = 0.004)에 얇은 검은 판
    scr = rbox_mb(0, 0.0045, LID_H / 2 + 0.03, W / 2 - 0.07, 0.003, LID_H / 2 - 0.08, 0.01, 2)
    make_obj('laptop_screen', scr.v, scr.f, mat('lap_screen', 0.25), lid_root)
    return root


# ───────────────────────── 책상·키보드 (idle 에도 항상 보인다)
def build_desk():
    """책상 슬랩: 윗면 y = DESK_TOP, x ±DESK_X, z DESK_Z0..DESK_Z1. 밑단·옆구리·검은 조각을 윗면과 앞면이 가린다.
    노드 'desk' 의 원점은 월드 원점. 색은 나무색으로 구우고, 앱이 idle 에서는 배경색 쪽으로 섞는다"""
    root = bpy.data.objects.new('desk', None)
    bpy.context.scene.collection.objects.link(root)
    cx, cz = 0.0, (DESK_Z0 + DESK_Z1) / 2
    sx, sy, sz = DESK_X, (DESK_TOP - DESK_BOTTOM) / 2, (DESK_Z1 - DESK_Z0) / 2
    b = rbox_mb(cx, DESK_TOP - sy, cz, sx, sy, sz, 0.03, 3)
    make_obj('desk_slab', b.v, b.f, mat('desk', 0.85), root)
    return root


def build_keyboard():
    """idle 용 납작한 키보드: 노드 원점 = 밑판 바닥 가운데, +Z = 사용자(카메라) 쪽"""
    root = bpy.data.objects.new('keyboard', None)
    bpy.context.scene.collection.objects.link(root)
    W, D, H = 1.15, 0.42, 0.045
    b = rbox_mb(0, H / 2, 0, W / 2, H / 2, D / 2, 0.02, 3)
    make_obj('kb_base', b.v, b.f, mat('lap_body', 0.7), root)
    keys = MB()
    cols, rows = 12, 4
    pitch = (W - 0.1) / cols
    kw = pitch * 0.82
    x0 = -(cols - 1) * pitch / 2
    z0 = -D / 2 + 0.07
    kp = (D - 0.14) / (rows)
    for r in range(rows):
        for c in range(cols):
            kb = rbox_mb(x0 + c * pitch, H + 0.009, z0 + r * kp, kw / 2, 0.009, kp * 0.41, 0.006, 2)
            keys.add(kb.v, kb.f)
    make_obj('kb_keys', keys.v, keys.f, mat('lap_key', 0.55), root)
    return root


def main():
    rig = json.load(open(ROOT / 'public' / 'navy-rig.json'))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    head = measure_head()
    if head is not None:
        print('[props] 머리 영역 정점', len(head), 'y 범위', head[:, 1].min().round(2), head[:, 1].max().round(2))
    build_headphones(head, rig)
    build_laptop()
    build_desk()
    build_keyboard()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(OUT), export_format='GLB', export_yup=True, export_apply=True,
        export_materials='EXPORT', export_cameras=False, export_lights=False, export_extras=False,
    )
    print('[props] wrote', OUT, round(OUT.stat().st_size / 1024), 'KB')


main()
