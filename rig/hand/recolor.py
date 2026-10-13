"""TRELLIS 가 손 텍스처를 단색 포화(빨강)로 구워서 몸 피부색으로 바꿔 입힌다.

  ~/Documents/GitHub/trellis-mac/.venv/bin/python rig/hand/recolor.py IN.glb OUT.glb R G B
  몸 텍스처(apose-s1-t42d)의 손 부분 중앙값 = (226,115,110), 전체 피부 중앙값 = (221,124,117).
"""
import sys
import numpy as np, trimesh
from PIL import Image
src, out = sys.argv[1], sys.argv[2]
rgb = tuple(int(x) for x in sys.argv[3:6])
m = trimesh.load(src, force='mesh')
img = Image.fromarray(np.full((64, 64, 3), rgb, np.uint8))
m.visual.material.baseColorTexture = img
m.visual.material.baseColorFactor = [255, 255, 255, 255]
m.export(out, include_normals=True)
print('wrote', out, m.visual.uv.shape, m.bounds.tolist())
