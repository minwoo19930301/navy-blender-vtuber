"""generate.py 가 남긴 *_bake.npz(복셀 색 + 메시)로 생성 없이 몸 텍스처 GLB 를 다시 만든다.

  ~/Documents/GitHub/trellis-mac/.venv/bin/python trellis/rebake.py trellis/apose-s1-t42b_bake.npz trellis/body-tex.glb
      [--size 2048] [--faces 118000] [--cut-z -0.43] [--iso 0.8] [--pad 2] [--smooth 5] [--despeckle 2]
      [--inset -0.5] [--k 4] [--maxd 2.5] [--behind 0.75] [--snap-max 2.2] [--ref trellis/apose-s1.png]
      [--no-color] [--no-brute] [--uv-only]
  (처음엔 약 45초. UV 는 trellis/<출력이름>_uv<size>.npz 에 캐시된다. 모든 기본값이 현재 최선이다.)

왜 이렇게 하나
TRELLIS 메시는 두 겹 이상 겹친 판·비다양체 모서리가 많아서(모서리 26% 가 3면 이상) xatlas 에 그대로 넣으면
차트가 3만 5천 조각으로 부서지고 40분이 걸리며 아틀라스의 22% 만 쓴다. 그래서 메시를 "새로 짠다".

파이프라인
1. 복셀 격자에서 바깥 공기를 채워 "속이 찬 몸" 장을 만들고 surface nets 로 깨끗한 다양체 메시를 뽑아
   --faces 면으로 줄인다 (대리 메시, 위상은 이게 최종 위상). 바지(--cut-z 아래)는 버린다. surfnets.py 는 skimage 대신 쓰는 numpy 구현.
2. 대리 메시에 xatlas (brute force 패킹, 8초대, 차트 약 2000개, 이용률 80%대).
3. 대리 정점을 진짜 TRELLIS 표면(속 겹·바지·찌꺼기를 뺀 면)의 가장 가까운 점으로 붙인다 (UV 는 그대로, 위치만).
   진짜 표면이 --snap-max 복셀보다 멀면(주머니처럼 바깥 겹이 빈 곳) 붙이지 않는다 (2.6%).
   그 뒤 몸통(목 아래)만 Taubin 평활 (얼굴은 눈 가장자리에 뾰족한 조각이 생겨서 뺀다).
   실루엣은 원본과 같다 (rig/front.png 와 비교, 바지 자른 것만 다름).
4. UV 공간에서 텍셀마다 3D 위치를 구해 복셀 색을 굽는다. 바깥에서 보이는 복셀(공기와 닿는 것)만, 표면에서 살짝 바깥 점을
   기준으로 가까운 것을 거리^2 가중으로 쓴다. 몸통은 표면 뒤쪽 복셀(재킷 뒤 셔츠 등)을 뺀다.
   몸통 복셀은 먼저 중앙값+양방향 필터로 잡티를 지운다 (재킷 가슴·주머니의 점무늬는 안쪽 겹 복셀이 섞인 것이었다).
5. 색 보정: 정면 투영(바깥 복셀)을 생성 입력 이미지(apose-s1.png)에 실루엣 IoU 로 맞추고, 같은 자리 색 쌍으로
   색 이동량(군집 64개의 중앙값)을 구해 부드럽게 적용한다. TRELLIS 알베도는 피부가 분홍, 재킷이 짙은 파랑으로 쏠려 있다.

출력 규약
- 입력과 같은 좌표(눕혀서 높이 1, z 위). rig.py 가 그대로 읽는다 (hem_z, top_z 계산이 같다). 면 수는 12만 이하라 rig 가 다시 줄이지 않는다.
- 재킷 밑단 아래는 rig.py 가 어차피 자른다 (hem_z=-0.400, bisect -0.406). --cut-z 는 그보다 0.025 아래.
- 주의: 피부가 생성 입력과 같은 살구색이라 rig.py 의 is_skin (R-G>0.2) 에 안 걸린다. 리깅 쪽 기준을 풀어야 한다.
"""
import sys
import time
from pathlib import Path

