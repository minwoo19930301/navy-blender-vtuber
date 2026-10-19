"""머리 이식 뒤 rig.py 가 읽을 랜드마크를 만든다.

  python3 rig/merge_landmarks.py

입력: rig/body-front.json·body-front-landmarks.json (이식 전 몸 정면 렌더), rig/front.json·front-landmarks.json (이식 뒤 정면 렌더)
출력: rig/front-landmarks.json (덮어씀), rig/front-hands.json

- 포즈(어깨·팔꿈치·손목)는 이식 전 몸에서 찾은 값을 쓴다. 몸은 그대로라 같은 자리이고,
  이식 뒤 렌더는 머리가 커져 화면 배율이 달라 MediaPipe 포즈가 흔들린다. 그래서 픽셀 좌표만 새 렌더 배율로 옮긴다.
- 얼굴은 이식 뒤 렌더(새 머리)에서 찾은 값을 그대로 둔다.
- 손은 rig/hand/ 의 새 손을 쓰므로 비워 둔다 (rig.py 가 아래팔 연장선으로 임시 점을 만든다).
"""
import json
from pathlib import Path

H = Path(__file__).resolve().parent
old_o = json.load(open(H / 'body-front.json'))
old_l = json.load(open(H / 'body-front-landmarks.json'))
new_o = json.load(open(H / 'front.json'))
new_l = json.load(open(H / 'front-landmarks.json'))


def conv(p):
    r, s = old_o['res'], old_o['ortho_scale']
    x = old_o['cx'] + (p[0] - r / 2) / r * s
    z = old_o['cz'] - (p[1] - r / 2) / r * s
    r2, s2 = new_o['res'], new_o['ortho_scale']
    return [r2 / 2 + (x - new_o['cx']) / s2 * r2, r2 / 2 - (z - new_o['cz']) / s2 * r2] + list(p[2:])


new_l['pose'] = [conv(p) for p in old_l['pose']]
new_l['note'] = 'pose: 이식 전 몸 렌더에서 찾은 관절을 새 렌더 픽셀로 옮긴 값. face: 새 렌더(이식한 머리)에서 찾은 값'
json.dump(new_l, open(H / 'front-landmarks.json', 'w'))
json.dump({'L': None, 'R': None}, open(H / 'front-hands.json', 'w'))
print('[merge] wrote rig/front-landmarks.json, rig/front-hands.json')
