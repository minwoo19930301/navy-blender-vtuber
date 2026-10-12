"""
TRELLIS 로 만든 캐릭터 메시에 뼈대를 넣어 three.js 용 스킨드 GLB 를 만든다.

  Blender --background --python rig/rig.py -- trellis/apose-s1-t42d.glb public/navy.glb [--preview shots/rig.png]

입력: 텍스처 입힌 TRELLIS GLB(눕혀서 나옴, 높이 1), rig/front.json(정면 직교 렌더 픽셀↔모델 좌표),
      rig/front-landmarks.json(MediaPipe 포즈·얼굴), rig/front-hands.json(손).
출력: public/navy.glb (Y 위, 책상=재킷 밑단 y=0, 정면 +Z) + public/navy-rig.json (얼굴 오버레이 위치 등).

순서
1. 세우고 앱 단위로 키운다 (재킷 밑단 → 머리 끝 = APP_H). 밑단 아래(바지)는 잘라 낸다 — 투명 오버레이에서 다리가 보이면 안 된다.
2. 정점 병합(UV 는 면 모서리별이라 유지된다) → 면 방향 통일 → 데시메이트.
3. MediaPipe 2D 점을 정면 직교 좌표로 옮기고, 깊이는 그 자리에서 앞·뒤로 쏜 레이 교점의 가운데로 잡는다.
4. 뼈대: hips·spine·chest·neck·head, 양쪽 shoulder·upper_arm·forearm·hand·thumb1/2·fingers1/2.
   손가락 넷은 메시에서 붙어 있어(벙어리장갑 모양) 하나의 fingers 사슬로 굽힌다.
5. 가중치: 복셀 리메시한 물샐틈없는 대역 메시에 자동 가중치(bone heat)를 주고, 원래 메시로 옮긴다(가까운 면 보간).
   머리카락·얼굴은 머리 뼈에 1.0 으로 고정한다 (목 아래 깃 근처만 섞인다).
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
argv = sys.argv[sys.argv.index('--') + 1:]
SRC, OUT = argv[0], Path(argv[1]).resolve()
PREVIEW = argv[argv.index('--preview') + 1] if '--preview' in argv else None

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

# ───────────────────────── 2. 자르기·병합·면 방향·데시메이트
bm = bmesh.new()
bm.from_mesh(body.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4 * S)
cut = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, -0.02), plane_no=(0, 0, 1), clear_inner=True)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
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
for k, v in J.items():
    log(f'  {k:16s} ({v.x:+.3f}, {v.y:+.3f}, {v.z:+.3f})')

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
for tag in ('L', 'R'):
    bone(f'shoulder_{tag}', J[f'clavicle_{tag}'], J[f'shoulder_{tag}'], 'chest')
    bone(f'upper_arm_{tag}', J[f'shoulder_{tag}'], J[f'elbow_{tag}'], f'shoulder_{tag}', True)
    bone(f'forearm_{tag}', J[f'elbow_{tag}'], J[f'wrist_{tag}'], f'upper_arm_{tag}', True)
    bone(f'hand_{tag}', J[f'wrist_{tag}'], J[f'knuckle_{tag}'], f'forearm_{tag}', True)
    bone(f'fingers1_{tag}', J[f'knuckle_{tag}'], J[f'finger_mid_{tag}'], f'hand_{tag}', True)
    bone(f'fingers2_{tag}', J[f'finger_mid_{tag}'], J[f'finger_tip_{tag}'], f'fingers1_{tag}', True)
    bone(f'thumb1_{tag}', J[f'thumb0_{tag}'], J[f'thumb2_{tag}'], f'hand_{tag}')
    bone(f'thumb2_{tag}', J[f'thumb2_{tag}'], J[f'thumb_tip_{tag}'], f'thumb1_{tag}', True)
# 손바닥 방향을 roll 로 맞춰 두면 three.js 쪽에서 손 기저를 읽기 쉽다: 뼈 Z 축이 앞(-Y, 카메라 쪽)을 보게 한다
for b in eb:
    b.align_roll(Vector((0, -1, 0)))
bpy.ops.object.mode_set(mode='OBJECT')
log('bones', len(arm_data.bones))

# ───────────────────────── 5. 가중치: 복셀 대역 메시 → bone heat → 원래 메시로 옮김
proxy = body.copy()
proxy.data = body.data.copy()
proxy.name = 'weight_proxy'
bpy.context.scene.collection.objects.link(proxy)
rm = proxy.modifiers.new('remesh', 'REMESH')
rm.mode = 'VOXEL'
rm.voxel_size = 0.025
activate(proxy)
bpy.ops.object.modifier_apply(modifier=rm.name)
log('proxy faces', len(proxy.data.polygons))
activate(proxy)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type='ARMATURE_AUTO')
empty_groups = [g.name for g in proxy.vertex_groups if not any(g.index in [x.group for x in v.groups] for v in proxy.data.vertices[:2000])]
log('proxy vgroups', len(proxy.vertex_groups))

for b in arm_data.bones:
    body.vertex_groups.new(name=b.name)
dt = body.modifiers.new('xfer', 'DATA_TRANSFER')
dt.object = proxy
dt.use_vert_data = True
dt.data_types_verts = {'VGROUP_WEIGHTS'}
dt.vert_mapping = 'POLYINTERP_NEAREST'
dt.layers_vgroup_select_src = 'ALL'
dt.layers_vgroup_select_dst = 'NAME'
activate(body)
bpy.ops.object.modifier_apply(modifier=dt.name)

# 머리 고정: 턱 아래 띠(band)부터 위는 head 1.0 (머리카락이 어깨 뼈에 끌려가지 않게)
head_g = body.vertex_groups['head']
z0 = J['head'].z - 0.12   # 이 아래는 원래 가중치
z1 = J['head'].z + 0.04   # 이 위는 head 1.0
groups = {g.index: g for g in body.vertex_groups}
for v in body.data.vertices:
    t = (v.co.z - z0) / (z1 - z0)
    if t <= 0:
        continue
    t = min(1.0, t)
    t = t * t * (3 - 2 * t)
    for ge in v.groups:
        g = groups[ge.group]
        if g.name != 'head':
            g.add([v.index], ge.weight * (1 - t), 'REPLACE')
    head_g.add([v.index], max(t, 0.0) + sum(ge.weight for ge in v.groups if groups[ge.group].name == 'head') * (1 - t), 'REPLACE')

activate(body)
bpy.ops.object.vertex_group_normalize_all(lock_active=False)
bpy.ops.object.vertex_group_limit_total(limit=4)
bpy.ops.object.vertex_group_normalize_all(lock_active=False)
unweighted = sum(1 for v in body.data.vertices if not any(ge.weight > 1e-4 for ge in v.groups))
log('unweighted verts', unweighted)

bpy.data.objects.remove(proxy)
body.parent = arm
mod = body.modifiers.new('Armature', 'ARMATURE')
mod.object = arm

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
    'joints': {k: three(v) for k, v in J.items()},
    'face': {k: {kk: (three(vv) if isinstance(vv, list) else round(vv, 4)) for kk, vv in d.items()} for k, d in face.items()},
}
OUT.parent.mkdir(parents=True, exist_ok=True)
json.dump(info, open(OUT.with_name(OUT.stem + '-rig.json'), 'w'), indent=1)

# ───────────────────────── 내보내기
for ob in bpy.context.selected_objects:
    ob.select_set(False)
arm.select_set(True)
body.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT), export_format='GLB', use_selection=True, export_yup=True,
                          export_skins=True, export_animations=False, export_apply=False, export_extras=False)
log('exported', OUT)

if PREVIEW:
    # 확인용: 팔을 책상 쪽으로 구부린 포즈로 정면 렌더
    pb = arm.pose.bones
    for tag, s in (('L', 1), ('R', -1)):
        pb[f'upper_arm_{tag}'].rotation_mode = 'XYZ'
        pb[f'forearm_{tag}'].rotation_mode = 'XYZ'
        pb[f'forearm_{tag}'].rotation_euler = (math.radians(-70), 0, 0)
        pb[f'fingers1_{tag}'].rotation_mode = 'XYZ'
        pb[f'fingers1_{tag}'].rotation_euler = (math.radians(30), 0, 0)
    pb['head'].rotation_mode = 'XYZ'
    pb['head'].rotation_euler = (0, 0, math.radians(20))
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x = sc.render.resolution_y = 720
    sc.view_settings.view_transform = 'Standard'
    w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
    w.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    w.node_tree.nodes['Background'].inputs[1].default_value = 0.6
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30)); sc.collection.objects.link(sun)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.lens = 85
    cam.location = Vector((0, -14, 1.6)); cam.rotation_euler = (math.radians(87), 0, 0)
    sc.render.filepath = str(Path(PREVIEW).resolve())
    bpy.ops.render.render(write_still=True)
    log('preview', PREVIEW)