import numpy as np
import trimesh
import xatlas
import fast_simplification as fs
import scipy.sparse as sp
import scipy.sparse.csgraph as cg
from PIL import Image
from scipy import ndimage as ndi
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from surfnets import surface_nets  # noqa: E402

args = sys.argv[1:]
src, out = args[0], args[1]


def opt(name, default, cast=float):
    return cast(args[args.index(name) + 1]) if name in args else default


SIZE = opt('--size', 2048, int)
CUT_Z = opt('--cut-z', -0.43)               # 이 아래(바지)는 버린다. 끄려면 -9
PROXY_FACES = opt('--faces', 118000, int)   # 대리 메시 면 수 = 최종 면 수 (바지를 자르면 약 3% 줄어든다)
PAD = opt('--pad', 2, int)                  # 차트 사이 여백 (텍셀)
DESPECKLE = opt('--despeckle', 2, int)       # 몸통 복셀 중앙값 필터 횟수 (0 이면 끔)
NECK_Z = opt('--neck-z', -0.02)             # 이 위(머리)는 잡티 제거를 안 한다
SNAP_MAX = opt('--snap-max', 2.2)           # 대리 정점이 진짜 표면에서 이보다 멀면 붙이지 않는다 (복셀 단위)
SMOOTH = opt('--smooth', 5, int)             # 몸통 지오메트리 Taubin 평활 횟수 (0 이면 끔)
ERODE = opt('--erode', 0, int)              # 대리 메시를 안쪽으로 깎는 복셀 수 (많이 깎으면 얇은 곳이 끊겨 차트가 부서진다)
ISO = opt('--iso', 0.8)                     # 대리 메시 등치면 (0.5 보다 크면 안쪽으로 붙는다)
INSET = opt('--inset', -0.5)                # 표면에서 안쪽으로 들여 놓는 거리 (복셀 단위). 음수면 바깥으로 — 재킷이 얇은 곳에서 뒤의 셔츠 복셀을 안 집으려고 바깥에서 찾는다
BEHIND = opt('--behind', 0.75)               # 표면 뒤로 이만큼(복셀) 넘게 들어간 복셀은 색 샘플에서 뺀다
WPOW = opt('--wpow', 2.0)                   # 거리 가중 지수 (클수록 가장 가까운 겉 복셀이 이긴다)
K = opt('--k', 4, int)                      # 섞을 이웃 복셀 수
MAX_D = opt('--maxd', 2.5)                  # 이보다 먼 복셀은 안 쓴다 (복셀 단위)
REF = args[args.index('--ref') + 1] if '--ref' in args else str(Path(__file__).resolve().parent / 'apose-s1.png')
T0 = time.time()


def log(*a):
    print(f'[rebake {time.time() - T0:5.0f}s]', *a, flush=True)


d = np.load(src)
coords = d['coords'].astype(np.int64)
attrs = d['attrs']
origin = d['origin'].astype(np.float64)
vs = float(d['voxel_size'])
N = int(round(1.0 / vs))
centers = coords * vs + origin + vs * 0.5
log(f'voxels {len(coords):,}  grid {N}  vs {vs:.5f}')

# ───────── 1. 바깥에서 보이는 복셀 + "속이 찬 몸" 장
PADV = 3
lo = coords.min(0) - PADV - 2
hi = coords.max(0) + PADV + 3
shape = tuple(hi - lo)
occ = np.zeros(shape, bool)
occ[tuple((coords - lo).T)] = True
st = ndi.generate_binary_structure(3, 3)
dil = ndi.binary_dilation(occ, structure=st, iterations=1)       # 작은 구멍을 막고
lab, _ = ndi.label(~dil)
outside = lab == lab[0, 0, 0]                                       # 바깥 공기
del lab, dil
near_out = ndi.binary_dilation(outside, structure=st, iterations=2)  # 막은 만큼 되돌려 원래 복셀과 닿게
ext = near_out[tuple((coords - lo).T)]
solid = ~outside
del near_out, outside
log(f'exterior voxels {ext.mean() * 100:.1f}%')

