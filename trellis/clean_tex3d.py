"""몸 텍스처의 노이즈를 3D 공간에서 정리한다 (아틀라스 조각이 잘아서 이미지 필터는 조각 경계를 넘어 번진다).

  ~/Documents/GitHub/trellis-mac/.venv/bin/python trellis/clean_tex3d.py trellis/body-tex.glb trellis/body-tex-clean.glb [--cell 0.008]

1. 텍셀마다 3D 위치를 구한다 (UV 삼각형 래스터화).
2. 텍셀 색을 몇 갈래로 나눈다: 남색(재킷)·흰색(셔츠)·피부·어두운색(머리카락·눈).
3. 3D 칸(cell)으로 묶고, 각 텍셀의 갈래를 주변 27칸의 다수결로 다시 정한다 → 흰 실밥·남색 점 같은 튀는 점이 사라진다.
4. 텍셀 색 = 주변 27칸에서 같은 갈래 텍셀들의 평균 (갈래 경계는 그대로 날카롭고, 갈래 안은 매끈해진다).
UV·메시는 그대로 두고 텍스처만 바꾼다.
"""
import sys
import time

import numpy as np
import trimesh
from PIL import Image
from scipy.ndimage import distance_transform_edt

args = sys.argv[1:]
SRC, OUT = args[0], args[1]
CELL = float(args[args.index('--cell') + 1]) if '--cell' in args else 0.008

t0 = time.time()
m = trimesh.load(SRC, force='mesh', process=False)
V = np.asarray(m.vertices, np.float64)
Fc = np.asarray(m.faces)
UV = np.asarray(m.visual.uv, np.float64)
img = np.asarray(m.visual.material.baseColorTexture.convert('RGB')).astype(np.float32) / 255
H, W = img.shape[:2]
print(f'[tex3d] {len(V):,} verts, {len(Fc):,} faces, tex {W}x{H}')

# ───────── 1. 래스터화: 텍셀 → 3D 위치 (trimesh 는 GLB 를 읽을 때 v 를 뒤집어 준다 → 이미지 행 = (1-v)*H)
pos = np.zeros((H, W, 3), np.float32)
ok = np.zeros((H, W), bool)
px = np.stack([UV[:, 0] * W - 0.5, (1 - UV[:, 1]) * H - 0.5], 1)
for a, b, c in Fc:
    p0, p1, p2 = px[a], px[b], px[c]
    x0, x1 = max(int(np.floor(min(p0[0], p1[0], p2[0]))), 0), min(int(np.ceil(max(p0[0], p1[0], p2[0]))), W - 1)
    y0, y1 = max(int(np.floor(min(p0[1], p1[1], p2[1]))), 0), min(int(np.ceil(max(p0[1], p1[1], p2[1]))), H - 1)
    if x1 < x0 or y1 < y0:
        continue
    e1, e2 = p1 - p0, p2 - p0
    den = e1[0] * e2[1] - e2[0] * e1[1]
    if abs(den) < 1e-12:
        continue
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
    dx, dy = gx - p0[0], gy - p0[1]
    u = (dx * e2[1] - e2[0] * dy) / den
    w = (e1[0] * dy - dx * e1[1]) / den
    ins = (u >= -1e-3) & (w >= -1e-3) & (u + w <= 1 + 1e-3)
    if not ins.any():
        continue
    iy, ix = np.where(ins)
    uu, ww = u[iy, ix, None], w[iy, ix, None]
    pos[iy + y0, ix + x0] = (1 - uu - ww) * V[a] + uu * V[b] + ww * V[c]
    ok[iy + y0, ix + x0] = True
ys, xs = np.where(ok)
P = pos[ys, xs]
C = img[ys, xs]
print(f'[tex3d] texels {len(P):,} ({ok.mean() * 100:.1f}%) {time.time() - t0:.0f}s')

# ───────── 2. 갈래 나누기
r, g, b = C[:, 0], C[:, 1], C[:, 2]
L = 0.3 * r + 0.59 * g + 0.11 * b
lab = np.full(len(C), 3, np.int8)                      # 3 = 어두운색(머리카락·눈·그림자)
lab[(b - r > 0.03) & (L < 0.45)] = 0                   # 0 = 남색 재킷
lab[(L > 0.72) & (np.abs(r - b) < 0.12)] = 1           # 1 = 흰 셔츠
lab[(r > 0.45) & (r - b > 0.12)] = 2                   # 2 = 피부
NL = 4

# ───────── 3·4. 3D 칸 다수결 + 같은 갈래 평균
key3 = np.floor(P / CELL).astype(np.int64)
key3 -= key3.min(0)
dims = key3.max(0) + 3
def enc(k):
    return (k[:, 0] * dims[1] + k[:, 1]) * dims[2] + k[:, 2]
cell = enc(key3 + 1)
uniq, inv = np.unique(cell, return_inverse=True)
cnt = np.zeros((len(uniq), NL), np.float64)
csum = np.zeros((len(uniq), NL, 3), np.float64)
np.add.at(cnt, (inv, lab), 1)
np.add.at(csum, (inv, lab), C)
acc_cnt = np.zeros((len(P), NL))
acc_sum = np.zeros((len(P), NL, 3))
for dx in (-1, 0, 1):
    for dy in (-1, 0, 1):
        for dz in (-1, 0, 1):
            nb = enc(key3 + 1 + np.array([dx, dy, dz]))
            j = np.searchsorted(uniq, nb)
            j = np.clip(j, 0, len(uniq) - 1)
            hit = uniq[j] == nb
            wgt = 1.0 if (dx, dy, dz) == (0, 0, 0) else 0.6
            acc_cnt[hit] += cnt[j[hit]] * wgt
            acc_sum[hit] += csum[j[hit]] * wgt
new_lab = acc_cnt.argmax(1)
# 피부·어두운색(얼굴·손 근처)은 원래 갈래를 존중한다: 남색↔흰색 사이 잡음만 다수결로 고친다
keep = (lab >= 2) | (new_lab >= 2)
new_lab[keep] = lab[keep]
mean = acc_sum[np.arange(len(P)), new_lab] / np.maximum(acc_cnt[np.arange(len(P)), new_lab], 1e-6)[:, None]
# 갈래 안 평균에 원래 색의 아주 약간(주름 음영)을 섞는다
out_c = np.where(keep[:, None], C, 0.85 * mean + 0.15 * C)
changed = (new_lab != lab).mean() * 100
print(f'[tex3d] relabeled {changed:.2f}% texels, {time.time() - t0:.0f}s')

out = img.copy()
out[ys, xs] = out_c
# 아틀라스 빈 곳(차트 여백)은 가장 가까운 유효 텍셀 색으로
_, (ny, nx) = distance_transform_edt(~ok, return_indices=True)
out = out[ny, nx]
res = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))
m.visual.material.baseColorTexture = res
m.export(OUT, include_normals=True)
res.save(OUT.replace('.glb', '.png'))
print(f'[tex3d] wrote {OUT} ({time.time() - t0:.0f}s)')
