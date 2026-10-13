"""
TRELLIS 로 만든 캐릭터 메시에 뼈대를 넣어 three.js 용 스킨드 GLB 를 만든다.

  Blender --background --python rig/rig.py -- trellis/apose-s1-t42d.glb public/wip/rig.glb \
      [--preview shots/body_rig/pose] [--wview shots/body_rig/w] [--no-hand] [--hand-dir rig/hand]

입력: 텍스처 입힌 TRELLIS GLB(눕혀서 나옴, 높이 1), rig/front.json(정면 직교 렌더 픽셀↔모델 좌표),
      rig/front-landmarks.json(MediaPipe 포즈·얼굴), rig/front-hands.json(손).
출력: OUT(.glb) (Y 위, 책상=재킷 밑단 y=0, 정면 +Z) + OUT-rig.json (관절·얼굴 오버레이 위치).

순서
1. 세우고 앱 단위로 키운다 (재킷 밑단 → 머리 끝 = APP_H). 밑단 아래(바지)는 잘라 낸다.
2. 정점 병합(UV 는 면 모서리별이라 유지된다) → 면 방향 통일 → 데시메이트.
3. MediaPipe 2D 점을 정면 직교 좌표로 옮기고, 깊이는 그 자리에서 앞·뒤로 쏜 레이 교점의 가운데로 잡는다.
3a. 소매 중심선: 표면 샘플로 높이별 소매 바깥 끝·깊이 평균을 재서 어깨·팔꿈치·손목 관절을 소매 한가운데로 옮긴다.
4. 생성된 손(벙어리장갑)은 소매 끝(피부 텍스처가 시작되는 곳) 안쪽에서 잘라 낸다(+ 소매 속 안감 껍질 제거). 새 손 메시는 소매 안으로 끼워 넣는다.
4b. 겨드랑이: 팔(소매 통)과 옆구리가 얇은 막으로 붙어 있어서 팔 면/몸통 면 사이 모서리를 끊는다(정점 복제). 분류는 소매 축까지 거리(타원 보정) + 이웃 다수결.
    --prune 을 주면 겉에서 안 보이는 안쪽 껍질도 지운다(기본 꺼짐: 효과가 작았다).
5. 뼈대: hips·spine·chest·neck·head, 양쪽 shoulder·upper_arm·forearm·hand + (임시 손가락 | 새 손의 손가락 15개).
6. 가중치: bone heat 대신 결정적 절차 가중치 (rig/weights.py). 뼈 선분까지의 거리를 반경으로 나눠 팔/몸통을 가르고,
   관절 면(이등분 평면)을 기준으로 매끈하게 섞는다. 머리·머리카락은 head 1.0.
7. 새 손이 있으면(rig/hand/hand_R.glb + hand_R.json) rig/handattach.py 가 가져와 L 은 거울로 만들고, 손가락 뼈를 달고 가중치를 준다.
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
argv = sys.argv[sys.argv.index('--') + 1:]
SRC, OUT = argv[0], Path(argv[1]).resolve()


def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


PREVIEW = opt('--preview')          # 포즈별 렌더 접두사 (shots/body_rig/pose → pose-idle-front.png ...)
WVIEW = opt('--wview')              # 가중치 색 렌더 접두사
HAND_DIR = Path(opt('--hand-dir', HERE / 'hand'))
USE_HAND = '--no-hand' not in argv and (HAND_DIR / 'hand_R.glb').exists() and (HAND_DIR / 'hand_R.json').exists()
PALM_LEN = float(opt('--palm-len', 0)) or None   # 새 손 손목→중지 MCP 길이 (앱 단위, 없으면 hand json 값)
sys.path.insert(0, str(HERE))
import handattach as HA  # noqa: E402
import weights as W_  # noqa: E402

APP_H = 3.05          # 재킷 밑단(책상) → 머리 끝 높이. 예전 모델 프레이밍과 같다
TARGET_TRIS = 120000  # 실시간 오버레이용 삼각형 수

ortho = json.load(open(HERE / 'front.json'))
lm = json.load(open(HERE / 'front-landmarks.json'))
hands = json.load(open(HERE / 'front-hands.json'))


def log(*a):
    print('[rig]', *a, flush=True)


def activate(o):
    for ob in bpy.context.selected_objects:
        ob.select_set(False)
    bpy.context.view_layer.objects.active = o
    o.select_set(True)


# ───────────────────────── 1. 불러와 세우기
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
assert len(meshes) == 1, f'메시가 하나여야 한다: {len(meshes)}'
body = meshes[0]
body.name = 'navy_body'
body.data.name = 'navy_body'
for o in list(bpy.context.scene.objects):
    if o is not body:
        bpy.data.objects.remove(o)
body.parent = None
# 눕혀 나온 메시를 세운다 (front_ortho.py 와 같은 회전)
body.matrix_world = Matrix.Rotation(math.radians(-90), 4, 'X') @ body.matrix_world
activate(body)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def px_to_model(px, py):
    """정면 직교 렌더 픽셀 → 모델 좌표 (x, z). 카메라는 -Y 에서 본다 (화면 오른쪽 = +x)"""
    r, s = ortho['res'], ortho['ortho_scale']
    return ortho['cx'] + (px - r / 2) / r * s, ortho['cz'] - (py - r / 2) / r * s


# 재킷 밑단 높이: 정면 렌더에서 가운데 열을 아래로 훑어 셔츠(흰색)가 끝나고 바지가 시작하는 곳 근처.
# 포즈 엉덩이(23·24)는 만화 비율에서 부정확해서, 손목 높이와 이미지에서 잰 밑단 비율을 쓴다
P = lm['pose']
wrist_py = (P[15][1] + P[16][1]) / 2
hem_py = wrist_py + 78  # front-hands.png 기준: 밑단이 손목보다 약 78px 아래 (밑단 ≈ 890px)
_, hem_z = px_to_model(512, hem_py)
top_z = max((body.matrix_world @ v.co).z for v in body.data.vertices)
S = APP_H / (top_z - hem_z)
log(f'hem_z={hem_z:.3f} top_z={top_z:.3f} scale={S:.3f}')


def to_app(x, y, z):
    """모델 좌표 → 앱 좌표 (Blender Z 위). 밑단이 z=0, 가운데 x=0"""
    return Vector((x * S, y * S, (z - hem_z) * S))


body.data.transform(Matrix.Translation((0, 0, -hem_z)))
body.data.transform(Matrix.Scale(S, 4))
body.data.update()

# 몸통 폭 보정: 머리에 비해 몸이 좁다. 목 밑동 아래로 x 를 최대 14% 넓힌다 (머리는 그대로)
TORSO_WIDEN = 0.14
_, _sh_z = px_to_model(512, (P[11][1] + P[12][1]) / 2)
NECK_BASE = to_app(0, 0, _sh_z).z + 0.05


def widen(z):
    """높이 z 에서 x 배율: 목 밑동 이상 1.0, 그 0.15 아래부터 1+TORSO_WIDEN"""
    t = np.clip((np.asarray(z) - NECK_BASE) / -0.15, 0.0, 1.0)
    return 1 + TORSO_WIDEN * t * t * (3 - 2 * t)


_a = np.empty(len(body.data.vertices) * 3, np.float32)
body.data.vertices.foreach_get('co', _a)
_a = _a.reshape(-1, 3)
_a[:, 0] *= widen(_a[:, 2])
body.data.vertices.foreach_set('co', _a.ravel())
body.data.update()
log(f'torso widen: neck_base z={NECK_BASE:.3f}, x scale up to {1 + TORSO_WIDEN:.2f}')

# ───────────────────────── 2. 자르기·병합·면 방향·데시메이트
bm = bmesh.new()
bm.from_mesh(body.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4 * S)
cut = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, -0.02), plane_no=(0, 0, 1), clear_inner=True)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
# 열린 가장자리(앞섶·깃·소매 끝)의 가시 조각을 깎고 톱니를 편다 (rig/edgeclean.py)
import edgeclean  # noqa: E402
_n_spk, _n_rel = edgeclean.clean_edges(bm)
log(f'edge clean: spikes removed {_n_spk}, boundary verts relaxed {_n_rel}')
bm.to_mesh(body.data)
bm.free()
n0 = len(body.data.polygons)
if n0 > TARGET_TRIS:
    dm = body.modifiers.new('dec', 'DECIMATE')
    dm.ratio = TARGET_TRIS / n0
    activate(body)
    bpy.ops.object.modifier_apply(modifier=dm.name)
log(f'faces {n0:,} -> {len(body.data.polygons):,}')
for p in body.data.polygons:
    p.use_smooth = True

# ───────────────────────── 3. 관절 3D 위치
bvh = BVHTree.FromObject(body, bpy.context.evaluated_depsgraph_get())


def joint(px, py, depth_bias=0.0):
    """픽셀 → 앱 좌표. 깊이(y)는 정면·뒷면 레이 교점의 가운데 (+bias 는 앞쪽 비율, 0=가운데)"""
    x, z = px_to_model(px, py)
    p = to_app(x, 0, z)
    front = bvh.ray_cast(Vector((p.x, -50, p.z)), Vector((0, 1, 0)))
    back = bvh.ray_cast(Vector((p.x, 50, p.z)), Vector((0, -1, 0)))
    if front[0] is None or back[0] is None:
        return Vector((p.x, 0, p.z))
    yf, yb = front[0].y, back[0].y
    return Vector((p.x, (yf + yb) / 2 + (yf - yb) * depth_bias, p.z))


def pmid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


F = lm['face']
J = {}
# 몸통: 어깨선과 턱을 기준으로 잡는다
shL, shR = joint(*P[11][:2]), joint(*P[12][:2])
chin_px = F[152][:2] if F else (512, P[0][1] + 90)
chin = joint(*chin_px)
J['hips'] = Vector((0, (shL.y + shR.y) / 2, 0.25))
J['chest'] = Vector((0, J['hips'].y, (shL.z + shR.z) / 2 - 0.25))
J['neck'] = Vector((0, J['hips'].y, (shL.z + shR.z) / 2 + 0.05))
J['head'] = Vector((0, chin.y - 0.05, chin.z + 0.05))
J['head_top'] = Vector((0, J['head'].y, max(v.co.z for v in body.data.vertices)))
for side, tag, si, ei, wi in ((1, 'L', 11, 13, 15), (-1, 'R', 12, 14, 16)):
    sh = shL if tag == 'L' else shR
    J[f'shoulder_{tag}'] = sh
    J[f'elbow_{tag}'] = joint(*P[ei][:2])
    J[f'wrist_{tag}'] = joint(*P[wi][:2])
    J[f'clavicle_{tag}'] = Vector((side * 0.18, J['chest'].y, sh.z + 0.02))

# 손: 찾은 쪽 손 랜드마크를 쓰고, 못 찾은 쪽은 반대 손을 몸 가운데 기준으로 좌우 반전해 손목에 맞춘다
hand_pts = {}
for tag in ('L', 'R'):
    h = hands.get(tag)
    if h:
        hand_pts[tag] = [p[:2] for p in h['pts']]
for tag, other in (('L', 'R'), ('R', 'L')):
    if tag not in hand_pts and other in hand_pts:
        src = hand_pts[other]
        w_other = src[0]
        w_this = P[15][:2] if tag == 'L' else P[16][:2]
        hand_pts[tag] = [(w_this[0] - (p[0] - w_other[0]), w_this[1] + (p[1] - w_other[1])) for p in src]
        log(f'hand {tag}: mirrored from {other}')
# 양손 다 못 찾으면(손을 새 손으로 갈아 끼울 때는 생성 손 랜드마크가 필요 없다) 아래팔 연장선으로 임시 점을 만든다
for tag, ei, wi in (('L', 13, 15), ('R', 14, 16)):
    if tag not in hand_pts:
        (ex, ey), (wx, wy) = P[ei][:2], P[wi][:2]
        dx, dy = wx - ex, wy - ey
        ln = max(1e-6, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / ln, dy / ln
        px = lambda t, o=0.0: (wx + ux * t * ln - uy * o * ln, wy + uy * t * ln + ux * o * ln)  # noqa: E731
        pts = [px(0)] * 21
        for i, (t, o) in {1: (0.1, -0.12), 2: (0.2, -0.18), 3: (0.3, -0.2), 4: (0.4, -0.2),
                          5: (0.35, -0.06), 10: (0.55, 0.0), 12: (0.75, 0.0), 14: (0.55, 0.03), 16: (0.72, 0.04), 17: (0.33, 0.08)}.items():
            pts[i] = px(t, o)
        hand_pts[tag] = pts
        log(f'hand {tag}: synthesized from forearm')
for tag in ('L', 'R'):
    hp = hand_pts[tag]
    J[f'hand_{tag}'] = J[f'wrist_{tag}']
    J[f'knuckle_{tag}'] = joint(*pmid(hp[5], hp[17]))          # 검지·새끼 MCP 가운데
    J[f'finger_mid_{tag}'] = joint(*pmid(hp[10], hp[14]))      # 중지·약지 PIP 가운데
    J[f'finger_tip_{tag}'] = joint(*pmid(hp[12], hp[16]))
    J[f'thumb1_{tag}'] = joint(*hp[2])
    J[f'thumb2_{tag}'] = joint(*hp[3])
    J[f'thumb_tip_{tag}'] = joint(*hp[4])
    J[f'thumb0_{tag}'] = joint(*hp[1])
for k in J:
    J[k] = Vector((J[k].x * float(widen(J[k].z)), J[k].y, J[k].z))   # 몸을 넓힌 만큼 어깨·팔꿈치·손목 x 도 같이 옮긴다
for k, v in J.items():
    log(f'  {k:16s} ({v.x:+.3f}, {v.y:+.3f}, {v.z:+.3f})')


# ───────────────────────── 3-0. 코 다듬기
# TRELLIS 코는 큼직한 공이라 그림자가 세게 진다. 레퍼런스 코는 뺨선을 거의 안 넘는 작은 혹이다.
# 코끝(눈 중심과 입 사이에서 가장 앞쪽 정점) 반경 NOSE_R 안의 앞쪽 돌출을 뺨 고리(NOSE_R~NOSE_R2)에 맞춘 평면 기준으로 NOSE_K 배로 줄인다
NOSE_R, NOSE_R2, NOSE_K = 0.09, 0.13, 0.5


def soften_nose():
    if not F:
        return
    _, ez = px_to_model(512, (F[133][1] + F[362][1]) / 2)
    _, mz = px_to_model(512, F[13][1])
    ez, mz = to_app(0, 0, ez).z, to_app(0, 0, mz).z
    P_ = coords()
    cand = np.nonzero((np.abs(P_[:, 0]) < 0.25) & (P_[:, 2] > mz) & (P_[:, 2] < ez) & (P_[:, 1] < 0.0))[0]
    if not len(cand):
        return
    tip = P_[cand[np.argmin(P_[cand, 1])]]
    d = np.linalg.norm(P_ - tip, axis=1)
    ring = (d >= NOSE_R) & (d <= NOSE_R2) & (P_[:, 1] < 0.12)
    if ring.sum() < 10:
        log('nose: 뺨 고리 점이 모자라 건너뜀')
        return
    # 뺨 평면 y = a x + b z + c (최소제곱)
    A = np.c_[P_[ring, 0], P_[ring, 2], np.ones(ring.sum())]
    coef = np.linalg.lstsq(A, P_[ring, 1], rcond=None)[0]
    inner = d < NOSE_R
    plane_y = P_[:, 0] * coef[0] + P_[:, 2] * coef[1] + coef[2]
    fwd = plane_y - P_[:, 1]                       # 평면보다 앞(-y)으로 나온 양
    t = np.clip(d / NOSE_R, 0, 1)
    k = NOSE_K + (1 - NOSE_K) * (t * t * (3 - 2 * t))   # 코끝 0.55 → 반경에서 1.0
    newy = np.where(inner & (fwd > 0), plane_y - fwd * k, P_[:, 1])
    P_[:, 1] = newy
    body.data.vertices.foreach_set('co', P_.astype(np.float32).ravel())
    body.data.update()
    log(f'nose: tip ({tip[0]:+.3f},{tip[1]:+.3f},{tip[2]:+.3f}), moved {int((inner & (fwd > 0)).sum())} verts, max pullback {float((fwd * (1 - k))[inner].max()):.3f}')


# 코 다듬기는 코 모양(공 → 작은 혹)이 눈에 띄는 얼굴 영역만 바꾸므로 BVH(관절·얼굴 점 깊이)를 다시 만든다
def coords():
    a = np.empty(len(body.data.vertices) * 3, np.float32)
    body.data.vertices.foreach_get('co', a)
    return a.reshape(-1, 3).astype(np.float64)


# 머리 이식 모델(--baked-face)의 코는 이미 작고, headswap.py 에서 살짝 뾰족하게 다듬었다 → 줄이지 않는다
if '--baked-face' not in argv:
    soften_nose()

# ───────────────────────── 3-1. 3D 입 (rig/mouth.py): 구운 입선을 따라 가르고 턱 뼈로 연다
import mouth as MO  # noqa: E402
MOUTH = None
JAW_DROP = 0.12   # 입을 다 벌렸을 때 아래 입술이 내려가는 거리 (앱 단위, 입 폭 ≈ 0.3)
if '--baked-face' in argv and F:
    _cl, _cr = joint(*F[291][:2], depth_bias=0.5), joint(*F[61][:2], depth_bias=0.5)
    _mc, _mw = (_cl + _cr) / 2, (_cl - _cr).length
    _near = min(body.data.polygons, key=lambda p_: (p_.center - _mc).length)
    _mi = _near.material_index
    MO.remove_inner_behind_mouth(body, _mc, _mw, log)
    _lip = (joint(*F[13][:2], depth_bias=0.5) + joint(*F[14][:2], depth_bias=0.5)) / 2
    # 만화 얼굴이라 입꼬리 랜드마크가 구운 미소 선과 어긋난다 → 텍스처에서 미소 선을 찾아 쓴다 (못 찾으면 랜드마크)
    _found = MO.smile_curve_from_texture(body, _mc, _mw, _mi, log)
    _curve, _xr = MO.rip(body, _cl, _cr, _lip, _mc, _mw, log, found=_found)
    MOUTH = dict(curve=_curve, xr=_xr, center=_mc, mw=_mw, chin_z=joint(*F[152][:2], depth_bias=0.5).z)

# ───────────────────────── 3-2. 옆머리·눈 다듬기 (rig/hairtrim.py, 사용자 요청)
import hairtrim as HT  # noqa: E402
if '--baked-face' in argv and F:
    _eR = (joint(*F[133][:2], depth_bias=0.5) + joint(*F[33][:2], depth_bias=0.5)) / 2   # 캐릭터 오른눈 (화면 왼쪽)
    _eL = (joint(*F[362][:2], depth_bias=0.5) + joint(*F[263][:2], depth_bias=0.5)) / 2
    HT.trim_sideburns(body, (_eR.z + _eL.z) / 2, log)
    # 왼눈 흰자 칠하기(HT.blacken_eye_corner)는 눈동자가 너무 커 보여 되돌렸다 (사용자 요청)
bvh = BVHTree.FromObject(body, bpy.context.evaluated_depsgraph_get())

# ───────────────────────── 3a. 소매 중심선으로 팔 관절 다듬기
# MediaPipe 어깨·팔꿈치·손목은 실루엣 바깥쪽에 찍혀 있어서 뼈가 소매 밖으로 나간다.
# 표면을 고르게 뿌린 점으로 높이(z)마다 소매 바깥 끝과 깊이 평균을 재서 중심선을 만든다.
def surface_samples(n=300000, seed=0):
    me = body.data
    me.calc_loop_triangles()
    tri = np.array([t.vertices[:] for t in me.loop_triangles])
    a = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get('co', a)
    Pm = a.reshape(-1, 3).astype(np.float64)
    A, B, C_ = Pm[tri[:, 0]], Pm[tri[:, 1]], Pm[tri[:, 2]]
    area = np.linalg.norm(np.cross(B - A, C_ - A), axis=1)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(tri), n, p=area / area.sum())
    r1, r2 = np.sqrt(rng.random(n)), rng.random(n)
    return A[idx] * (1 - r1)[:, None] + B[idx] * (r1 * (1 - r2))[:, None] + C_[idx] * (r1 * r2)[:, None]


SLEEVE_R = 0.19   # 소매 반지름 (정면 렌더 폭에서 잰 값)


def sleeve_center(samples, side, z):
    """높이 z 에서 소매 중심 (x, y). 가장 바깥 소매 한 가닥만 본다 (몸통과 붙는 윗부분도 바깥 끝은 깨끗하다)"""
    m = (np.abs(samples[:, 2] - z) < 0.03) & (side * samples[:, 0] > 0.3)
    xs = side * samples[m, 0]
    xmax = np.percentile(xs, 99.7)
    q = samples[m][xs > xmax - 0.30]
    return side * (xmax - SLEEVE_R), float(q[:, 1].mean())


samp = surface_samples()
# 메시는 좌우 대칭이라 높이는 L 랜드마크로 통일한다 (R 랜드마크는 어깨가 더 낮게 찍혀 있다)
zS = {t: J['shoulder_L'].z for t in 'LR'}
zE = {t: J['elbow_L'].z for t in 'LR'}
for side, tag in ((1, 'L'), (-1, 'R')):
    for key, z in (('shoulder', zS[tag]), ('elbow', zE[tag])):
        x, y = sleeve_center(samp, side, z)
        log(f'{key}_{tag}: landmark ({J[f"{key}_{tag}"].x:+.3f}, {J[f"{key}_{tag}"].y:+.3f}) -> sleeve center ({x:+.3f}, {y:+.3f}) @z={z:.3f}')
        J[f'{key}_{tag}'] = Vector((x, y, z))
    J[f'clavicle_{tag}'] = Vector((side * 0.18, J['chest'].y, J[f'shoulder_{tag}'].z + 0.02))

# ───────────────────────── 3b. 색 샘플 → 손 자르기
def vertex_colors():
    """정점마다 텍스처 색 (sRGB 0..1). 정점에 붙은 모서리 UV 색의 평균"""
    me = body.data
    img = next(n.image for m in me.materials for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)[:, :, :3]
    nl = len(me.loops)
    uv = np.empty(nl * 2, np.float32)
    me.uv_layers.active.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2) % 1.0
    vi = np.empty(nl, np.int32)
    me.loops.foreach_get('vertex_index', vi)
    c = px[np.clip((uv[:, 1] * h).astype(int), 0, h - 1), np.clip((uv[:, 0] * w).astype(int), 0, w - 1)]
    c = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.maximum(c, 1e-6), 1 / 2.4) - 0.055)
    acc = np.zeros((len(me.vertices), 3))
    cnt = np.zeros(len(me.vertices))
    np.add.at(acc, vi, c)
    np.add.at(cnt, vi, 1)
    return acc / np.maximum(cnt, 1)[:, None]


_TEX = {}


def uv_srgb(uvs):
    """UV 목록 → 텍스처 색 (sRGB 0..1). 이미지는 처음 한 번만 읽어 둔다"""
    if 'px' not in _TEX:
        img = next(n.image for m in body.data.materials for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image)
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        _TEX['px'], _TEX['wh'] = px.reshape(h, w, 4)[:, :, :3], (w, h)
    w, h = _TEX['wh']
    uv = np.asarray(uvs, np.float64).reshape(-1, 2) % 1.0
    c = _TEX['px'][np.clip((uv[:, 1] * h).astype(int), 0, h - 1), np.clip((uv[:, 0] * w).astype(int), 0, w - 1)]
    return c   # img.pixels 는 이미 sRGB 값 그대로다 (vertex_colors 는 한 번 더 올려서 밝게 나온다)


NAVY = np.array([0.165, 0.18, 0.275])   # 재킷 감청 (구운 색 표본)


def navy_uv(uvs):
    """후보 UV 중 재킷 감청에 가장 가까운 한 점. 덮개 면이 피부·머리 칸을 밟지 않게 한다"""
    c = uv_srgb(uvs)
    d = np.sqrt(((c - NAVY) ** 2).sum(axis=1))
    k = int(np.argmin(d))
    navy_uv.dist = float(d[k])
    return uvs[k]


def coords():
    me = body.data
    a = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get('co', a)
    return a.reshape(-1, 3).astype(np.float64)


def is_skin(c):
    # 피부색: 복숭아(텍스처 보정 후)와 예전 분홍 둘 다 잡는다
    return (c[:, 0] > 0.6) & (c[:, 0] - c[:, 1] > 0.1) & (c[:, 0] - c[:, 2] > 0.12)


Pv, Cv = coords(), vertex_colors()
# 손 색: 얼굴(머리 높이)의 피부 정점 색 중앙값에 맞춘다
_sk = is_skin(Cv) & (Pv[:, 2] > 1.4)
HA.SKIN = tuple(float(x) for x in np.median(Cv[_sk], axis=0)) if _sk.sum() > 100 else None
log('skin color (sRGB 255):', None if HA.SKIN is None else tuple(round(x * 255) for x in HA.SKIN), 'verts', int(_sk.sum()))
LINER_DEPTH = 0.50   # 소매 속 안감을 걷어 내는 깊이 (팔꿈치 근처까지)
LINER_R = 0.125   # 소매 속 안감 반지름 (소매 겉 반지름 0.19 보다 안쪽)
CUFF_BACK = 0.04   # 자르는 면을 소매 끝에서 소매 안쪽으로 들이는 양
cuff_info = {}
for side, tag in ((1, 'L'), (-1, 'R')):
    E = np.array(J[f'elbow_{tag}'])
    x, y = sleeve_center(samp, side, 0.34)
    fa = np.array((x, y, 0.34)) - E
    fa /= np.linalg.norm(fa)
    t = (Pv - E) @ fa
    radial = np.linalg.norm(Pv - (E + t[:, None] * fa), axis=1)
    sk = is_skin(Cv) & (radial < 0.3) & (t > 0.3)
    t_skin = float(np.percentile(t[sk], 3))
    cuff_info[tag] = dict(t_skin=t_skin, fa=fa)
    old_w = Vector(J[f'wrist_{tag}'])
    Wn = Vector(E + fa * (t_skin - 0.02))
    shift = Wn - old_w
    for k in ('knuckle', 'finger_mid', 'finger_tip', 'thumb1', 'thumb2', 'thumb_tip', 'thumb0'):
        J[f'{k}_{tag}'] = J[f'{k}_{tag}'] + shift   # 임시 손 뼈는 손목과 함께 옮긴다
    J[f'wrist_{tag}'] = Wn
    J[f'hand_{tag}'] = Wn.copy()
    log(f'cuff {tag}: skin starts t={t_skin:.3f} z={(E + fa * t_skin)[2]:.3f}, skin verts {int(sk.sum())}, wrist -> ({Wn.x:+.3f},{Wn.y:+.3f},{Wn.z:+.3f})')


def cut_hand(tag):
    """소매 끝 안쪽에서 팔 축에 수직인 면으로 손 쪽을 잘라 낸다. 손목 관절은 소매 끝으로 옮긴다"""
    E = Vector(J[f'elbow_{tag}'])
    fa = Vector(cuff_info[tag]['fa'])
    t_cut = cuff_info[tag]['t_skin'] - CUFF_BACK
    co = E + fa * t_cut

    def region(p):
        t = (p - E).dot(fa)
        return abs(t - t_cut) < 0.6 and (p - E - fa * t).length < 0.45

    bm = bmesh.new()
    bm.from_mesh(body.data)
    faces = [f for f in bm.faces if all(region(v.co) for v in f.verts)]
    edges = list({e for f in faces for e in f.edges})
    verts = list({v for f in faces for v in f.verts})
    bmesh.ops.bisect_plane(bm, geom=verts + edges + faces, plane_co=co, plane_no=fa)
    dead = [v for v in bm.verts if (v.co - co).dot(fa) > 1e-5 and (v.co - E - fa * (v.co - E).dot(fa)).length < 0.45]
    bmesh.ops.delete(bm, geom=dead, context='VERTS')
    # 소매 속 안감(피부 껍질) 가장자리가 잘린 채 들쭉날쭉 보이므로 소매 끝 근처 안쪽 껍질을 걷어 낸다. 새 손의 손목이 채운다
    liner = [v for v in bm.verts if -LINER_DEPTH < (v.co - co).dot(fa) <= 1e-5 and (v.co - E - fa * (v.co - E).dot(fa)).length < LINER_R]
    bmesh.ops.delete(bm, geom=liner, context='VERTS')
    log(f'hand {tag} liner removed: {len(liner)} verts')
    # 잘린 가장자리 띠는 UV 가 줄무늬 칸에 걸려 해칭처럼 보인다. 바로 안쪽 소매 겉면의 UV 한 점(감청)으로 모은다
    uvl = bm.loops.layers.uv.active

    def tt(f):
        return (f.calc_center_median() - E).dot(fa)

    def rr(f):
        c_ = f.calc_center_median() - E
        return (c_ - fa * c_.dot(fa)).length
    ref = [f for f in bm.faces if t_cut - 0.16 < tt(f) < t_cut - 0.10 and 0.17 < rr(f) < 0.30]
    band = [f for f in bm.faces if t_cut - 0.10 <= tt(f) < t_cut + 1e-3 and rr(f) < 0.30]
    if ref and band:
        top = max(ref, key=lambda f: f.calc_center_median().z)   # 소매 윗면 한 칸의 UV (재킷 감청)
        us = [l[uvl].uv.copy() for l in top.loops]
        u0 = sum(us, type(us[0])((0, 0))) / len(us)
        for f in band:
            for l in f.loops:
                l[uvl].uv = u0
    log(f'hand {tag} cuff band uv fix: {len(band)} faces (ref {len(ref)})')
    # 잘리고 남은 떠돌이 조각 정리
    bm.verts.ensure_lookup_table()
    bm.to_mesh(body.data)
    bm.free()
    log(f'hand {tag} cut: removed {len(dead)} verts, plane t={t_cut:.3f}')


for tag in ('L', 'R'):
    cut_hand(tag)
body.data.update()


def recolor_stray_skin(z_max):
    """깃 아래 몸 메시의 피부색 면(잘린 생성 손의 잔해·소매 속 껍질)을 재킷 남색으로 칠한다.
    지우면 구멍이 나서 안쪽 껍질이 비친다 → 지우지 않고, 그 면들의 UV 를 텍스처의 깨끗한 남색 한 점으로 모은다.
    재질마다 자기 텍스처에서 색을 읽는다 (머리 이식 모델은 재질이 둘이다). 새 손은 이 뒤에 붙으니 영향이 없다."""
    me = body.data
    imgs = {}
    for mi, m in enumerate(me.materials):
        for n in (m.node_tree.nodes if m and m.node_tree else []):
            if n.type == 'TEX_IMAGE' and n.image:
                w, h = n.image.size
                px = np.empty(w * h * 4, np.float32)
                n.image.pixels.foreach_get(px)
                imgs[mi] = (px.reshape(h, w, 4), w, h)
                break
    uv = me.uv_layers.active.data
    skin, navy = [], []
    for poly in me.polygons:
        if poly.material_index not in imgs:
            continue
        arr, w, h = imgs[poly.material_index]
        u = sum(uv[i].uv[0] for i in poly.loop_indices) / poly.loop_total
        v = sum(uv[i].uv[1] for i in poly.loop_indices) / poly.loop_total
        r, g, b_ = arr[min(h - 1, int(v % 1.0 * h)), min(w - 1, int(u % 1.0 * w)), :3]
        if poly.center.z < z_max and r > 0.45 and r - b_ > 0.12:
            skin.append(poly)
        elif b_ - r > 0.05 and max(r, g, b_) < 0.35 and poly.center.z < z_max:
            navy.append((poly.material_index, (u, v), (r, g, b_)))
    if not skin or not navy:
        log('stray skin recolor: nothing to do')
        return
    # 남색 기준점: 남색 면 색의 중앙값에 가장 가까운 면의 UV (같은 재질 안에서)
    med = np.median(np.array([c for _, _, c in navy]), axis=0)
    by_mat = {}
    for mi, (u, v), c in navy:
        d = float(np.sum((np.array(c) - med) ** 2))
        if mi not in by_mat or d < by_mat[mi][0]:
            by_mat[mi] = (d, (u, v))
    any_uv = min(by_mat.values())[1]
    for poly in skin:
        tu, tv = by_mat.get(poly.material_index, (0, any_uv))[1]
        for i in poly.loop_indices:
            uv[i].uv = (tu, tv)
    log(f'stray skin faces recolored navy below z={z_max:.2f}: {len(skin)} (navy ref rgb {np.round(med, 3)})')


recolor_stray_skin(J['neck'].z - 0.12)


def recolor_clothes(z_max, mat_index=0):
    """재킷·셔츠를 영역으로 다시 칠한다 (누더기 같은 흰 줄·남색 얼룩 정리).
    재킷은 거의 한 가지 남색이라, 앞쪽 가운데 셔츠 띠(높이마다 흰색이 우세한 x 폭) 안은 흰색, 그 밖은 남색으로 정한다.
    해당 면의 UV 를 텍스처의 깨끗한 흰 점·남 점으로 모은다. 몸 재질(mat_index)·깃 아래만 바꾼다 (얼굴·목은 머리 재질이라 안 건드린다)."""
    me = body.data
    m = me.materials[mat_index]
    img = next(n.image for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    arr = px.reshape(h, w, 4)[:, :, :3]
    uv = me.uv_layers.active.data
    polys = [p_ for p_ in me.polygons if p_.material_index == mat_index and p_.center.z < z_max]
    cols, uvs_c = [], []
    for p_ in polys:
        u = sum(uv[i].uv[0] for i in p_.loop_indices) / p_.loop_total
        v = sum(uv[i].uv[1] for i in p_.loop_indices) / p_.loop_total
        cols.append(arr[min(h - 1, int(v % 1.0 * h)), min(w - 1, int(u % 1.0 * w))])
        uvs_c.append((u, v))
    cols = np.array(cols)
    ctr = np.array([p_.center[:] for p_ in polys])
    nrm = np.array([p_.normal[:] for p_ in polys])
    r_, g_, b_ = cols[:, 0], cols[:, 1], cols[:, 2]
    white = (r_ > 0.7) & (g_ > 0.7) & (b_ > 0.65)
    navy = (b_ - r_ > 0.04) & (np.maximum(np.maximum(r_, g_), b_) < 0.4)
    # 정면 판정: 이 메시는 면 방향이 다 맞지는 않아 법선 대신 위치로 본다 — 같은 높이 몸 단면의 앞쪽 절반(-Y)이고 법선이 옆을 향하지 않는 면
    yc = np.empty(len(ctr))
    for z0 in np.arange(ctr[:, 2].min(), z_max + 0.1, 0.1):
        sel = np.abs(ctr[:, 2] - z0) < 0.05
        if sel.any():
            yc[sel] = np.median(ctr[sel & (np.abs(ctr[:, 0]) < 0.5), 1]) if (sel & (np.abs(ctr[:, 0]) < 0.5)).any() else np.median(ctr[sel, 1])
    front = (ctr[:, 1] < yc) & (np.abs(nrm[:, 1]) > 0.35)
    # 높이마다 셔츠 반폭: 정면 흰 면의 |x| 80 번째 백분위 (위아래로 매끈하게)
    zb = np.arange(ctr[:, 2].min(), z_max + 0.05, 0.05)
    half = np.full(len(zb), np.nan)
    xb = np.arange(0.0, 0.5, 0.02)
    for i, z0 in enumerate(zb):
        band = front & (np.abs(ctr[:, 2] - z0) < 0.05)
        ax = np.abs(ctr[band, 0])
        wb = white[band]
        mid = ax < 0.06
        if band.sum() < 40 or not mid.any() or wb[mid].mean() < 0.5:
            continue
        # 가운데부터 바깥으로: 흰 면 비율이 절반 아래로 떨어지는 첫 칸이 셔츠 끝 (재킷 위 흰 줄에 덜 휘둘린다)
        edge = None
        for x0 in xb:
            sel = (ax >= x0) & (ax < x0 + 0.02)
            if sel.sum() >= 5 and wb[sel].mean() < 0.5:
                edge = x0
                break
        if edge is not None:
            half[i] = edge
    ok = ~np.isnan(half)
    if ok.sum() < 3:
        log('clothes recolor: shirt band not found, skipped')
        return
    half = np.interp(zb, zb[ok], half[ok])
    half = np.convolve(np.pad(half, 2, mode='edge'), np.ones(5) / 5, mode='valid')
    hz = np.interp(ctr[:, 2], zb, half)
    in_shirt = front & (np.abs(ctr[:, 0]) < hz)
    # 기준 텍셀: 흰색·남색 각각 중앙값에 가장 가까운 면의 UV
    def ref(mask):
        med = np.median(cols[mask], axis=0)
        j = np.argmin(np.sum((cols - med) ** 2, axis=1) + (~mask) * 1e9)
        return uvs_c[j], med
    (uw, mw_), (un, mn_) = ref(white), ref(navy)
    skin = (r_ > 0.45) & (r_ - b_ > 0.12)
    # 면 가운데 색만 바꾸면 면 안쪽에 남은 흰 얼룩(생성 텍스처 노이즈)이 그대로 보인다 → 재킷·셔츠는 텍스처 없는 단색 재질로 바꾼다.
    # 주름 음영은 조명이 만든다. 셔츠 띠 안 = 흰색, 그 밖 = 남색 (피부는 그대로)
    def flat(name, srgb):
        m_ = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m_.use_nodes = True
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
        bs = m_.node_tree.nodes['Principled BSDF']
        bs.inputs['Base Color'].default_value = (*lin, 1)
        bs.inputs['Roughness'].default_value = 0.85
        m_.use_backface_culling = False
        if name not in [x.name for x in me.materials]:
            me.materials.append(m_)
        return [x.name for x in me.materials].index(name)
    i_navy, i_white = flat('jacket_navy', mn_), flat('shirt_white', mw_)
    shirt = front & (np.abs(ctr[:, 0]) < hz - 0.02) & ~skin
    jacket = ~(front & (np.abs(ctr[:, 0]) < hz)) & ~skin
    for idx in np.where(shirt)[0]:
        polys[idx].material_index = i_white
    for idx in np.where(jacket)[0]:
        polys[idx].material_index = i_navy
    log(f'clothes: {int(jacket.sum())} faces → flat navy {np.round(mn_, 3)}, {int(shirt.sum())} → flat white {np.round(mw_, 3)}')


recolor_clothes(J['neck'].z - 0.1)
bm = bmesh.new()
bm.from_mesh(body.data)
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
bm.to_mesh(body.data)
bm.free()


def components():
    """연결 조각 목록 (정점 인덱스 리스트)"""
    bm_ = bmesh.new()
    bm_.from_mesh(body.data)
    seen, out = set(), []
    for v in bm_.verts:
        if v.index in seen:
            continue
        comp, stack = [], [v]
        seen.add(v.index)
        while stack:
            x = stack.pop()
            comp.append(x.index)
            for e in x.link_edges:
                o = e.other_vert(x)
                if o.index not in seen:
                    seen.add(o.index)
                    stack.append(o)
        out.append(comp)
    bm_.free()
    return sorted(out, key=len, reverse=True)


def remove_tiny(limit=40):
    """잘린 손가락 조각 같은 작은 떠돌이는 지운다 (머리카락 가닥은 훨씬 크다)"""
    tiny = [i for comp in components() if len(comp) < limit for i in comp]
    if tiny:
        bm = bmesh.new()
        bm.from_mesh(body.data)
        bm.verts.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.verts[i] for i in tiny], context='VERTS')
        bm.to_mesh(body.data)
        bm.free()
        log('removed tiny fragments:', len(tiny), 'verts')




def strip_inner_skin():
    """소매 속 피부 껍질을 걷어 낸다. 팔을 들면 겨드랑이·소매 입구로 분홍 껍질이 비친다. 손은 새 메시가 대신하므로 팔 영역의 피부색 정점은 전부 안쪽 껍질이다"""
    P_, C_ = coords(), vertex_colors()
    warm = (C_[:, 0] > 0.22) & (C_[:, 0] > C_[:, 1]) & (C_[:, 0] - C_[:, 2] > 0.08)   # 그늘진 갈색 피부도 포함
    kill = (is_skin(C_) | warm) & (np.abs(P_[:, 0]) > 0.25) & (P_[:, 2] < 1.20)
    bm_ = bmesh.new()
    bm_.from_mesh(body.data)
    bm_.verts.ensure_lookup_table()
    bmesh.ops.delete(bm_, geom=[bm_.verts[i] for i in np.nonzero(kill)[0]], context='VERTS')
    bm_.to_mesh(body.data)
    bm_.free()
    log('inner skin shell removed:', int(kill.sum()), 'verts')


strip_inner_skin()
remove_tiny()
Pc = coords()
for comp in components()[:12]:
    c = Pc[comp].mean(0)
    log(f'component {len(comp):6d} verts centroid ({c[0]:+.2f},{c[1]:+.2f},{c[2]:+.2f})')
log('after cut: verts', len(body.data.vertices), 'faces', len(body.data.polygons))

# ───────────────────────── 3b2. 겉에서 안 보이는 안쪽 껍질 지우기
# TRELLIS 메시는 재킷 안쪽에 피부·안감 껍질이 더 들어 있다. 팔을 들면 이게 겨드랑이 구멍으로 분홍 조각으로 튀어나온다.
# 정점에서 사방(피보나치 구)으로 레이를 쏴서 하나도 못 빠져나가는 정점만 안쪽으로 보고, 세 정점이 다 안쪽인 면을 지운다.
def prune_hidden(n_dirs=24, eps=0.004):
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    k = np.arange(n_dirs) + 0.5
    phi = np.arccos(1 - 2 * k / n_dirs)
    th = math.pi * (1 + 5 ** 0.5) * k
    dirs = [Vector((math.cos(t) * math.sin(p), math.sin(t) * math.sin(p), math.cos(p))) for t, p in zip(th, phi)]
    hidden = []
    for v in bm.verts:
        ok = False
        for d in dirs:
            if tree.ray_cast(v.co + d * eps, d, 8.0)[0] is None:
                ok = True
                break
        if not ok:
            hidden.append(v)
    hid = {v.index for v in hidden}
    dead_faces = [f for f in bm.faces if all(v.index in hid for v in f.verts)]
    bmesh.ops.delete(bm, geom=dead_faces, context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.to_mesh(body.data)
    bm.free()
    log(f'prune hidden: {len(hidden)} hidden verts, removed {len(dead_faces)} faces')


if '--prune' in argv:
    prune_hidden()

# ───────────────────────── 3c. 겨드랑이 접촉면 끊기
# 팔(소매 통)과 몸통은 옆구리에서 얇은 막으로 붙어 한 덩어리로 나왔다. 팔을 들면 이 막이 길게 늘어난다.
# 팔 면과 몸통 면 사이 모서리를 끊어(정점 복제) 두 껍질을 따로 움직이게 한다. 겨드랑이 꼭대기(ZTOP) 위는 이어 둔다.
ZTOP = 1.12     # 이 높이 아래에서만 끊는다 (겨드랑이 꼭대기)
ZLOW = 0.38     # 이 아래는 팔과 몸통 사이가 벌어져 있다
SPLIT_THR = 0.02   # 소매 겉면에서 이만큼까지를 팔 면으로 본다
CHAIN_CAPS = False   # 모서리 고리를 메우는 방식은 팔을 들면 막이 늘어나 쓰지 않는다 (cap_holes)
HOLE_X, HOLE_Z, HOLE_SIDES = 0.35, (0.15, 1.30), 4000   # 옆구리 구멍 메우기 범위
FACING_MIN = float(opt('--facing', -2.0))   # 법선 방향 시험 (TRELLIS 면 방향이 안쪽 껍질에서 뒤집혀 있어 기본은 끈다)


def arm_dist_e(P_):
    """점들의 팔 축까지 소매 겉면 기준 바깥 거리 e (양팔 중 가까운 쪽), 어느 쪽 팔인지, 축에서 바깥으로 향하는 단위벡터"""
    best = np.full(len(P_), 9.0)
    which = np.zeros(len(P_), np.int8)
    rad = np.zeros((len(P_), 3))
    for side, tag in ((1, 'L'), (-1, 'R')):
        Sv, Ev, Wv = (np.array(J[f'{n}_{tag}']) for n in ('shoulder', 'elbow', 'wrist'))
        sc = np.array([1.0, W_.CFG['sy'], 1.0])
        d1, _, o1 = W_.seg_dist(P_ * sc, Sv * sc, Ev * sc)
        Wx = Wv + W_.unit(Wv - Ev) * 0.25   # weights.py 와 같이 소매 끝 아래까지 연장
        d2, _, o2 = W_.seg_dist(P_ * sc, Ev * sc, Wx * sc)
        e1, e2 = d1 - W_.CFG['r_up'], d2 - W_.CFG['r_fo']
        u1 = e1 < e2
        e = np.where(u1, e1, e2)
        o = np.where(u1[:, None], o1, o2)
        o = o / np.maximum(np.linalg.norm(o, axis=1, keepdims=True), 1e-9)
        m = e < best
        best[m], which[m], rad[m] = e[m], side, o[m]
    return best, which, rad


def face_is_arm(cen, nrm):
    """소매 면: 소매 안쪽이거나, 소매 겉면 근처에서 법선이 팔 축 바깥을 향하는 면. 소매에 닿은 몸통 옆면은 법선이 팔 쪽을 보므로 빠진다"""
    e, which, rad = arm_dist_e(cen)
    facing = (nrm * rad).sum(axis=1)
    thr = np.where(cen[:, 2] < 0.58, 0.06, SPLIT_THR)   # 소매 끝은 나팔처럼 벌어져 있다
    is_arm = ((e < thr) & (facing > FACING_MIN)) | (e < -0.06)
    low = cen[:, 2] <= ZLOW - 0.05
    # 소매 끝 아래쪽 자락(z < ZLOW)은 소매 통 안쪽 면만 팔로 본다 (몸통 밑단 옆면은 소매 겉면에서 떨어져 있다)
    is_arm = np.where(low, (e < 0.0) & (cen[:, 2] > 0.05), is_arm)
    is_arm &= cen[:, 2] < ZTOP + 0.15
    return is_arm, which


def arm_axis_point(A, side):
    """팔 모서리 묶음 중심에서 가장 가까운 소매 중심선(어깨-팔꿈치-손목) 위의 점"""
    tag = 'L' if side > 0 else 'R'
    c = sum((v.co for e in A for v in e.verts), Vector()) / (2 * len(A))
    best, bd = None, 1e9
    pts = [J[f'shoulder_{tag}'], J[f'elbow_{tag}'], J[f'wrist_{tag}']]
    for a, b in zip(pts[:-1], pts[1:]):
        ab = b - a
        t = max(0.0, min(1.0, (c - a).dot(ab) / ab.length_squared))
        q = a + ab * t
        if (q - c).length < bd:
            best, bd = q, (q - c).length
    return best


def _cls(ed, lay):
    return ed.link_faces[0][lay]


def _fill_loop(bm, edges, lay, cls_val, uvl, apex=None):
    """닫힌 모서리 고리를 메우고 새 면에 분류·재킷 감청 UV 를 준다. apex 가 있으면 그 점으로 부채꼴, 못 메워도 부채꼴로 덮는다"""
    newf = []
    if apex is None:
        res = bmesh.ops.holes_fill(bm, edges=edges, sides=HOLE_SIDES)
        newf = list(res['faces'])
    if not newf:
        vs = {v for ed in edges for v in ed.verts}
        c = Vector(apex) if apex is not None else sum((v.co for v in vs), Vector()) / len(vs)
        cv = bm.verts.new(c)
        for ed in edges:
            if not ed.is_boundary:
                continue
            lp = next(l for l in ed.link_faces[0].loops if l.edge is ed)
            try:
                newf.append(bm.faces.new((lp.link_loop_next.vert, lp.vert, cv)))
            except ValueError:
                pass
    for f in newf:
        us = [l[uvl].uv.copy() for v in f.verts for l in v.link_loops if l.face is not f]
        if us:
            u = navy_uv(us)
            for l in f.loops:
                l[uvl].uv = u
            if '--dbgcap' in argv and f is newf[0]:
                log('CAP uv', tuple(u), 'color', tuple(np.round(uv_srgb([u])[0] * 255)), 'cands', len(us))
        f[lay] = cls_val
        f.smooth = True
    return len(newf)


def cap_holes(bm, lay):
    """옆구리 구멍을 메운다. 팔이 떨어져 나간 자리의 경계 고리는 몸통 모서리와 팔 모서리가 이어진 하나의 고리다.
    그대로 메우면 팔과 몸통 사이에 막이 걸려 팔을 들 때 늘어난다. 그래서 고리를 둘로 나눠
    (몸통 모서리 + 팔 모서리의 복제본) 와 (팔 모서리 + 몸통 모서리의 복제본) 을 따로 메운다.
    복제본은 같은 자리에 있어서 바인드 자세에서는 겹치고, 팔을 들면 각자 제 몸을 따라간다"""
    bm.edges.ensure_lookup_table()
    be = [ed for ed in bm.edges if ed.is_boundary
          and all(abs(v.co.x) > HOLE_X and HOLE_Z[0] < v.co.z < HOLE_Z[1] for v in ed.verts)]
    par = {}

    def fnd(a):
        while par.setdefault(a, a) != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    for ed in be:
        par[fnd(ed.verts[0].index)] = fnd(ed.verts[1].index)
    comps = {}
    for ed in be:
        comps.setdefault(fnd(ed.verts[0].index), []).append(ed)
    uvl = bm.loops.layers.uv.active
    made = 0
    for eds in comps.values():
        T = [e for e in eds if _cls(e, lay) == 0]
        A = [e for e in eds if _cls(e, lay) != 0]
        per = sum(e.calc_length() for e in eds)
        if '--dbgcap' in argv:
            log(f'CAP comp edges {len(eds)} (torso {len(T)}, arm {len(A)}) per {per:.2f}')
        # 둘레 이웃 면이 재킷 감청이 아니면(속 피부·셔츠 껍질의 구멍) 메우지 않는다
        navy_uv([l[uvl].uv.copy() for e in eds for l in e.link_faces[0].loops])
        if navy_uv.dist > 0.12:
            continue
        if T and A:
            tv = {v for e in T for v in e.verts}
            av = {v for e in A for v in e.verts}
            # 몸통 쪽: 몸통 모서리 + 팔 모서리 복제본
            cp = {v: (v if v in tv else bm.verts.new(v.co)) for v in av}
            ne = []
            for e in A:
                a, b = cp[e.verts[0]], cp[e.verts[1]]
                try:
                    ne.append(bm.edges.new((a, b)))
                except ValueError:
                    ne.append(bm.edges.get((a, b)))
            made += _fill_loop(bm, T + [x for x in ne if x], lay, 0, uvl)
            # 팔 쪽: 소매 터진 자리는 소매 중심선 위 한 점으로 모으는 뿔로 닫는다 (납작한 막이면 팔을 들 때 날개처럼 달린다)
            arm_cls = _cls(A[0], lay)
            made += _fill_loop(bm, A, lay, arm_cls, uvl, apex=arm_axis_point(A, arm_cls))
        elif T:
            made += _fill_loop(bm, T, lay, 0, uvl)
        else:
            made += _fill_loop(bm, A, lay, _cls(A[0], lay), uvl, apex=arm_axis_point(A, _cls(A[0], lay)))
    return made




WALL_Z, WALL_Y, WALL_BACK, FLAP_MARGIN = (0.26, 1.18), (-0.42, 0.42), 0.035, 0.07   # 옆구리 벽 패치: 높이 범위, 앞뒤(y) 범위, 안쪽 깊이, 막 찌꺼기 한계


def wall_patch(bm, lay):
    """소매가 떨어져 나간 자리의 옆구리 벽을 새로 만든다 (몸통 벽 높이장 x(y, z)).
    창(높이 WALL_Z × 앞뒤 WALL_Y) 위·아래 바깥 띠에서 재킷 몸통의 y 별 바깥 x 윤곽을 재고, 창 안은 두 윤곽을 높이로 섞는다.
    기존 벽과 겹쳐 깜박이지 않게 WALL_BACK 만큼 안쪽에 놓고, 창 안에서 벽 밖으로 삐져나온 막 찌꺼기는 지운다"""
    z0, z1 = WALL_Z
    y0, y1 = WALL_Y
    nz, ny = int(round((z1 - z0) / 0.03)), int(round((y1 - y0) / 0.03))
    ZZ, YY = np.linspace(z0, z1, nz + 1), np.linspace(y0, y1, ny + 1)
    made = 0
    uvl = bm.loops.layers.uv.active
    for sd in (1, -1):
        bm.verts.ensure_lookup_table()
        allc = [v for v in bm.verts if v.link_loops and sd * v.co.x > 0.25 and z0 - 0.3 < v.co.z < z1 + 0.3]
        cols = uv_srgb([v.link_loops[0][uvl].uv for v in allc])
        navy = np.sqrt(((cols - NAVY) ** 2).sum(axis=1)) < 0.12
        xyz = np.array([[v.co.x * sd, v.co.y, v.co.z] for v in allc])
        arm_v = np.array([any(f[lay] != 0 for f in v.link_faces) for v in allc])
        good = navy & ~arm_v

        def profile(zlo, zhi):
            """높이 띠 [zlo, zhi] 에서 y 별 바깥 x (상위 15% 평균), 빈 y 는 보간"""
            m = good & (xyz[:, 2] > zlo) & (xyz[:, 2] < zhi)
            out = np.full(ny + 1, np.nan)
            for i, y in enumerate(YY):
                sel = m & (np.abs(xyz[:, 1] - y) < 0.03)
                if sel.sum() >= 3:
                    xs = np.sort(xyz[sel, 0])
                    out[i] = xs[int(len(xs) * 0.85):].mean()
            ok = ~np.isnan(out)
            return np.interp(YY, YY[ok], out[ok]) if ok.sum() >= 3 else None
        top, bot = profile(z1 + 0.01, z1 + 0.20), profile(z0 - 0.20, z0 - 0.01)
        if top is None or bot is None:
            log('wall patch: 윤곽을 못 쟀다, 건너뜀')
            continue
        Xw = np.array([[bot[j] * (1 - (ZZ[i] - z0) / (z1 - z0)) + top[j] * ((ZZ[i] - z0) / (z1 - z0)) for j in range(ny + 1)] for i in range(nz + 1)])
        grid = {}
        for i in range(nz + 1):
            for j in range(ny + 1):
                grid[i, j] = bm.verts.new(Vector((sd * (Xw[i, j] - WALL_BACK), YY[j], ZZ[i])))
        u = navy_uv([v.link_loops[0][uvl].uv.copy() for v in np.array(allc, dtype=object)[good][:3000]])
        for i in range(nz):
            for j in range(ny):
                a_, b_, c_, d_ = grid[i, j], grid[i, j + 1], grid[i + 1, j + 1], grid[i + 1, j]
                quad = (a_, b_, c_, d_) if sd > 0 else (a_, d_, c_, b_)   # 법선이 바깥(sd*x)을 보게
                for tri in ((quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])):
                    try:
                        f = bm.faces.new(tri)
                    except ValueError:
                        continue
                    f.smooth = True
                    f[lay] = 0
                    for l in f.loops:
                        l[uvl].uv = u
                    made += 1
        gv = set(grid.values())
        dead = []
        for f in bm.faces:
            if f[lay] != 0 or any(v in gv for v in f.verts):
                continue
            c = f.calc_center_median()
            cx = c.x * sd
            if cx < 0.6 or not (z0 < c.z < z1) or not (-0.3 < c.y < 0.3):
                continue
            i = min(nz, max(0, int(round((c.z - z0) / (z1 - z0) * nz))))
            j = min(ny, max(0, int(round((c.y - y0) / (y1 - y0) * ny))))
            if cx > Xw[i, j] + FLAP_MARGIN:
                dead.append(f)
        bmesh.ops.delete(bm, geom=dead, context='FACES')
        log(f'wall patch side {sd:+d}: grid {nz}x{ny}, x {Xw.min():.2f}..{Xw.max():.2f}, removed {len(dead)} faces')
    return made


def split_arms():
    body.data.validate(verbose=False)   # 퇴화 면을 먼저 정리해 면 번호를 고정한다
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    cen = np.array([f.calc_center_median()[:] for f in bm.faces])
    nrm = np.array([f.normal[:] for f in bm.faces])
    is_arm, which = face_is_arm(cen, nrm)
    if '--dbgcls' in argv:
        m = (np.abs(cen[:, 0] - 0.86) < 0.08) & (cen[:, 2] > 0.30) & (cen[:, 2] < 0.42) & (np.abs(cen[:, 1] + 0.16) < 0.06)
        e_, _, _ = arm_dist_e(cen)
        log(f'DBGCLS faces {int(m.sum())} arm {int(is_arm[m].sum())} e mean {e_[m].mean():.3f} min {e_[m].min():.3f} max {e_[m].max():.3f} z mean {cen[m, 2].mean():.3f}')
        for i in np.nonzero(m)[0][:8]:
            log('DBGCLS', tuple(np.round(cen[i], 3)), 'e', round(float(e_[i]), 3), 'arm', bool(is_arm[i]))
    # 고립된 낱장 분류를 이웃 다수결로 정리한다 (분류 경계가 들쭉날쭉하면 떨어진 조각이 생긴다)
    nbr = [[g.index for e in f.edges for g in e.link_faces if g is not f] for f in bm.faces]
    for _ in range(4):
        new_ = is_arm.copy()
        for i, ns in enumerate(nbr):
            if not ns:
                continue
            k = sum(1 for j in ns if is_arm[j])
            if is_arm[i] and k * 2 < len(ns) - 0.5:
                new_[i] = False
            elif (not is_arm[i]) and k * 2 > len(ns) + 0.5:
                new_[i] = True
        is_arm = new_
    lay = bm.faces.layers.int.new('arm_cls')   # 면 속성으로 남겨 두면 뒤에서 면을 지워도 따라간다
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        f[lay] = int(which[f.index]) if is_arm[f.index] else 0
    cls = {f.index: bool(is_arm[f.index]) for f in bm.faces}
    cut = []
    for ed in bm.edges:
        if len(ed.link_faces) != 2:
            continue
        a, b = ed.link_faces
        if cls[a.index] != cls[b.index] and 0.08 < (ed.verts[0].co.z + ed.verts[1].co.z) / 2 < ZTOP:
            cut.append(ed)
    bmesh.ops.split_edges(bm, edges=cut)
    # 팔 면과 몸통 면이 모서리 없이 꼭짓점 하나로만 닿는 곳이 남는다. 그런 꼭짓점도 면 묶음별로 갈라 준다
    bm.verts.ensure_lookup_table()
    pinch = [v for v in bm.verts if 0.08 < v.co.z < ZTOP and abs(v.co.x) > 0.3
             and len({cls[g.index] for g in v.link_faces}) > 1]
    if pinch:
        bmesh.ops.split_edges(bm, edges=[], verts=pinch, use_verts=True)
    log(f'pinch verts split: {len(pinch)}')
    # 팔이 떠나면 옆구리 벽에 구멍이 남는다 (TRELLIS 는 소매와 몸통을 한 겹으로 붙여 냈다). 몸통·팔을 따로 메운다
    nf = 0 if ('--nocap' in argv or not CHAIN_CAPS) else cap_holes(bm, lay)
    nf += 0 if '--nowall' in argv else wall_patch(bm, lay)
    if '--dbgloops' in argv:
        log('--- after fill')
        bm.edges.ensure_lookup_table()
        be = [ed for ed in bm.edges if ed.is_boundary]
        par = {}

        def fnd(a):
            while par.setdefault(a, a) != a:
                par[a] = par[par[a]]
                a = par[a]
            return a
        for ed in be:
            par[fnd(ed.verts[0].index)] = fnd(ed.verts[1].index)
        grp = {}
        for ed in be:
            grp.setdefault(fnd(ed.verts[0].index), []).append(ed)
        for k, eds in sorted(grp.items(), key=lambda kv: -len(kv[1]))[:25]:
            vs = [v.co for ed in eds for v in ed.verts]
            xs = [v.x for v in vs]; zs = [v.z for v in vs]
            cl = [ed.link_faces[0][lay] for ed in eds]
            per = sum(ed.calc_length() for ed in eds)
            log(f'LOOP edges {len(eds):4d} per {per:.2f} x[{min(xs):+.2f},{max(xs):+.2f}] z[{min(zs):.2f},{max(zs):.2f}] arm-edges {sum(1 for c in cl if c)} torso-edges {sum(1 for c in cl if not c)}')
    bm.to_mesh(body.data)
    bm.free()
    log(f'armpit split: {len(cut)} edges, arm faces {int(is_arm.sum())}, hole patch faces {nf}')


split_arms()
remove_tiny()

# ───────────────────────── 3d. 새 손 배치 (있으면)
placed = HA.load_and_place(HAND_DIR, J, cuff_info, PALM_LEN, log) if USE_HAND else None

# ───────────────────────── 4. 뼈대
arm_data = bpy.data.armatures.new('navy_rig')
arm = bpy.data.objects.new('navy_rig', arm_data)
bpy.context.scene.collection.objects.link(arm)
activate(arm)
bpy.ops.object.mode_set(mode='EDIT')
eb = arm_data.edit_bones


def bone(name, head, tail, parent=None, connect=False):
    b = eb.new(name)
    b.head, b.tail = head, tail
    if (b.tail - b.head).length < 1e-4:
        b.tail = b.head + Vector((0, 0, 0.05))
    if parent:
        b.parent = eb[parent]
        b.use_connect = connect
    return b


bone('hips', J['hips'] - Vector((0, 0, 0.25)), J['hips'])
bone('spine', J['hips'], J['chest'], 'hips', True)
bone('chest', J['chest'], J['neck'], 'spine', True)
bone('neck', J['neck'], J['head'], 'chest', True)
bone('head', J['head'], J['head_top'], 'neck', True)
if MOUTH:
    # 턱 뼈: 입 뒤쪽 위(경첩)에서 턱끝으로. 드라이버가 mouthOpen 만큼 아래로 돌린다
    _mc = MOUTH['center']
    # 경첩은 귀 쪽(머리 깊이 가운데)·입보다 조금 위. 그래야 아래 얼굴이 뒤로 쏠리지 않고 거의 곧게 내려간다.
    # 경첩이 멀리 있으니 각도는 작게: 입술이 JAW_DROP 만큼 벌어지는 각을 json(jawMax)으로 넘긴다
    _hinge = Vector((_mc.x, J['head'].y, _mc.z + 0.04))
    MOUTH['jaw_max'] = JAW_DROP / max(0.1, _hinge.y - _mc.y)
    bone('jaw', _hinge, Vector((_mc.x, _mc.y + 0.02, MOUTH['chin_z'])), 'head')
for tag in ('L', 'R'):
    bone(f'shoulder_{tag}', J[f'clavicle_{tag}'], J[f'shoulder_{tag}'], 'chest')
    bone(f'upper_arm_{tag}', J[f'shoulder_{tag}'], J[f'elbow_{tag}'], f'shoulder_{tag}', True)
    bone(f'forearm_{tag}', J[f'elbow_{tag}'], J[f'wrist_{tag}'], f'upper_arm_{tag}', True)
    bone(f'hand_{tag}', J[f'wrist_{tag}'], J[f'knuckle_{tag}'], f'forearm_{tag}', True)
    if USE_HAND:
        HA.add_bones(eb, placed[tag]['pts'], tag, J, bone)
    else:
        # 새 손이 오기 전 임시 손가락 뼈 (메시는 없다)
        bone(f'fingers1_{tag}', J[f'knuckle_{tag}'], J[f'finger_mid_{tag}'], f'hand_{tag}', True)
        bone(f'fingers2_{tag}', J[f'finger_mid_{tag}'], J[f'finger_tip_{tag}'], f'fingers1_{tag}', True)
        bone(f'thumb1_{tag}', J[f'thumb0_{tag}'], J[f'thumb2_{tag}'], f'hand_{tag}')
        bone(f'thumb2_{tag}', J[f'thumb2_{tag}'], J[f'thumb_tip_{tag}'], f'thumb1_{tag}', True)
# 뼈 Z 축이 앞(-Y, 카메라 쪽)을 보게 roll 을 맞춘다
for b in eb:
    b.align_roll(Vector((0, -1, 0)))
bpy.ops.object.mode_set(mode='OBJECT')
log('bones', len(arm_data.bones))

# ───────────────────────── 5. 가중치 (절차)
bone_names = [b.name for b in arm_data.bones]
Pv = coords()
me = body.data
ev = np.empty(len(me.edges) * 2, np.int32)
me.edges.foreach_get('vertices', ev)
Jn = {k: np.array(v) for k, v in J.items()}


def vertex_lock():
    """겨드랑이 구간 정점: 팔 면에 붙어 있으면 그 팔 쪽(+1 L, -1 R), 아니면 0. 분류는 split_arms 가 면 속성으로 남긴 값"""
    me_ = body.data
    cls = np.zeros(len(me_.polygons), np.int32)
    me_.attributes['arm_cls'].data.foreach_get('value', cls)
    lock = np.zeros(len(me_.vertices), np.int8)
    for p in np.nonzero(cls)[0]:
        for v in me_.polygons[int(p)].vertices:
            lock[v] = cls[p]
    return lock


lock = vertex_lock()
if '--dbgmix' in argv:
    _pl = np.array([list(p_.vertices) for p_ in body.data.polygons if len(p_.vertices) == 3])
    _lk = lock[_pl]
    mixed = (_lk.max(1) != _lk.min(1)) | False
    _c = Pv[_pl].mean(1)
    log(f'MIX faces {int(mixed.sum())}')
    for lo, hi in ((0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.1), (1.1, 1.3)):
        m = mixed & (_c[:, 2] >= lo) & (_c[:, 2] < hi) & (np.abs(_c[:, 0]) > 0.3)
        log(f'MIX z[{lo},{hi}) {int(m.sum())}')
    sel = np.nonzero(mixed & (np.abs(_c[:, 0]) > 0.3))[0]
    # 면 크기 (긴 막)
    ar = np.linalg.norm(np.cross(Pv[_pl[:, 1]] - Pv[_pl[:, 0]], Pv[_pl[:, 2]] - Pv[_pl[:, 0]]), axis=1) / 2
    for i in sel[np.argsort(-ar[sel])][:12]:
        log('MIX big', tuple(np.round(_c[i], 2)), 'area', round(float(ar[i]), 3), 'locks', _lk[i])
Wt = W_.compute(Pv, Jn, bone_names, ev.reshape(-1, 2), lock=lock, zlow=ZLOW, ztop=ZTOP)


def write_weights(obj, Wt, names):
    obj.vertex_groups.clear()
    vg = [obj.vertex_groups.new(name=n) for n in names]
    for bi in range(len(names)):
        col = Wt[:, bi]
        for vi in np.nonzero(col > 1e-4)[0]:
            vg[bi].add([int(vi)], float(col[vi]), 'REPLACE')


if MOUTH:
    # 손 자르기 등으로 정점 번호가 바뀌었으니 입술 위·아래를 지금 메시에서 다시 찾는다
    _lo, _up = MO.lip_sides(body, MOUTH['curve'], MOUTH['xr'], MOUTH['center'])
    log(f'lip sides: lower {len(_lo)}, upper {len(_up)}')
    _jw = MO.jaw_weights(coords(), MOUTH['curve'], MOUTH['center'], MOUTH['mw'], MOUTH['chin_z'], J['head'].y, _lo, _up)
    # 입 높이는 목→머리 가중치가 섞이는 띠 안이라 head 몫만 옮기면 턱이 반만 따라간다 → 모든 뼈 몫을 jw 비율로 턱에 넘긴다
    _ji = bone_names.index('jaw')
    _take = _jw
    Wt *= (1 - _jw)[:, None]
    Wt[:, _ji] += _jw
    log(f'jaw weights: {int((_take > 0.05).sum())} verts')
    # 턱이 더해지면 영향이 5개가 되는 정점이 생긴다 → 큰 것 4개만 남기고 다시 합을 1로 (glTF·three 는 정점당 4개)
    _ord = np.argsort(-Wt, axis=1)
    _cut = np.zeros_like(Wt, dtype=bool)
    np.put_along_axis(_cut, _ord[:, 4:], True, axis=1)
    Wt[_cut] = 0
    Wt /= np.maximum(Wt.sum(axis=1, keepdims=True), 1e-9)
write_weights(body, Wt, bone_names)
log('unweighted verts', int((Wt.sum(axis=1) < 0.5).sum()), 'max influences', int((Wt > 1e-4).sum(axis=1).max()))

for p in body.data.polygons:
    p.use_smooth = True

body.parent = arm
mod = body.modifiers.new('Armature', 'ARMATURE')
mod.object = arm

hand_objs = []
if USE_HAND:
    for tag in ('L', 'R'):
        ho = placed[tag]['obj']
        Wh = HA.weights(ho, placed[tag]['pts'], J, tag, bone_names)
        write_weights(ho, Wh, bone_names)
        ho.parent = arm
        hm = ho.modifiers.new('Armature', 'ARMATURE')
        hm.object = arm
        hand_objs.append(ho)
        log(f'hand {tag} weighted: verts {len(ho.data.vertices)}, max influences {int((Wh > 1e-4).sum(axis=1).max())}')

# 입 속은 텍스처에서 찾은 미소 선 높이에 맞춘다 (랜드마크 입 중심은 만화 얼굴이라 어긋난다)
cav_objs = MO.add_cavity(bpy, arm, Vector((MOUTH['center'].x, MOUTH['center'].y, float(MOUTH['curve'](MOUTH['center'].x)))), MOUTH['mw'], MOUTH['center'].y, log) if MOUTH else []

# ───────────────────────── 겨드랑이 다리 (사용자: 만세하면 겨드랑이가 비어 보인다)
# 팔과 몸통 사이를 남색 타원체로 잇는다. 몸 쪽 끝은 chest, 팔 쪽 끝은 upper_arm 을 따라가서 팔을 들면 겨드랑이를 덮으며 늘어난다.
# 쉼 자세(팔 내림)에서는 팔·몸 속에 묻혀 안 보인다.
pit_objs = []
_jn = bpy.data.materials.get('jacket_navy')
for side, tag in ((1, 'L'), (-1, 'R')):
    S_ = Vector(J[f'shoulder_{tag}'])
    E_ = Vector(J[f'elbow_{tag}'])
    A_ = S_ + Vector((-side * 0.16, 0.0, -0.22))          # 몸통 옆 (가슴 안쪽)
    B_ = S_ + (E_ - S_).normalized() * 0.30               # 위팔 안쪽
    ax = (B_ - A_)
    L_ = ax.length
    me_p = bpy.data.meshes.new(f'navy_pit_{tag}')
    ob_p = bpy.data.objects.new(f'navy_pit_{tag}', me_p)
    bpy.context.scene.collection.objects.link(ob_p)
    bm_p = bmesh.new()
    bmesh.ops.create_uvsphere(bm_p, u_segments=20, v_segments=14, radius=1.0)
    q_ = Vector((0, 0, 1)).rotation_difference(ax.normalized())
    for v in bm_p.verts:
        loc = Vector((v.co.x * 0.15, v.co.y * 0.12, v.co.z * (L_ / 2 + 0.06)))
        v.co = (A_ + B_) / 2 + q_ @ loc
    bm_p.to_mesh(me_p)
    bm_p.free()
    for poly in me_p.polygons:
        poly.use_smooth = True
    if _jn:
        me_p.materials.append(_jn)
    g_c = ob_p.vertex_groups.new(name='chest')
    g_s = ob_p.vertex_groups.new(name=f'shoulder_{tag}')
    g_u = ob_p.vertex_groups.new(name=f'upper_arm_{tag}')
    for v in me_p.vertices:
        t = max(0.0, min(1.0, (v.co - A_).dot(ax) / (L_ * L_)))
        wu = t * t * (3 - 2 * t)
        g_c.add([v.index], (1 - wu) * 0.7, 'REPLACE')
        g_s.add([v.index], (1 - wu) * 0.3, 'REPLACE')
        g_u.add([v.index], wu, 'REPLACE')
    ob_p.parent = arm
    mp = ob_p.modifiers.new('Armature', 'ARMATURE')
    mp.object = arm
    pit_objs.append(ob_p)
log(f'armpit bridges: {len(pit_objs)}')

# 재질: 양면 (TRELLIS 면 방향이 다 맞지는 않는다)
for m in body.data.materials:
    m.use_backface_culling = False
# ───────────────────────── 얼굴 오버레이 위치 (head 뼈 기준이 아니라 앱 월드 좌표; three 가 bind 시점에 head 로컬로 바꾼다)
face = {}
if F:
    def fp(i):
        return joint(*F[i][:2], depth_bias=0.5)  # 얼굴 표면 쪽
    for tag, (a, b, t, bt) in {'eyeL': (362, 263, 386, 374), 'eyeR': (133, 33, 159, 145)}.items():
        pa, pb, pt, pbt = fp(a), fp(b), fp(t), fp(bt)
        face[tag] = {'center': list((pa + pb) / 2), 'width': (pa - pb).length, 'height': max((pt - pbt).length, 0.02)}
    ml, mr_, mt, mb = fp(291), fp(61), fp(13), fp(14)
    face['mouth'] = {'center': list((ml + mr_) / 2), 'width': (ml - mr_).length, 'upper': list(mt), 'lower': list(mb)}


def three(v):
    v = Vector(v)
    return [round(v.x, 4), round(v.z, 4), round(-v.y, 4)]


info = {
    'source': Path(SRC).name,
    'scale': S,
    'height': APP_H,
    # --baked-face: 얼굴(눈·입)이 텍스처에 잘 구워져 있다 (머리 이식 모델). 오버레이는 깜빡임·입 벌림만 그린다
    'bakedFace': '--baked-face' in argv,
    # 3D 입(턱 뼈)이 있으면 오버레이는 벌린 입을 그리지 않는다
    'jaw': bool(MOUTH),
    'jawMax': round(MOUTH['jaw_max'], 4) if MOUTH else None,
    'joints': {k: three(v) for k, v in J.items()},
    'palm': ({t: three(placed[t]['palm']) for t in ('L', 'R')} if placed else None),
    'face': {k: {kk: (three(vv) if isinstance(vv, list) else round(vv, 4)) for kk, vv in d.items()} for k, d in face.items()},
}
OUT.parent.mkdir(parents=True, exist_ok=True)
json.dump(info, open(OUT.with_name(OUT.stem + '-rig.json'), 'w'), indent=1)

# ───────────────────────── 소매 끝 말린 단 (cuff)
# 생성 메시의 소매 끝은 톱니처럼 들쭉날쭉하고 얇은 조각이 손등 위로 늘어진다 → 부드러운 남색 고리로 덮는다.
# 레퍼런스의 소매 끝도 둥글게 말린 단이다. 아래팔 뼈에 100% 붙인다.
CUFF_MINOR = 0.03
cuff_objs = []
_navy = None
for tag in ('L', 'R'):
    E = Vector(J[f'elbow_{tag}'])
    fa = Vector(cuff_info[tag]['fa']).normalized()
    t_end = cuff_info[tag]['t_skin'] - CUFF_BACK
    # 소매 끝 단면 반지름: 그 높이 근처 몸 정점의 축 거리 (바깥 껍질 쪽)
    co = np.array([v.co[:] for v in body.data.vertices])
    tt = (co - np.array(E)) @ np.array(fa)
    rad = np.linalg.norm(co - (np.array(E) + tt[:, None] * np.array(fa)), axis=1)
    band = (np.abs(tt - t_end) < 0.03) & (rad < 0.35)
    r_open = float(np.percentile(rad[band], 85)) if band.sum() > 20 else 0.18
    bm_c = bmesh.new()
    bmesh.ops.create_cone(bm_c, cap_ends=False, segments=40, radius1=1, radius2=1, depth=1)  # 자리만 잡고 아래에서 다시 만든다
    bm_c.free()
    me_c = bpy.data.meshes.new(f'navy_cuff_{tag}')
    ob_c = bpy.data.objects.new(f'navy_cuff_{tag}', me_c)
    bpy.context.scene.collection.objects.link(ob_c)
    bm_c = bmesh.new()
    # 도넛: 큰 반지름 = 소매 안쪽, 작은 반지름 = 말린 두께. 축 방향으로 조금 납작하게
    NU, NV = 40, 14
    q = fa.to_track_quat('Z', 'Y')
    # 소매 끝보다 조금 안쪽에 두고, 벌어진 끝단 반지름보다 작게 (밖으로 고리가 튀어나오면 훌라후프처럼 보인다)
    center = E + fa * (t_end - 0.03)
    R_maj = r_open * 0.8
    rows = []
    for i in range(NU):
        a_ = 2 * math.pi * i / NU
        row = []
        for j in range(NV):
            b_ = 2 * math.pi * j / NV
            rr = R_maj + CUFF_MINOR * math.cos(b_)
            local = Vector((rr * math.cos(a_), rr * math.sin(a_), CUFF_MINOR * 0.8 * math.sin(b_)))
            row.append(bm_c.verts.new(center + q @ local))
        rows.append(row)
    for i in range(NU):
        for j in range(NV):
            a1, b1 = rows[i][j], rows[(i + 1) % NU][j]
            c1, d1 = rows[(i + 1) % NU][(j + 1) % NV], rows[i][(j + 1) % NV]
            bm_c.faces.new((a1, b1, c1, d1))
    bmesh.ops.recalc_face_normals(bm_c, faces=bm_c.faces)
    bm_c.to_mesh(me_c)
    bm_c.free()
    for poly in me_c.polygons:
        poly.use_smooth = True
    if _navy is None:
        _navy = bpy.data.materials.new('navy_cuff')
        _navy.use_nodes = True
        # 재킷 남색 (sRGB 0.153,0.165,0.251 → 선형)
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (0.150, 0.162, 0.248)]
        _navy.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*lin, 1)
        _navy.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.85
    me_c.materials.append(_navy)
    vg = ob_c.vertex_groups.new(name=f'forearm_{tag}')
    vg.add(list(range(len(me_c.vertices))), 1.0, 'REPLACE')
    ob_c.parent = arm
    mod_c = ob_c.modifiers.new('Armature', 'ARMATURE')
    mod_c.object = arm
    cuff_objs.append(ob_c)
    log(f'cuff ring {tag}: r_open={r_open:.3f} at t={t_end:.3f}')

# ───────────────────────── 내보내기
for ob in bpy.context.selected_objects:
    ob.select_set(False)
arm.select_set(True)
body.select_set(True)
for ho in hand_objs + cuff_objs + cav_objs + pit_objs:
    ho.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT), export_format='GLB', use_selection=True, export_yup=True,
                          export_skins=True, export_animations=False, export_apply=False, export_extras=False)
log('exported', OUT)


if USE_HAND:
    pass  # 새 손 붙이기는 rig/handattach.py (아래 hook)

if WVIEW or PREVIEW:
    import rigview as RV
    from mathutils import Vector as V

if WVIEW:
    pal = np.array(RV.PALETTE)
    pal = pal[np.arange(len(bone_names)) % len(pal)]
    if opt('--wgroup'):   # 몸통=파랑, 어깨=노랑, 상완=빨강, 전완=초록, 손=흰색 (가중치 팔/몸통 구분 보기용)
        gc = {'hips': (.2, .3, .9), 'spine': (.2, .3, .9), 'chest': (.35, .5, 1.0), 'neck': (.2, .8, .9), 'head': (.8, .8, .8),
              'shoulder': (1, .9, .1), 'upper_arm': (1, .15, .1), 'forearm': (.1, .8, .2)}
        pal = np.array([next((v for k, v in gc.items() if n.startswith(k)), (1, 1, 1)) for n in bone_names])
    cols = Wt @ pal
    RV.set_vertex_colors(body, cols)
    vis = RV.bone_vis(arm)
    cam = RV.setup_workbench(560, 'VERTEX')
    for name, az, ctr, sc_ in (('front', 0, (0, 0, 1.5), 4.4), ('side', 90, (0, 0, 1.5), 4.4), ('back', 180, (0, 0, 1.5), 4.4),
                               ('arm', 0, (0.75, 0, 0.95), 2.2), ('armside', 90, (0.7, 0, 0.95), 2.2), ('shoulder', 0, (0.4, 0, 1.3), 1.6)):
        RV.snap(cam, f'{WVIEW}-{name}.png', az, ctr, sc_)
    if opt('--wpose'):
        RV.pose(arm, opt('--wpose'))
        for k, (az, c, s_) in enumerate(((0, (0.9, 0, 0.8), 2.0), (-40, (0.9, 0, 0.8), 2.0), (60, (0.9, 0, 0.8), 2.0))):
            RV.snap(cam, f'{WVIEW}-pose{k}.png', az, c, s_)
    log('wview done')

if '--dbgstretch' in argv:
    import rigview as RV
    RV.pose(arm, 'tpose')
    dg = bpy.context.evaluated_depsgraph_get()
    ev_ = body.evaluated_get(dg).to_mesh()
    pe = np.array([v.co[:] for v in ev_.vertices])
    me_ = body.data
    me_.calc_loop_triangles()
    tri = np.array([t.vertices[:] for t in me_.loop_triangles])

    def areas(Q):
        return np.linalg.norm(np.cross(Q[tri[:, 1]] - Q[tri[:, 0]], Q[tri[:, 2]] - Q[tri[:, 0]]), axis=1) / 2
    a0, a1 = areas(Pv), areas(pe)
    # 가장 긴 모서리 늘어남
    def maxedge(Q):
        return np.max([np.linalg.norm(Q[tri[:, i]] - Q[tri[:, (i + 1) % 3]], axis=1) for i in range(3)], axis=0)
    e0, e1 = maxedge(Pv), maxedge(pe)
    ratio = e1 / np.maximum(e0, 1e-4)
    names_ = [g.name for g in body.vertex_groups]
    big = np.nonzero((e1 > 0.25) & (ratio > 3) & (np.abs(Pv[tri].mean(1)[:, 0]) > 0.3))[0]
    log(f'STRETCH faces {len(big)}')
    for i in big[np.argsort(-e1[big])][:20]:
        vs = tri[i]
        desc = []
        for v in vs:
            ws = sorted(((g.weight, names_[g.group]) for g in body.data.vertices[int(v)].groups), reverse=True)[:2]
            desc.append('/'.join(f'{n}{w:.1f}' for w, n in ws))
        log('STRETCH', tuple(np.round(Pv[tri[i]].mean(0), 2)), 'edge', round(float(e0[i]), 3), '->', round(float(e1[i]), 3), 'lock', lock[vs], desc)
    # 가중치 구간별 (몸통 lock=0 인데 팔 가중치 가진 정점)
    ua = np.zeros(len(Pv))
    for nm in names_:
        if nm.startswith(('upper_arm', 'shoulder', 'forearm')):
            ua += Wt[:, bone_names.index(nm)]
    m = (lock == 0) & (ua > 0.1) & (np.abs(Pv[:, 0]) > 0.4) & (Pv[:, 2] < 1.2)
    log('TORSO-LOCK verts with arm weight', int(m.sum()))
    for lo, hi in ((0, 0.4), (0.4, 0.7), (0.7, 1.0), (1.0, 1.12), (1.12, 1.2)):
        mm = m & (Pv[:, 2] >= lo) & (Pv[:, 2] < hi)
        log(f'  z[{lo},{hi}) {int(mm.sum())}')

if opt('--dbgpose'):
    import rigview as RV
    RV.pose(arm, opt('--dbgpose'))
    for n_ in ('shoulder_L', 'upper_arm_L', 'forearm_L', 'hand_L'):
        pb_ = arm.pose.bones[n_]
        log(f'POSE {n_}: head {tuple(round(x, 3) for x in pb_.head)} tail {tuple(round(x, 3) for x in pb_.tail)}')
    dg = bpy.context.evaluated_depsgraph_get()
    ev_ = body.evaluated_get(dg).to_mesh()
    pe = np.array([v.co[:] for v in ev_.vertices])
    gi = {g.index: g.name for g in body.vertex_groups}
    names_ = [g.name for g in body.vertex_groups]
    sel = np.nonzero((pe[:, 0] > 0.75) & (pe[:, 2] < 1.0) & (pe[:, 2] > 0.4))[0]
    log(f'POSE flap candidates {len(sel)}')
    for i in sel[:40]:
        v = body.data.vertices[int(i)]
        ws = sorted(((g.weight, names_[g.group]) for g in v.groups), reverse=True)[:3]
        log('POSE flapv bind', tuple(np.round(Pv[i], 2)), 'posed', tuple(np.round(pe[i], 2)), 'lock', int(lock[i]), 'e', round(float(arm_dist_e(Pv[[i]])[0][0]), 3), [(round(w, 2), n) for w, n in ws])
    for nm in ('upper_arm_L', 'forearm_L'):
        gidx = body.vertex_groups[nm].index
        sel = [i for i, v in enumerate(body.data.vertices) if any(g.group == gidx and g.weight > 0.95 for g in v.groups)]
        log(f'POSE {nm} pure verts {len(sel)}: bind mean {np.round(Pv[sel].mean(0), 3)} posed mean {np.round(pe[sel].mean(0), 3)}')

if opt('--closeup'):
    import rigview as RV
    cam = RV.setup_eevee(720)
    for p in body.data.polygons:
        p.use_smooth = True
    for nm in opt('--poses', 'bind').split(','):
        RV.pose(arm, nm)
        for k, (az, c, s_) in enumerate(((0, (0.9, 0, 0.3), 1.4), (-50, (0.9, 0, 0.3), 1.4), (90, (0.9, 0, 0.3), 1.4))):
            RV.snap(cam, f'{opt("--closeup")}-{nm}-{k}.png', az, c, s_)

if opt('--vc'):
    # 임의 시점 렌더: --vc PREFIX --vcviews "az:cx:cy:cz:scale,..." --poses bind,tpose
    import rigview as RV
    cam = RV.setup_eevee(int(opt('--vcres', 720)))
    for p in body.data.polygons:
        p.use_smooth = True
    for nm in opt('--poses', 'bind').split(','):
        RV.pose(arm, nm)
        for k, v in enumerate(opt('--vcviews').split(',')):
            az, cx, cy, cz, sc_ = (float(x) for x in v.split(':'))
            RV.snap(cam, f'{opt("--vc")}-{nm}-{k}.png', az, (cx, cy, cz), sc_)

if PREVIEW:
    if WVIEW:
        bpy.data.objects.remove(vis)
        body.data.color_attributes.remove(body.data.color_attributes['dbg'])
    cam = RV.setup_eevee(480)
    for p in body.data.polygons:
        p.use_smooth = True
    for pname in (opt('--poses', 'bind,idle,wave,tpose,armsup,forward,yawL,twist,lean,shrug')).split(','):
        RV.pose(arm, pname)
        for vname, az in (('front', 0), ('q', -40)):
            RV.snap(cam, f'{PREVIEW}-{pname}-{vname}.png', az, (0, 0, 1.45), 4.2)
        # 왼팔(+x) 확대: 어깨~손목 가운데를 본다
        c = (arm.pose.bones['shoulder_L'].tail + arm.pose.bones['hand_L'].head) / 2
        RV.snap(cam, f'{PREVIEW}-{pname}-arm.png', -20, c, 2.2)
        RV.snap(cam, f'{PREVIEW}-{pname}-side.png', 90, (0, 0, 1.45), 4.2)
    log('preview done')