# ───────── 1b. 복셀 색 잡티 제거: 재킷에 보라·붉은 점과 밝은 세로줄이 박혀 있다 (생성 이미지에는 없다).
# 몸통(목 아래)의 바깥 복셀만 이웃 K 개의 중앙값으로 바꾼다. 중앙값은 경계(깃·셔츠 선)를 살린다. 얼굴·머리는 눈이 있어 건드리지 않는다.
colv = attrs[:, 0:3].copy()


def bilateral(col_e, ce, etree, idx_sel, use_median, sc):
    """idx_sel 복셀만 이웃 64 개의 (선택적 중앙값 →) 색·거리 가중 평균으로 바꾼다. 색 차이가 큰 이웃은 거의 안 섞여 경계가 산다"""
    new_e = col_e.copy()
    for s0 in range(0, len(idx_sel), 100000):
        ii = idx_sel[s0:s0 + 100000]
        dd, nn = etree.query(ce[ii], k=64, workers=-1)
        cn = col_e[nn]                                                  # [n,64,3]
        ref_c = np.median(cn[:, :27], axis=1) if use_median else col_e[ii]
        dc = np.linalg.norm(cn - ref_c[:, None], axis=2)
        w = np.exp(-(dd / (3 * vs)) ** 2 / 2) * np.exp(-(dc / sc) ** 2 / 2) + 1e-9
        new_e[ii] = (cn * w[..., None]).sum(1) / w.sum(1, keepdims=True)
    return new_e


if DESPECKLE > 0:
    ce = centers[ext]
    etree = cKDTree(ce)
    col_e = colv[ext]
    is_body = (centers[ext][:, 2] < NECK_Z)
    bi, hi_ = np.where(is_body)[0], np.where(~is_body)[0]
    for it_ in range(DESPECKLE):
        col_e = bilateral(col_e, ce, etree, bi, True, 0.1)              # 몸통: 중앙값으로 튀는 점을 누르고 평균
    col_e = bilateral(col_e, ce, etree, hi_, False, 0.06)               # 머리: 눈·눈썹 같은 센 경계는 그대로, 피부 결만 편다
    colv[ext] = col_e
    log(f'despeckle: 몸통 {len(bi):,} 개 (중앙값+양방향 x{DESPECKLE}), 머리 {len(hi_):,} 개 (양방향)')

# ───────── 2. 진짜 메시 정리: 병합·중복면·떠다니는 조각·속 겹·바지 제거 → 데시메이트
m = trimesh.Trimesh(d['bake_verts'], d['bake_faces'], process=True)
m.update_faces(m.nondegenerate_faces())
m.update_faces(m.unique_faces())
m.remove_unreferenced_vertices()
trimesh.repair.fix_winding(m)
trimesh.repair.fix_inversion(m)
v0, f0 = np.asarray(m.vertices), np.asarray(m.faces)
n_v = len(v0)
A = sp.coo_matrix((np.ones(len(f0) * 3), (f0.ravel(), f0[:, [1, 2, 0]].ravel())), shape=(n_v, n_v))
_, comp = cg.connected_components(A, directed=False)
csize = np.bincount(comp[f0[:, 0]], minlength=comp.max() + 1)
keep = csize[comp[f0[:, 0]]] >= 100                                  # 100면 미만 조각은 떠다니는 찌꺼기
vtree_all = cKDTree(centers)
cen_f = v0[f0].mean(1)
dnn, inn = vtree_all.query(cen_f, k=6)
face_ext = ext[inn].mean(1)                                          # 면 근처 복셀 중 바깥에서 보이는 비율
keep &= face_ext > 0                                                 # 이웃 복셀이 전부 속 겹이면 안 보이는 면
keep &= cen_f[:, 2] > CUT_Z
log(f'faces {len(f0):,} → keep {keep.sum():,} (조각 {np.sum(csize[comp[f0[:, 0]]] < 100):,}, 속 겹 {np.sum(face_ext == 0):,}, 바지 {np.sum(cen_f[:, 2] <= CUT_Z):,})')
f1 = f0[keep]
ra, rb, rc = v0[f1[:, 0]], v0[f1[:, 1]], v0[f1[:, 2]]               # 진짜 표면 (속 겹·바지 뺀 것) — 대리 메시 정점을 여기로 붙인다
rtree = cKDTree((ra + rb + rc) / 3)
log(f'real surface: {len(f1):,} faces')

