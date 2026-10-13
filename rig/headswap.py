"""
몸 메시의 머리를 '상자 모델'(레퍼런스 프레임에서 바로 만든 Space 결과, trellis/out-idle-s0.glb)의 머리로 바꾼다.
상자 모델 얼굴이 레퍼런스와 더 닮았다 (눈 크기·하이라이트·미소·머리카락).

  Blender --background --python rig/headswap.py -- BODY.glb BOX.glb OUT.glb [--preview OUT.png]

BODY.glb: 로컬 TRELLIS 몸 (눕혀 나옴, 높이 1). 정면 랜드마크는 rig/front.json + rig/front-landmarks.json.
BOX.glb : Space TRELLIS (서 있음). 정면 랜드마크는 rig/box-front.json + rig/box-front-landmarks.json (front_ortho.py ROTX=0, detect.py).
OUT.glb : BODY 와 같은 틀(눕힘)로 내보낸다 → rig/rig.py 입력으로 그대로 쓴다.

맞추기: 두 얼굴의 눈 중심·입 중심으로 배율(회전 없음)과 위치를 정한다. 깊이는 눈 사이 얼굴 표면에 맞춘다.
자르기: 턱 위는 통째로, 턱 아래는 목 둘레 원기둥 안만 바꾼다 (어깨·재킷 깃은 몸 것을 남긴다).
이음매는 셔츠 깃 높이에 둔다. 상자 목을 깃 안쪽으로 조금 더 내려 겹치게 해서 틈이 안 보이게 한다.
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
BODY, BOX, OUT = argv[0], argv[1], Path(argv[2]).resolve()
PREVIEW = argv[argv.index('--preview') + 1] if '--preview' in argv else None


def log(*a):
    print('[swap]', *a, flush=True)


def load(path, rotx):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objs = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in objs if o.type == 'MESH']
    assert len(meshes) == 1, (path, len(meshes))
    m = meshes[0]
    mw = m.matrix_world.copy()
    for o in objs:
        if o is not m:
            bpy.data.objects.remove(o)
    m.parent = None
    m.matrix_world = Matrix.Rotation(math.radians(rotx), 4, 'X') @ mw
    m.data.transform(m.matrix_world)
    m.matrix_world = Matrix.Identity(4)
    # UV 이음매로 갈라진 정점을 붙인다 (Blender 는 UV 를 면 모서리별로 가지고 있어 텍스처는 그대로다).
    # 안 붙이면 UV 조각마다 따로 떨어진 섬이 돼서 '작은 조각 지우기'가 몸을 통째로 지운다
    bm = bmesh.new()
    bm.from_mesh(m.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.to_mesh(m.data)
    bm.free()
    return m


bpy.ops.wm.read_factory_settings(use_empty=True)
body = load(BODY, -90)   # 눕혀 나온 로컬 결과를 세운다 (front_ortho.py 와 같은 틀)
box = load(BOX, 0)       # Space 결과는 이미 서 있다
body.name, box.name = 'body', 'box'


def landmarks(prefix):
    o = json.load(open(HERE / f'{prefix}.json'))
    lm = json.load(open(HERE / f'{prefix}-landmarks.json'))
    return o, lm


def px_to_xz(o, px, py):
    r, s = o['res'], o['ortho_scale']
    return o['cx'] + (px - r / 2) / r * s, o['cz'] - (py - r / 2) / r * s


def face_points(obj, prefix):
    o, lm = landmarks(prefix)
    F = lm['face']
    bvh = BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())

    def p3(i, j=None):
        px = F[i][:2] if j is None else ((F[i][0] + F[j][0]) / 2, (F[i][1] + F[j][1]) / 2)
        x, z = px_to_xz(o, *px)
        hit = bvh.ray_cast(Vector((x, -50, z)), Vector((0, 1, 0)))
        return Vector((x, hit[0].y if hit[0] else 0.0, z))
    pts = {'eyeL': p3(362, 263), 'eyeR': p3(133, 33), 'mouth': p3(61, 291), 'chin': p3(152), 'nose': p3(1)}
    # 셔츠 깃: 턱 아래로 정면 렌더 가운데 열을 내려가며 흰 셔츠가 시작하는 곳
    from PIL import Image  # noqa: E402  (Blender 파이썬에 없으면 아래 대체)
    return pts


def collar_z(obj, prefix, chin_z):
    """정면에서 목 가운데를 따라 내려가며 피부→셔츠 경계를 찾는다 (재질 색이 아니라 렌더 픽셀로)."""
    o, _ = landmarks(prefix)
    img = bpy.data.images.load(str(HERE / f'{prefix}.png'))
    w, h = img.size
    px = list(img.pixels)
    r = o['res']
    # 턱 픽셀 행
    row0 = int(r / 2 - (chin_z - o['cz']) / o['ortho_scale'] * r)
    cx = int(r / 2 + (0 - o['cx']) / o['ortho_scale'] * r)
    for row in range(row0, min(h - 1, row0 + 200)):
        yb = h - 1 - row  # Blender 이미지는 아래가 0
        i = (yb * w + cx) * 4
        R, G, B = px[i], px[i + 1], px[i + 2]
        if R > 0.88 and G > 0.86 and B > 0.84 and abs(R - B) < 0.06:  # 흰 셔츠 (피부는 R 이 B 보다 확실히 크다)
            return px_to_xz(o, cx, row)[1]
    return chin_z - 0.05


# Blender 파이썬엔 PIL 이 없을 수 있다 → face_points 에서 import 를 빼고 쓴다
def face_points_np(obj, prefix):
    o, lm = landmarks(prefix)
    F = lm['face']
    bvh = BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())

    def p3(i, j=None):
        px = F[i][:2] if j is None else ((F[i][0] + F[j][0]) / 2, (F[i][1] + F[j][1]) / 2)
        x, z = px_to_xz(o, *px)
        hit = bvh.ray_cast(Vector((x, -50, z)), Vector((0, 1, 0)))
        return Vector((x, hit[0].y if hit[0] else 0.0, z))
    return {'eyeL': p3(362, 263), 'eyeR': p3(133, 33), 'mouth': p3(61, 291), 'chin': p3(152), 'nose': p3(1)}


fb = face_points_np(body, 'body-front')   # 머리 이식 전 몸 렌더 (rig/body-front*.json, 고정)
fx = face_points_np(box, 'box-front')
for k in fb:
    log(f'{k:6s} body {tuple(round(v, 3) for v in fb[k])}  box {tuple(round(v, 3) for v in fx[k])}')

eb_mid, ex_mid = (fb['eyeL'] + fb['eyeR']) / 2, (fx['eyeL'] + fx['eyeR']) / 2
s_eye = (fb['eyeL'] - fb['eyeR']).length / (fx['eyeL'] - fx['eyeR']).length
s_mouth = (eb_mid - fb['mouth']).length / (ex_mid - fx['mouth']).length
s_chin = (eb_mid - fb['chin']).length / (ex_mid - fx['chin']).length
# 눈 사이 거리는 몸 쪽 얼굴(눈이 큼)과 비율이 달라 덜 믿는다. 눈→입·눈→턱 세로 비율을 주로 쓴다
# 배율은 레퍼런스(reference/idle-0.png) 비율로 정한다: (머리 끝 - 턱) / (턱 - 재킷 밑단) = HEAD_RATIO.
# 몸 얼굴은 FLUX 가 눈을 크게 그린 얼굴이라 눈 간격으로 맞추면 머리가 너무 커진다 (1.57 배가 나왔다).
# 턱·머리 끝 높이만 쓴다 (z 는 정면 픽셀에서 바로 나와 믿을 만하다. 깊이는 안 쓴다)
HEAD_RATIO = 1.44          # 레퍼런스: 머리카락 끝 30px, 턱 390px, 책상 640px
HEM_Z = -0.40              # 몸(눕힘→세움 틀)의 재킷 밑단 높이 (rig.py 가 쓰는 값과 같다)
box_top = max(v.co.z for v in box.data.vertices if (v.co - Vector((ex_mid.x, 0, v.co.z))).length < 0.5)
# z' = eb_mid.z + S (z - ex_mid.z) 로 옮겼을 때 (top' - chin') / (chin' - HEM_Z) = HEAD_RATIO 를 S 에 대해 푼다
a_ = (box_top - fx['chin'].z)                       # top' - chin' = S * a_
c_ = eb_mid.z - HEM_Z                                # chin' - HEM_Z = c_ + S * d_
d_ = (fx['chin'].z - ex_mid.z)
S = HEAD_RATIO * c_ / (a_ - HEAD_RATIO * d_)
log(f'head ratio target {HEAD_RATIO}: S={S:.3f} (eye-based would be {0.5 * s_eye + 0.5 * s_mouth:.3f})')
T = eb_mid - ex_mid * S
log(f'scale eye={s_eye:.3f} mouth={s_mouth:.3f} chin={s_chin:.3f} → {S:.3f}, offset {tuple(round(v, 4) for v in T)}')
box.data.transform(Matrix.Translation(T) @ Matrix.Scale(S, 4))
box.data.update()

# 깃 높이와 목 축
chin_z = fb['chin'].z
cz_body = collar_z(body, 'body-front', chin_z)
log(f'chin z {chin_z:.3f}, collar z {cz_body:.3f}')
neck_c = Vector((eb_mid.x, 0, 0))
# 목 반지름: 몸 메시에서 깃 바로 위 높이의 피부 정점 분포로 잰다 (정면 투영 폭의 절반)
bm = bmesh.new()
bm.from_mesh(body.data)
band = [v.co for v in bm.verts if cz_body + 0.005 < v.co.z < chin_z - 0.01]
if band:
    xs = sorted(abs(v.x - neck_c.x) for v in band)
    neck_r = xs[int(len(xs) * 0.6)] if xs else 0.06
    ys = [v.y for v in band]
    neck_c.y = (min(ys) + max(ys)) / 2
else:
    neck_r = 0.06
bm.free()
R_CUT = max(0.05, neck_r * 1.35)
log(f'neck radius {neck_r:.3f}, cut radius {R_CUT:.3f}, neck center y {neck_c.y:.3f}')


def in_neck(co):
    return math.hypot(co.x - neck_c.x, co.y - neck_c.y) < R_CUT


def face_colors(obj):
    """면마다 UV 중심의 베이스컬러 텍스처 색 (0..1, 저장값 그대로) — numpy 배열 [F,3]"""
    import numpy as np
    me = obj.data
    uv = me.uv_layers.active.data
    out = np.full((len(me.polygons), 3), 0.5, np.float32)
    imgs = {}
    for mi, m in enumerate(me.materials):
        if not m or not m.node_tree:
            continue
        for n in m.node_tree.nodes:
            if n.type == 'TEX_IMAGE' and n.image and any(l.to_socket.name == 'Base Color' for l in n.outputs['Color'].links):
                im = n.image
                px = np.empty(im.size[0] * im.size[1] * 4, np.float32)
                im.pixels.foreach_get(px)
                imgs[mi] = (px.reshape(im.size[1], im.size[0], 4), im.size)
    for p in me.polygons:
        if p.material_index not in imgs:
            continue
        arr, (w, h) = imgs[p.material_index]
        u = sum(uv[i].uv[0] for i in p.loop_indices) / p.loop_total
        v = sum(uv[i].uv[1] for i in p.loop_indices) / p.loop_total
        x = min(w - 1, max(0, int(u % 1.0 * w)))
        y = min(h - 1, max(0, int(v % 1.0 * h)))
        out[p.index] = arr[y, x, :3]
    return out


def is_head_material(c):
    """피부 또는 머리카락이면 True. 재킷(남색: B 가 R 보다 큼)·셔츠(밝은 무채색)는 False"""
    r, g, b = float(c[0]), float(c[1]), float(c[2])
    skin = r > 0.45 and r - b > 0.12
    hair = max(r, g, b) < 0.22 and b - r < 0.05
    return skin or hair


BAND_LO = cz_body - 0.06   # 이 아래는 몸 것만
EYE_Z = (fb['eyeL'].z + fb['eyeR'].z) / 2
R_BAND = 0.30              # 목 둘레 원기둥 반지름 (어깨는 이 밖)


def cut(obj, keep_head):
    """턱 위: 몸은 다 지우고 상자는 다 남긴다. 목 띠(깃 아래 조금 ~ 턱): 텍스처 색으로 가른다
    (상자는 피부·머리카락만, 몸은 재킷·셔츠만 남긴다). 그 아래·원기둥 밖은 몸만."""
    cols = face_colors(obj)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    dead = []
    for f in bm.faces:
        c = f.calc_center_median()
        if c.z > chin_z - 0.005:
            # 상자 모델은 재킷 깃이 턱 높이까지 올라와 있다 → 눈 높이 아래에서는 상자도 피부·머리카락만 남긴다
            # (눈 흰자·하이라이트가 지워지지 않게 눈 아래 0.075 부터 적용한다)
            if keep_head and c.z < EYE_Z - 0.075:
                mine = is_head_material(cols[f.index])
            else:
                mine = keep_head
        elif c.z > BAND_LO and in_neck_r(c, R_BAND):
            if not keep_head and c.y > neck_c.y + 0.02:
                # 목 뒤: 상자 모델은 여기가 재킷 깃이라(지워진다) 몸의 목 뒤 피부를 남겨 틈을 메운다
                mine = True
            else:
                mine = is_head_material(cols[f.index]) == keep_head
        else:
            mine = not keep_head
        if not mine:
            dead.append(f)
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    # 떨어져 나온 작은 조각 제거
    bm.verts.ensure_lookup_table()
    seen, islands = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, isl = [v], []
        seen.add(v.index)
        while stack:
            u = stack.pop()
            isl.append(u)
            for e in u.link_edges:
                w = e.other_vert(u)
                if w.index not in seen:
                    seen.add(w.index)
                    stack.append(w)
        islands.append(isl)
    islands.sort(key=len, reverse=True)
    small = [v for isl in islands[1:] if len(isl) < 0.01 * len(bm.verts) for v in isl]
    bmesh.ops.delete(bm, geom=small, context='VERTS')
    bm.to_mesh(obj.data)
    bm.free()
    log(f'{obj.name}: {len(obj.data.polygons):,} faces after cut')


def in_neck_r(co, r):
    return math.hypot(co.x - neck_c.x, co.y - neck_c.y) < r


cut(body, keep_head=False)
cut(box, keep_head=True)

# 합치기 (재질 2개: 몸 텍스처, 상자 텍스처)
for ob in bpy.context.selected_objects:
    ob.select_set(False)
body.select_set(True)
box.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
merged = bpy.context.view_layer.objects.active
merged.name = 'navy_body'
for p in merged.data.polygons:
    p.use_smooth = True
for m in merged.data.materials:
    m.use_backface_culling = False

if PREVIEW:
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x, sc.render.resolution_y = 1440, 720
    sc.view_settings.view_transform = 'Standard'
    w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
    w.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    w.node_tree.nodes['Background'].inputs[1].default_value = 0.7
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sun.data.energy = 2.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30)); sc.collection.objects.link(sun)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = 0.75
    paths = []
    for az in (0, 40, 90, 180):
        t = math.radians(az)
        ctr = Vector((0, 0, chin_z + 0.08))
        cam.location = ctr + Vector((math.sin(t) * 5, -math.cos(t) * 5, 0))
        cam.rotation_euler = (ctr - cam.location).to_track_quat('-Z', 'Y').to_euler()
        sc.render.resolution_x = sc.render.resolution_y = 720
        p = str(Path(PREVIEW).with_name(Path(PREVIEW).stem + f'-{az}.png'))
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        paths.append(p)
    import subprocess
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *sum([['-i', p] for p in paths], []), '-filter_complex', 'hstack=inputs=4', str(Path(PREVIEW).resolve())])
    log('preview', PREVIEW)

# 원래 틀(눕힘)로 되돌려 내보낸다
merged.data.transform(Matrix.Rotation(math.radians(90), 4, 'X'))
for ob in bpy.context.selected_objects:
    ob.select_set(False)
merged.select_set(True)
OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(OUT), export_format='GLB', use_selection=True, export_yup=True, export_apply=True)  # 가져오면 몸 GLB 처럼 눕혀 나온다
log('wrote', OUT)
