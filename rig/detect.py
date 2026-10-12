"""정면 렌더에서 MediaPipe 포즈·손·얼굴 랜드마크를 찾아 픽셀 좌표로 저장하고 겹쳐 그린다.

  ~/Documents/GitHub/trellis-mac/.venv/bin/python rig/detect.py rig/front.png
  → rig/front-landmarks.json, rig/front-landmarks.png
"""
import json, sys
from pathlib import Path
import mediapipe as mp
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision
from PIL import Image, ImageDraw

src = Path(sys.argv[1])
models = Path(__file__).resolve().parent.parent / 'public/models'
img = mp.Image.create_from_file(str(src))
W, H = img.width, img.height
out = {'size': [W, H]}

pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path=str(models / 'pose_landmarker.task')), min_pose_detection_confidence=0.2))
r = pose.detect(img)
out['pose'] = [[l.x * W, l.y * H, l.visibility] for l in r.pose_landmarks[0]] if r.pose_landmarks else None

hands = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path=str(models / 'hand_landmarker.task')), num_hands=2, min_hand_detection_confidence=0.2))
r = hands.detect(img)
out['hands'] = [{'side': h[0].category_name, 'pts': [[l.x * W, l.y * H] for l in lm]} for h, lm in zip(r.handedness, r.hand_landmarks)]

face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path=str(models / 'face_landmarker.task')), min_face_detection_confidence=0.2))
r = face.detect(img)
out['face'] = [[l.x * W, l.y * H] for l in r.face_landmarks[0]] if r.face_landmarks else None

json.dump(out, open(src.with_name(src.stem + '-landmarks.json'), 'w'))
im = Image.open(src).convert('RGB'); d = ImageDraw.Draw(im)
def dot(p, c, r=5): d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=c)
if out['pose']:
    for i in [0, 11, 12, 13, 14, 15, 16, 23, 24]:
        dot(out['pose'][i], 'red', 8); d.text((out['pose'][i][0] + 8, out['pose'][i][1]), str(i), fill='red')
for h in out['hands']:
    for p in h['pts']: dot(p, 'lime', 4)
if out['face']:
    for i in [33, 133, 362, 263, 13, 14, 61, 291, 1]:
        dot(out['face'][i], 'blue', 4)
im.save(src.with_name(src.stem + '-landmarks.png'))
print('pose:', bool(out['pose']), 'hands:', [h['side'] for h in out['hands']], 'face:', bool(out['face']))