def closest_bary(P, a, b, c):
    """점 P 에서 삼각형 abc 까지 가장 가까운 점의 무게중심 좌표 [n,3] 과 거리 (Ericson, 영역 판정 우선순위 그대로)"""
    n = len(P)
    ab, ac, ap = b - a, c - a, P - a
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = P - b
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = P - c
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4
    z = np.zeros(n)
    one = np.ones(n)
    with np.errstate(all='ignore'):
        den = 1.0 / (va + vb + vc)
        v_, w_ = vb * den, vc * den
        bary = np.stack([1 - v_ - w_, v_, w_], 1)                                   # 7. 안쪽
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        # 낮은 우선순위부터 덮어쓴다 (1번이 가장 높다)
        for mask, w in (
            ((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), np.stack([z, 1 - t, t], 1)),                  # 6. 변 bc
            ((vb <= 0) & (d2 >= 0) & (d6 <= 0), np.stack([1 - d2 / (d2 - d6), z, d2 / (d2 - d6)], 1)),      # 5. 변 ac
            ((d6 >= 0) & (d5 <= d6), np.stack([z, z, one], 1)),                                              # 4. 점 c
            ((vc <= 0) & (d1 >= 0) & (d3 <= 0), np.stack([1 - d1 / (d1 - d3), d1 / (d1 - d3), z], 1)),      # 3. 변 ab
            ((d3 >= 0) & (d4 <= d3), np.stack([z, one, z], 1)),                                              # 2. 점 b
            ((d1 <= 0) & (d2 <= 0), np.stack([one, z, z], 1)),                                               # 1. 점 a
        ):
            bary = np.where(mask[:, None], w, bary)
    bad = ~np.isfinite(bary).all(1)                                                 # 넓이 0 삼각형
    bary[bad] = [1.0, 0.0, 0.0]
    pt = bary[:, 0:1] * a + bary[:, 1:2] * b + bary[:, 2:3] * c
    return bary, np.linalg.norm(P - pt, axis=1)


# ───────── 3. 대리 메시(깨끗한 다양체) → xatlas → 정점을 진짜 표면으로 붙인다
uv_cache = Path(src).with_name(Path(out).stem + f'_uv{SIZE}.npz')
meta = np.array([SIZE, PROXY_FACES, CUT_Z, PAD, len(f1), ERODE, ISO, SNAP_MAX, opt('--maxcost', 2.0), '--no-brute' not in args, SMOOTH, 12])
if uv_cache.exists() and np.array_equal(np.load(uv_cache)['meta'], meta):
    c = np.load(uv_cache)
    sv, sf, uv = c['sv'], c['sf'], c['uv']
    log(f'uv cache {uv_cache.name}')
