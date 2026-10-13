"""손 메시에서 MediaPipe 21점을 3D 로 뽑는다.

  ~/Documents/GitHub/trellis-mac/.venv/bin/python rig/hand/landmarks.py rig/hand/hand_R.glb
  전제: ortho.py 로 front/side/top 렌더(rig/hand/ortho-*.png/json)가 이미 있다.
  → rig/hand/hand_R.json, rig/hand/check-*.png (점 겹쳐 그린 검증 이미지)

좌표계: 세운 모델 좌표 (Blender Z-up). GLB 를 X축 -90° 세운 것 = GLB 원본 좌표와 같다 (x, y, z 그대로).
정면 카메라는 -Y 에서 +Y 를 본다 → 렌더에서 보이는 면은 y 가 작은 쪽.
"""
import json, sys
from pathlib import Path
import numpy as np
import trimesh
import mediapipe as mp
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
glb = Path(sys.argv[1])
models = HERE.parent.parent / 'public/models'
mesh = trimesh.load(glb, force='mesh')
V = np.asarray(mesh.vertices)  # 세운 좌표와 같다 (위 docstring)
print('bounds', mesh.bounds.tolist())

info = json.load(open(HERE / 'ortho-front.json'))
res, sc = info['res'], info['ortho_scale']
ctr = np.array(info['center'])


def px2model(px, py):  # 정면 렌더 픽셀 → (x, z)
    return ctr[0] + (px / res - 0.5) * sc, ctr[2] - (py / res - 0.5) * sc


def model2px(p, view):  # 임의 뷰 투영
    i = json.load(open(HERE / f'ortho-{view}.json'))
    c = np.array(i['center']); r = np.array(i['right']); u = np.array(i['up'])
    d = np.asarray(p) - c
    return (np.dot(d, r) / i['ortho_scale'] + 0.5) * i['res'], (0.5 - np.dot(d, u) / i['ortho_scale']) * i['res']


img = mp.Image.create_from_file(str(HERE / 'ortho-front.png'))
det = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path=str(models / 'hand_landmarker.task')),
    num_hands=1, min_hand_detection_confidence=0.1, min_hand_presence_confidence=0.1))
r = det.detect(img)
assert r.hand_landmarks, 'MediaPipe 가 손을 못 찾음'
lm = r.hand_landmarks[0]
print('handedness(이미지 기준 라벨):', r.handedness[0][0].category_name, r.handedness[0][0].score)

# 레이캐스트: 정면 → +Y 광선. rtree 가 없어서 XZ 평면 무게중심 좌표로 직접 교차 (면 3만 × 점 21 이라 충분)
F = np.asarray(mesh.faces); T = V[F]  # (n,3,3)
def hits_y(x, z):
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    d = (b[:, 0] - a[:, 0]) * (c[:, 2] - a[:, 2]) - (c[:, 0] - a[:, 0]) * (b[:, 2] - a[:, 2])
    ok = np.abs(d) > 1e-12
    u = ((x - a[:, 0]) * (c[:, 2] - a[:, 2]) - (c[:, 0] - a[:, 0]) * (z - a[:, 2])) / np.where(ok, d, 1)
    v = ((b[:, 0] - a[:, 0]) * (z - a[:, 2]) - (x - a[:, 0]) * (b[:, 2] - a[:, 2])) / np.where(ok, d, 1)
    m = ok & (u >= 0) & (v >= 0) & (u + v <= 1)
    return (a[m, 1] + u[m] * (b[m, 1] - a[m, 1]) + v[m] * (c[m, 1] - a[m, 1]))
pts, spans = [], []
for l in lm:
    x, z = px2model(l.x * res, l.y * res)
    ys = hits_y(x, z)
    if len(ys) == 0:  # 실루엣 밖이면 가까운 정점으로 보정
        k = np.argmin((V[:, 0] - x) ** 2 + (V[:, 2] - z) ** 2)
        y0 = y1 = V[k, 1]; x, z = V[k, 0], V[k, 2]
    else:
        y0, y1 = ys.min(), ys.max()
    pts.append([x, (y0 + y1) / 2, z]); spans.append([y0, y1])
pts = np.array(pts); spans = np.array(spans)

# 손바닥 법선: 손목(0)·검지뿌리(5)·새끼뿌리(17) 외적. 정면 카메라가 손등을 본다고 가정하면 손바닥은 +Y (화면 안쪽) 이다.
P = pts[[0, 1, 2, 5, 9, 13, 17]]  # 손바닥 주변 점 평면 맞춤 (SVD 최소 특이벡터)
n = np.linalg.svd(P - P.mean(0))[2][-1]
# 단, 점의 y 는 레이 중간값이라 거의 평면이다 → 손바닥 쪽을 +Y 로 고정하고 기울기만 외적에서 가져온다.
if n[1] < 0: n = -n

# 손목 반지름: 손목 아래(정점 z 가 손목점보다 아래 0.02 구간) 단면의 평균 반경
wz = pts[0][2]
band = V[(V[:, 2] > V[:, 2].min()) & (V[:, 2] < V[:, 2].min() + 0.06 * (V[:, 2].max() - V[:, 2].min()))]
cx_, cy_ = band[:, 0].mean(), band[:, 1].mean()
wrist_radius = float(np.mean(np.hypot(band[:, 0] - cx_, band[:, 1] - cy_)) * 1.15)
wrist_center = [float(cx_), float(cy_), float(V[:, 2].min())]

out = {
    'frame': '세운 모델 좌표 (rig/front_ortho.py 와 같은 변환: GLB 를 X축 -90° 세움, Blender Z-up). 손가락 끝 = +Z, 손등 쪽 = -Y(정면 카메라 쪽), 손바닥 = +Y, 엄지 = -X',
    'pts': pts.tolist(), 'palm_normal': n.tolist(), 'wrist_radius': wrist_radius, 'wrist_center': wrist_center,
    'bounds': mesh.bounds.tolist(), 'mp_label': r.handedness[0][0].category_name,
    'depth_span': spans.tolist(),
}
json.dump(out, open(HERE / 'hand_R.json', 'w'), indent=1)
print('wrote hand_R.json, palm_normal', n, 'wrist_r', wrist_radius)

# 검증: 3개 뷰에 점을 그린다
for view in ['front', 'side', 'top']:
    f = HERE / f'ortho-{view}.png'
    if not f.exists(): continue
    im = Image.open(f).convert('RGB'); d = ImageDraw.Draw(im)
    for i, p in enumerate(pts):
        x, y = model2px(p, view)
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline='red', width=2); d.text((x + 6, y - 6), str(i), fill='blue')
    im.save(HERE / f'check-{view}.png')
