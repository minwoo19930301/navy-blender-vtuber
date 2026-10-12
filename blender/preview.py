"""
build.py 장면을 포즈를 잡아 렌더한다. 모양을 레퍼런스에 맞춰 볼 때 쓴다.

  Blender --background --python blender/preview.py -- OUT.png [--view ref] [--pose rest] [--only body,head] [--ref reference/idle-0.png]

--view  ref(레퍼런스 영상과 같은 구도) | front | three(35°) | side | back | head | face | hands | top | working
--pose  rest(책상에 손 올림) | working(노트북 타이핑, 오른쪽으로 몸을 돌림) | tpose
--ref   주면 OUT 옆에 레퍼런스를 붙인 OUT-compare.png 도 만든다 (ffmpeg)
--res   한 변 픽셀 (기본 720)

포즈는 three.js 리그(src/model/rig.ts)와 같은 규칙으로 놓는다: 소매는 원점에서 +Y 가 관절 방향을 보게 돌리고,
손은 손가락(+Y)·손바닥(+Z) 기저를 맞춘다. 얼굴 데칼은 three.js 에서만 그려지므로 여기서는 숨긴다.
"""
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'parts'))

import bpy  # noqa: E402
from mathutils import Matrix, Quaternion, Vector  # noqa: E402

import build  # noqa: E402
from common import DIMS, T  # noqa: E402

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []


def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


OUT = Path(argv[0]).resolve()
VIEW = opt('--view', 'ref')
POSE = opt('--pose', 'rest')
REF = opt('--ref')
RES = int(opt('--res', '720'))
ONLY = opt('--only')

ctx, failed = build.build_scene(ONLY.split(',') if ONLY else None)
objs = bpy.data.objects


def V(t):
    return Vector(t)


# ───────────────────────── 포즈
POSES = {
    # side=+1 기준 방향. x 에 side 를 곱해 양쪽에 쓴다
    'rest': dict(upper=DIMS['REST_UPPER'], lower=DIMS['REST_LOWER'], hand=DIMS['REST_HAND'], palm=DIMS['REST_PALM'],
                 body_yaw=0.0, head=(0, 0, 0), curl=0.15),
    'working': dict(upper=(0.30, -0.90, 0.30), lower=(-0.55, -0.10, 0.83), hand=(-0.15, -0.20, 1.0), palm=(0, -1, 0.1),
                    body_yaw=-0.55, head=(-0.12, 0.0, 0.0), curl=0.45),
    'tpose': dict(upper=(1, 0, 0), lower=(1, 0, 0), hand=(1, 0, 0), palm=(0, -1, 0), body_yaw=0, head=(0, 0, 0), curl=0),
}
P = POSES[POSE]


def aim(o, pos_world, d):
    """소매: 원점을 pos 에, 로컬 +Y(three) = Blender +Z 를 d 방향으로. 부모 body 의 회전을 고려한다."""
    parent_q = o.parent.matrix_world.to_quaternion() if o.parent else Quaternion()
    o.rotation_mode = 'QUATERNION'
    q_world = Vector((0, 0, 1)).rotation_difference(T(*d).normalized())
    o.rotation_quaternion = parent_q.inverted() @ q_world
    o.location = (o.parent.matrix_world.inverted() if o.parent else Matrix.Identity(4)) @ T(*pos_world)


def basis_quat(fy, fz):
    fy = V(fy).normalized()
    fz = (V(fz) - V(fy).normalized() * V(fz).dot(fy)).normalized()
    fx = fy.cross(fz)
    m3 = Matrix((T(*fx), -T(*fz), T(*fy))).transposed()
    return m3.to_quaternion()


body = objs['body']
body.rotation_mode = 'XYZ'
body.rotation_euler = (0, 0, P['body_yaw'])  # three y 회전 = Blender z 회전
bpy.context.view_layer.update()
yaw = Matrix.Rotation(P['body_yaw'], 3, 'Y')  # three 좌표에서 쓰는 회전

hp = objs['head_pivot']
hp.rotation_mode = 'XYZ'
# three (pitch x, yaw y, roll z) → Blender (x, -z?, y): three x = Blender x, three y = Blender z, three z = Blender -y
hp.rotation_euler = (P['head'][0], -P['head'][2], P['head'][1])