else:
    from scipy.ndimage import gaussian_filter
    solid_e = ndi.binary_erosion(solid, structure=st, iterations=ERODE) if ERODE else solid        # 닫느라 부푼 만큼 되돌린다
    fld = gaussian_filter(solid_e.astype(np.float32), 1.0)
    gv, gf = surface_nets(fld, ISO)
    gv = (gv + lo) * vs + origin + vs * 0.5                          # 격자 → 모델 좌표 (인덱스 g 의 장 값은 복셀 g 의 중심)
    log(f'surface nets {len(gv):,} verts {len(gf):,} faces')
    px, pxf = fs.simplify(gv.astype(np.float32), gf.astype(np.int32), target_count=PROXY_FACES)
    pm = trimesh.Trimesh(px, pxf, process=False)
    pm.update_faces(pm.nondegenerate_faces())
    pm.update_faces(pm.triangles_center[:, 2] > CUT_Z)                  # 바지 쪽 면은 버린다
    pm.remove_unreferenced_vertices()
    at = xatlas.Atlas()
    at.add_mesh(np.ascontiguousarray(pm.vertices, np.float32), np.ascontiguousarray(pm.faces, np.uint32))
    po = xatlas.PackOptions()
    po.padding = PAD
    po.resolution = SIZE
    po.bilinear = True
    po.bruteForce = '--no-brute' not in args
    co = xatlas.ChartOptions()
    co.max_cost = opt('--maxcost', 2.0)
    at.generate(chart_options=co, pack_options=po)
    vmap, idx, uv = at[0]
    log(f'xatlas: {len(idx) // 3:,} faces, {at.chart_count} charts, utilization {at.utilization * 100:.0f}%')
    # 정점마다 진짜 표면의 가장 가까운 점으로 (차트·UV 는 그대로, 위치만 옮긴다)
    pvv = np.asarray(pm.vertices, np.float64)
    _, cand = rtree.query(pvv, k=16, workers=-1)
    cf = cand.ravel()
    bary, dist = closest_bary(np.repeat(pvv, 16, 0), ra[cf], rb[cf], rc[cf])
    dist = dist.reshape(-1, 16)
    sel = dist.argmin(1)
    tri = cand[np.arange(len(pvv)), sel]
    bsel = bary.reshape(-1, 16, 3)[np.arange(len(pvv)), sel]
    snapped = bsel[:, 0:1] * ra[tri] + bsel[:, 1:2] * rb[tri] + bsel[:, 2:3] * rc[tri]
    # 진짜 표면이 너무 먼 곳(주머니처럼 바깥 겹이 비고 속 겹만 남은 곳)은 붙이지 않는다 — 속 겹으로 파고들어 얼룩이 된다
    far = dist.min(1) > SNAP_MAX * vs
    snapped[far] = pvv[far]
    log(f'snap 건너뜀(너무 멂): {far.mean() * 100:.1f}%')
    log(f'snap: 이동 거리 중앙값 {np.median(dist.min(1)) / vs:.2f} 복셀, 99% {np.percentile(dist.min(1), 99) / vs:.2f}')
    if SMOOTH > 0:                                                     # 진짜 표면의 잔 요철(얼굴·재킷이 얼룩덜룩해 보이는 원인)을 약하게 편다. 부피는 지킨다 (Taubin)
        sm_ = trimesh.Trimesh(snapped, pm.faces, process=False)
        trimesh.smoothing.filter_taubin(sm_, lamb=0.5, nu=0.53, iterations=SMOOTH)
        # 얼굴도 편다. 다만 어두운 복셀(눈·눈썹·입·머리카락) 2 복셀 안의 정점은 고정한다 (거기서 눈가 뾰족한 조각이 생겼다)
        dark_v = ext & (centers[:, 2] > NECK_Z) & ((colv * np.array([0.299, 0.587, 0.114])).sum(1) < 0.35)
        dd_, _ = cKDTree(centers[dark_v]).query(snapped, workers=-1)
        pin = np.clip((3.5 * vs - dd_) / (1.5 * vs), 0, 1)               # 2 복셀 안 = 1, 3.5 복셀 밖 = 0
        bl = (1.0 - pin)[:, None]
        log(f'smooth: 고정 정점 {np.mean(pin > 0.99) * 100:.1f}%')
        snapped = snapped + (np.asarray(sm_.vertices) - snapped) * bl
    sv = snapped[vmap]
    sf = idx.reshape(-1, 3).astype(np.int64)
    np.savez_compressed(uv_cache, sv=sv, sf=sf, uv=uv, meta=meta)
