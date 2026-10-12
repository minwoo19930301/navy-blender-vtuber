"""generate.py 가 남긴 *_bake.npz(복셀 색 + 메시)로 생성 없이 텍스처만 다시 굽는다.

  ~/Documents/GitHub/trellis-mac/.venv/bin/python trellis/rebake.py trellis/apose-s1-t42b_bake.npz trellis/out.glb [--size 2048] [--inset 0.6] [--k 4]

하는 일: 정점 병합 → 면 방향(winding) 통일·뒤집힘 보정 → xatlas UV(여백 포함, 결과는 *_uv.npz 로 캐시) → 복셀 색 굽기 → 법선 포함 GLB.
- TRELLIS 메시는 면 방향이 섞여 있어 단면 렌더(three.js 기본)에서 뒤집힌 면이 구멍처럼 빠져 보인다 → winding 통일.
- trellis-mac 의 KDTree 굽기는 텍셀 위치에서 가장 가까운 복셀들을 섞어서, 얇게 맞닿은 면(목과 깃, 이마와 앞머리)끼리 색이 번진다.
  여기서는 텍셀을 면 법선 반대쪽(표면 안쪽)으로 inset 복셀만큼 들여 놓고 찾는다. 맞은편 면의 복셀은 반대 방향이라 덜 잡힌다.
- 색은 감마 없이 그대로 쓴다 (공식 o_voxel.postprocess.to_glb 와 같다).
"""
import sys
import time
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path.home() / 'Documents/GitHub/trellis-mac'))
from backends.texture_baker import uv_unwrap  # noqa: E402

args = sys.argv[1:]
src, out = args[0], args[1]


def opt(name, default, cast=float):
    return cast(args[args.index(name) + 1]) if name in args else default


SIZE = opt('--size', 2048, int)
INSET = opt('--inset', 0.6)      # 표면 안쪽으로 들여 놓는 거리 (복셀 단위)
K = opt('--k', 4, int)           # 섞을 이웃 복셀 수
MAX_D = opt('--maxd', 1.5)       # 이보다 먼 복셀은 안 쓴다 (복셀 단위)

t0 = time.time()
d = np.load(src)
coords, attrs, origin, vs = d['coords'], d['attrs'], d['origin'], float(d['voxel_size'])

# ───────── UV (느리다: 20만 면에 약 40분) → 캐시
uv_cache = Path(src).with_name(Path(src).stem.replace('_bake', '') + '_uv.npz')
if uv_cache.exists():
    c = np.load(uv_cache)
    v, f, uvs = c['v'], c['f'], c['uvs']
    print(f'[rebake] uv cache {uv_cache.name}: {len(v):,} verts')
else:
    m = trimesh.Trimesh(d['bake_verts'], d['bake_faces'], process=True)
    m.update_faces(m.nondegenerate_faces())
    m.remove_unreferenced_vertices()
    trimesh.repair.fix_winding(m)
    trimesh.repair.fix_inversion(m)
    v, f, uvs, _ = uv_unwrap(np.asarray(m.vertices), np.asarray(m.faces), texture_size=SIZE)
    np.savez_compressed(uv_cache, v=v, f=f, uvs=uvs)
    print(f'[rebake] uv: {len(v):,} verts ({time.time() - t0:.0f}s) → {uv_cache.name}')

# ───────── UV 공간 래스터화: 텍셀마다 3D 위치와 면 번호
H = W = SIZE
pos = np.zeros((H, W, 3), np.float32)
fid = np.full((H, W), -1, np.int64)
px = np.stack([uvs[:, 0] * W - 0.5, (1.0 - uvs[:, 1]) * H - 0.5], 1).astype(np.float32)  # trimesh 가 GLB 로 낼 때 v 를 뒤집는다
for i, (a, b, c_) in enumerate(f):
    p0, p1, p2 = px[a], px[b], px[c_]
    x0, x1 = max(int(np.floor(min(p0[0], p1[0], p2[0]))), 0), min(int(np.ceil(max(p0[0], p1[0], p2[0]))), W - 1)
    y0, y1 = max(int(np.floor(min(p0[1], p1[1], p2[1]))), 0), min(int(np.ceil(max(p0[1], p1[1], p2[1]))), H - 1)
    if x1 < x0 or y1 < y0:
        continue
    e1, e2 = p1 - p0, p2 - p0
    den = e1[0] * e2[1] - e2[0] * e1[1]
    if abs(den) < 1e-12:
        continue
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1, dtype=np.float32), np.arange(y0, y1 + 1, dtype=np.float32))
    dx, dy = gx - p0[0], gy - p0[1]
    u = (dx * e2[1] - e2[0] * dy) / den
    w = (e1[0] * dy - dx * e1[1]) / den
    inside = (u >= -1e-3) & (w >= -1e-3) & (u + w <= 1 + 1e-3)
    if not inside.any():
        continue
    iy, ix = np.where(inside)
    uu, ww = u[iy, ix, None], w[iy, ix, None]
    ry, rx = (iy + y0), (ix + x0)
    pos[ry, rx] = (1 - uu - ww) * v[a] + uu * v[b] + ww * v[c_]
    fid[ry, rx] = i
mask = fid >= 0
print(f'[rebake] raster coverage {mask.mean() * 100:.1f}% ({time.time() - t0:.0f}s)')

# ───────── 복셀 색 샘플: 법선 반대로 들여 놓고 가까운 복셀 K 개를 거리 가중 평균
fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
q = pos[mask] - fn[fid[mask]] * (INSET * vs)
centers = coords.astype(np.float32) * vs + origin + vs * 0.5
dist, idx = cKDTree(centers).query(q, k=K, workers=-1)
if K == 1:
    dist, idx = dist[:, None], idx[:, None]
wgt = 1.0 / (dist + 0.1 * vs)
wgt[dist > MAX_D * vs] = 0
ok = wgt.sum(1) > 0
wgt /= np.maximum(wgt.sum(1, keepdims=True), 1e-12)
col = (attrs[idx] * wgt[..., None]).sum(1)

img = np.zeros((H, W, attrs.shape[1]), np.float32)
good = np.zeros((H, W), bool)
ys, xs = np.where(mask)
img[ys[ok], xs[ok]] = col[ok]
good[ys[ok], xs[ok]] = True
# 빈 텍셀(차트 밖·복셀 없음)은 가장 가까운 유효 텍셀 색으로 (차트 여백이 이중선형 보간에 섞여도 같은 색)
_, (ny, nx) = distance_transform_edt(~good, return_indices=True)
img = img[ny, nx]
print(f'[rebake] sampled {ok.mean() * 100:.1f}% texels with voxels ({time.time() - t0:.0f}s)')

base = (np.clip(img[..., 0:3], 0, 1) * 255).astype(np.uint8)
mr = np.zeros((H, W, 3), np.uint8)
if attrs.shape[1] > 4:
    mr[..., 1] = (np.clip(img[..., 4], 0, 1) * 255).astype(np.uint8)
    mr[..., 2] = (np.clip(img[..., 3], 0, 1) * 255).astype(np.uint8)
else:
    mr[..., 1] = 200

mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(base), metallicRoughnessTexture=Image.fromarray(mr),
                                          metallicFactor=0.0, roughnessFactor=1.0)
mesh.visual = trimesh.visual.TextureVisuals(uv=uvs, material=mat)
mesh.export(out, include_normals=True)
Image.fromarray(base).save(Path(out).with_suffix('.basecolor.png'))
print(f'[rebake] wrote {out} ({time.time() - t0:.0f}s)')