for side, tag in ((1, 'L'), (-1, 'R')):
    def sd(t):
        return yaw @ V((t[0] * side, t[1], t[2]))
    sh = yaw @ V((DIMS['SHOULDER'][0] * side, DIMS['SHOULDER'][1], DIMS['SHOULDER'][2]))
    ud, ld = sd(P['upper']).normalized(), sd(P['lower']).normalized()
    el = sh + ud * DIMS['UPPER_LEN']
    wr = el + ld * DIMS['LOWER_LEN']
    if f'arm_upper_{tag}' in objs:
        aim(objs[f'arm_upper_{tag}'], sh, ud)
        aim(objs[f'arm_lower_{tag}'], el, ld)
    if f'hand_{tag}' in objs:
        h = objs[f'hand_{tag}']
        h.rotation_mode = 'QUATERNION'
        h.rotation_quaternion = basis_quat(sd(P['hand']), sd(P['palm']))
        h.location = T(*wr)
        for i in range(5):
            for j in range(3):
                n = objs.get(f'f{i}_{j}_{tag}')
                if n is None:
                    continue
                c = P['curl'] * (0.6 if i == 0 else 1.0) * (0.9 if j == 0 else 1.2)
                # three rotation.x 양수 = 손가락(+Y)이 손바닥(+Z) 쪽으로. Blender 로컬 x 축 회전도 같은 부호다
                n.rotation_mode = 'XYZ'
                n.rotation_euler = (c, n.rotation_euler[1], n.rotation_euler[2])
bpy.context.view_layer.update()

if 'face_decal' in objs:
    objs['face_decal'].hide_render = True

# ───────────────────────── 카메라·조명
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = scene.render.resolution_y = RES
scene.render.film_transparent = False
try:
    scene.view_settings.view_transform = 'Standard'
except Exception:
    pass
world = bpy.data.worlds.new('w')
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes['Background']
bg.inputs[0].default_value = (0.97, 0.97, 0.98, 1)
bg.inputs[1].default_value = 0.75

C = DIMS['HEAD_C']
# (목표점 three, 보이는 높이, 방위각°, 고도°)
VIEWS = {
    'ref': ((0, 1.40, 0), 3.66, 0, 4),
    'front': ((0, 1.45, 0), 3.9, 0, 2),
    'three': ((0, 1.45, 0), 3.9, 35, 4),
    'side': ((0, 1.45, 0), 3.9, 90, 2),
    'back': ((0, 1.45, 0), 3.9, 180, 4),
    'head': ((C[0], C[1] + 0.15, C[2]), 2.1, 0, 2),
    'face': ((C[0], C[1] - 0.25, C[2]), 1.3, 0, 0),
    'hands': ((0, 0.15, 0.55), 1.5, 0, 35),
    'top': ((0, 1.6, 0), 4.0, 0, 70),
    'working': ((0.25, 1.30, 0), 3.8, -20, 14),
}
tgt3, vis_h, az, el = VIEWS[VIEW]
cam_d = bpy.data.cameras.new('cam')
cam_d.lens = 118
cam_d.sensor_fit = 'VERTICAL'
cam_d.sensor_height = 36
dist = vis_h * cam_d.lens / 36
a, e = math.radians(az), math.radians(el)
tgt = T(*tgt3)
cam = bpy.data.objects.new('cam', cam_d)
scene.collection.objects.link(cam)
scene.camera = cam
cam.location = tgt + T(math.sin(a) * math.cos(e) * dist, math.sin(e) * dist, math.cos(a) * math.cos(e) * dist)
cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam_d.clip_end = dist * 4


def light(name, kind, energy, rot_three_dir, size=None):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    if size is not None and hasattr(ld, 'angle'):
        ld.angle = size
    o = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(o)
    d = T(*rot_three_dir).normalized()
    o.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()


light('key', 'SUN', 3.2, (-0.5, 0.9, 0.8), 0.3)
light('fill', 'SUN', 1.0, (0.7, 0.3, 0.6), 0.6)
light('rim', 'SUN', 1.6, (0.3, 0.8, -0.9), 0.3)

scene.render.filepath = str(OUT)
bpy.ops.render.render(write_still=True)
print('[preview] wrote', OUT, 'failed parts:', failed)

if REF:
    cmp = OUT.with_name(OUT.stem + '-compare.png')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(OUT), '-i', str(Path(REF).resolve()),
                    '-filter_complex', f'[0]scale={RES}:{RES}[a];[1]scale={RES}:{RES}[b];[a][b]hstack', str(cmp)], check=False)
    print('[preview] compare', cmp)