log(f'final mesh: {len(sv):,} verts {len(sf):,} faces')
sm = trimesh.Trimesh(sv, sf, process=False)
snrm = np.asarray(sm.vertex_normals, np.float64)
face_ext = np.ones(len(sf))
if '--uv-only' in args:
    sys.exit(0)

# ───────── 5. UV 공간 래스터화: 텍셀마다 3D 위치·면 번호 (바깥 면이 마지막에 그려져 이긴다)
H = W = SIZE
pos = np.zeros((H, W, 3), np.float32)
fid = np.full((H, W), -1, np.int64)
pxy = np.stack([uv[:, 0] * W - 0.5, (1.0 - uv[:, 1]) * H - 0.5], 1).astype(np.float32)  # trimesh 가 GLB 로 낼 때 v 를 뒤집는다
for i in np.argsort(face_ext, kind='stable'):
    a, b, c_ = sf[i]
    p0, p1, p2 = pxy[a], pxy[b], pxy[c_]
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
    pos[ry, rx] = (1 - uu - ww) * sv[a] + uu * sv[b] + ww * sv[c_]
    fid[ry, rx] = i
mask = fid >= 0
log(f'raster coverage {mask.mean() * 100:.1f}%')

# ───────── 6. 복셀 색 샘플: 표면 안쪽으로 inset 한 점에서 가까운 "바깥 복셀" K 개를 거리 가중 평균
fn = np.cross(sv[sf[:, 1]] - sv[sf[:, 0]], sv[sf[:, 2]] - sv[sf[:, 0]])
fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
q = pos[mask].astype(np.float64) - fn[fid[mask]] * (INSET * vs)
tree_ext = cKDTree(centers[ext])
col_ext = np.concatenate([colv[ext], attrs[ext][:, 3:]], 1)
dist, idx = tree_ext.query(q, k=K, workers=-1)
wgt = 1.0 / (dist + 0.1 * vs) ** WPOW
wgt[dist > MAX_D * vs] = 0
# 표면보다 BEHIND 만큼 뒤에 있는 복셀(재킷 앞면 뒤의 셔츠·안감)은 안 쓴다. 법선은 바깥을 향한다
rel = centers[ext][idx] - pos[mask][:, None].astype(np.float64)
wgt[((rel * fn[fid[mask]][:, None]).sum(-1) < -BEHIND * vs) & (pos[mask][:, 2:3] < NECK_Z)] = 0   # 몸통만 (얼굴은 눈 가장자리가 거칠어진다)
ok = wgt.sum(1) > 0
wgt /= np.maximum(wgt.sum(1, keepdims=True), 1e-12)
col = (col_ext[idx] * wgt[..., None]).sum(1)
if (~ok).any():                                                        # 조건에 맞는 겉 복셀이 없으면 거리·방향 제한 없이 가장 가까운 겉 복셀
    d2, i2 = tree_ext.query(q[~ok], k=K, workers=-1)
    w2 = 1.0 / (d2 + 0.1 * vs) ** WPOW
    w2 /= w2.sum(1, keepdims=True)
    col[~ok] = (col_ext[i2] * w2[..., None]).sum(1)
log(f'sampled: 바깥 복셀 {ok.mean() * 100:.1f}% / 제한 없이 최근접으로 대체 {(~ok).mean() * 100:.1f}%')

img = np.zeros((H, W, attrs.shape[1]), np.float32)
good = np.zeros((H, W), bool)
ys, xs = np.where(mask)
img[ys, xs] = col
good[ys, xs] = True
# 빈 텍셀(차트 밖)은 가장 가까운 유효 텍셀 색으로 (차트 여백이 이중선형 보간에 섞여도 같은 색)
_, (ny, nx) = distance_transform_edt(~good, return_indices=True)
img = img[ny, nx]

