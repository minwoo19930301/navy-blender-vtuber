"""손목 주변을 잘라 확대해서 손 랜드마크를 다시 찾는다 (전신 렌더에서는 손이 작아 한쪽을 놓친다).
잘라낸 손을 좌우 반전한 것도 같이 시도하고, 찾은 점은 원래 렌더 픽셀 좌표로 되돌려 front-hands.json 에 저장한다.
"""
import json
from pathlib import Path
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision
from PIL import Image, ImageDraw

here = Path(__file__).resolve().parent
lm = json.load(open(here / 'front-landmarks.json'))
im = Image.open(here / 'front.png').convert('RGB')
det = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path=str(here.parent / 'public/models/hand_landmarker.task')),
    num_hands=1, min_hand_detection_confidence=0.1, min_hand_presence_confidence=0.1))
P = lm['pose']
res = {}
for name, wi, ei in (('L', 15, 13), ('R', 16, 14)):  # 모델 기준 L = 화면 오른쪽
    wx, wy = P[wi][0], P[wi][1]
    ex, ey = P[ei][0], P[ei][1]
    # 팔꿈치→손목 방향으로 조금 더 나간 곳이 손 중심
    cx, cy = wx + (wx - ex) * 0.6, wy + (wy - ey) * 0.6
    half = 150
    box = (int(cx - half), int(cy - half), int(cx + half), int(cy + half))
    crop = im.crop(box).resize((600, 600))
    found = None
    for flip in (False, True):
        c = crop.transpose(Image.FLIP_LEFT_RIGHT) if flip else crop
        r = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(c)))
        if r.hand_landmarks:
            pts = []
            for l in r.hand_landmarks[0]:
                x = (1 - l.x) if flip else l.x
                pts.append([box[0] + x * (box[2] - box[0]), box[1] + l.y * (box[3] - box[1]), l.z])
            found = {'flip': flip, 'pts': pts}
            break
    res[name] = found
    print(name, 'found' if found else 'MISSING', 'flip' if found and found['flip'] else '')
json.dump(res, open(here / 'front-hands.json', 'w'))
d = ImageDraw.Draw(im)
for name, h in res.items():
    if not h: continue
    for i, p in enumerate(h['pts']):
        d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill='lime' if name == 'L' else 'orange')
    for a, b in [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(0,9),(9,10),(10,11),(11,12),(0,13),(13,14),(14,15),(15,16),(0,17),(17,18),(18,19),(19,20)]:
        d.line([tuple(h['pts'][a][:2]), tuple(h['pts'][b][:2])], fill='lime' if name == 'L' else 'orange', width=2)
im.crop((120, 700, 900, 1000)).resize((1560, 600)).save(here / 'front-hands.png')