# ───────── 7. 색 보정: 정면 투영(바깥 복셀)을 생성 입력 이미지에 맞춰 놓고, 같은 자리 색 쌍으로 색 변환을 맞춘다
# TRELLIS 의 알베도는 피부가 분홍·재킷이 짙은 파랑으로 쏠려 있다. 같은 자리 쌍이라 셔츠·피부·머리가 섞이지 않는다.
rgb = np.clip(img[..., 0:3], 0, 1)
if '--no-color' not in args and Path(REF).exists():
    from scipy.cluster.vq import kmeans2
    from scipy.optimize import minimize
    R_ = 1024
    scale = 1.08  # front.json 의 ortho_scale 과 같은 틀
    ext_c = centers[ext]
    ext_col = np.clip(colv[ext], 0, 1)
    sx = ext_c[:, 0] / scale * R_ + R_ / 2
    sy = -ext_c[:, 2] / scale * R_ + R_ / 2
    order = np.argsort(-ext_c[:, 1])                                   # y 작은 쪽이 앞 → 먼 것부터 그려 가까운 것이 덮는다
    sp_img = np.ones((R_, R_, 3), np.float32)
    sp_msk = np.zeros((R_, R_), bool)
    r = int(np.ceil(vs / scale * R_ * 0.75))
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            qx, qy = (sx[order] + dx).astype(int), (sy[order] + dy).astype(int)
            okq = (qx >= 0) & (qx < R_) & (qy >= 0) & (qy < R_)
            sp_img[qy[okq], qx[okq]] = ext_col[order][okq]
            sp_msk[qy[okq], qx[okq]] = True
    sp_msk = ndi.binary_fill_holes(sp_msk)
    ref = np.asarray(Image.open(REF).convert('RGB').resize((R_, R_), Image.LANCZOS), np.float32) / 255
    ref_msk = ndi.binary_fill_holes((1 - ref).max(-1) > 30 / 255)
    # 실루엣 IoU 로 정렬 (x,y 배율 + 이동)
    sm_s, rm_s = ndi.zoom(sp_msk.astype(np.float32), 0.25, order=1), ndi.zoom(ref_msk.astype(np.float32), 0.25, order=1)

    def warp(img, p_, shape=None):
        a_, b_, tx_, ty_ = p_
        return ndi.affine_transform(img, [1 / b_, 1 / a_], offset=[-ty_ / b_, -tx_ / a_], order=1, output_shape=shape or img.shape)

    def cost(p_):
        w = warp(sm_s, [p_[0], p_[1], p_[2] * 10, p_[3] * 10])
        return 1 - (w * rm_s).sum() / (w + rm_s - w * rm_s).sum()

    bestr = min((minimize(cost, [a0, a0, 0.1, 0.1], method='Nelder-Mead', options={'xatol': 1e-3, 'fatol': 1e-5, 'maxiter': 400}) for a0 in (0.9, 1.0, 1.1)), key=lambda r_: r_.fun)
    pa_ = bestr.x.copy()
    pa_[2:] *= 40                                                       # 1/4 해상도 이동 단위 → 원해상도 픽셀
    log(f'color align: IoU {1 - bestr.fun:.3f} scale ({pa_[0]:.3f},{pa_[1]:.3f}) shift ({pa_[2]:.1f},{pa_[3]:.1f})')
    smw = warp(sp_msk.astype(np.float32), pa_)
    spw = np.stack([warp(sp_img[..., i] * sp_msk, pa_) for i in range(3)], -1) / np.maximum(smw[..., None], 1e-3)
    valid = ndi.binary_erosion((smw > 0.99) & ref_msk, iterations=4)

    def lstd(im, size=7):
        m1, m2 = ndi.uniform_filter(im, (size, size, 1)), ndi.uniform_filter(im * im, (size, size, 1))
        return np.sqrt(np.maximum(m2 - m1 * m1, 0)).max(-1)

    use = valid & (lstd(spw) < 0.02) & (lstd(ref) < 0.02)               # 경계·잔무늬 빼고 평평한 곳만 짝으로 쓴다
    Sc, Tc = spw[use], ref[use]
    cen_c, _ = kmeans2(Sc[::3], 64, seed=1, minit='++')
    lab_c = cKDTree(cen_c).query(Sc)[1]
    cnt_c = np.bincount(lab_c, minlength=len(cen_c))
    delta_c = np.zeros((len(cen_c), 3))
    for k_ in range(len(cen_c)):
        if cnt_c[k_] > 30:
            delta_c[k_] = np.median((Tc - Sc)[lab_c == k_], 0)          # 군집마다 색 이동량 (중앙값)
    good_c = cnt_c > 30
    cen_c, delta_c = cen_c[good_c], delta_c[good_c]
    ctree = cKDTree(cen_c)
    log(f'color pairs {use.sum():,}, centers {len(cen_c)}')

    def correct(c):
        dist, idx = ctree.query(c, k=8, workers=-1)
        w = np.exp(-(dist / 0.06) ** 2 / 2)
        # 짝이 없던 색(눈 가장자리의 회색 등)은 이웃 군집 값을 억지로 끌어오지 않고 보정을 줄인다
        return np.clip(c + (delta_c[idx] * w[..., None]).sum(1) / np.maximum(w.sum(1, keepdims=True), 0.4), 0, 1)

    rgb = correct(rgb.reshape(-1, 3).astype(np.float64)).reshape(H, W, 3).astype(np.float32)
    log('color corrected')

# ───────── 8. 군집 후처리 (texclean.py): 경계 털·점·보라 얼룩·청록 눈썹 정리, 피부 양방향, 색 이동
if '--no-clean' not in args:
    from texclean import clean
    Av = sp.coo_matrix((np.ones(len(sf) * 2), (np.concatenate([sf[:, 0], sf[:, 1]]), np.concatenate([sf[:, 1], sf[:, 2]]))), shape=(len(sv), len(sv)))
    ncomp, vcomp = cg.connected_components(Av, directed=False)
    chart_f = vcomp[sf[:, 0]]
    cid = np.where(mask, chart_f[np.maximum(fid, 0)], -1)[ny, nx].astype(np.int32)   # 여백 텍셀은 가장 가까운 차트 번호
    zt = pos[..., 2][ny, nx]
    log(f'charts {ncomp}')
    if '--stage' in args:
        np.savez_compressed(Path(out).with_name('body-tex_stage.npz'), rgb=rgb * 255, cid=cid, zt=zt, mask=mask, pos=pos[ny, nx])
    rgb = clean((rgb * 255).astype(np.float32), cid, pos[ny, nx], mask, NECK_Z, log) / 255
    log('texclean done')

base = (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)
mr = np.zeros((H, W, 3), np.uint8)
if attrs.shape[1] > 4:
    mr[..., 1] = (np.clip(img[..., 4], 0, 1) * 255).astype(np.uint8)
    mr[..., 2] = (np.clip(img[..., 3], 0, 1) * 255).astype(np.uint8)
else:
    mr[..., 1] = 200

mesh = trimesh.Trimesh(vertices=sv, faces=sf, vertex_normals=snrm, process=False)
mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(base), metallicRoughnessTexture=Image.fromarray(mr),
                                          metallicFactor=0.0, roughnessFactor=1.0)
mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=mat)
mesh.export(out, include_normals=True)
Image.fromarray(base).save(Path(out).with_suffix('.basecolor.png'))
log(f'wrote {out}  ({len(sf):,} faces, {len(sv):,} verts)')
