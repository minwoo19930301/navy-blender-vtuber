"""스칼라장 → 삼각형 메시 (surface nets). skimage 없이 numpy 만으로 마칭큐브 대신 쓴다.

rebake.py 가 UV 를 짜려고 만드는 "깨끗한 대리 메시"에만 쓴다. 최종 지오메트리가 아니다.
"""
import numpy as np


def surface_nets(f, iso=0.5):
    """f: (nx,ny,nz) float 장. f>iso 쪽이 안. 반환 (정점 [n,3] 격자 좌표, 면 [m,3]) — 면은 바깥을 향한다."""
    s = f > iso
    nx, ny, nz = s.shape
    cs = np.zeros((nx - 1, ny - 1, nz - 1), np.int8)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                cs += s[dx:nx - 1 + dx, dy:ny - 1 + dy, dz:nz - 1 + dz]
    mixed = (cs > 0) & (cs < 8)
    del cs
    ci = np.argwhere(mixed)                       # 섞인 셀
    vid = np.full(mixed.shape, -1, np.int32)
    vid[tuple(ci.T)] = np.arange(len(ci), dtype=np.int32)
    del mixed
    corner = [(dx, dy, dz) for dx in (0, 1) for dy in (0, 1) for dz in (0, 1)]
    val = {c: (f[ci[:, 0] + c[0], ci[:, 1] + c[1], ci[:, 2] + c[2]] - iso).astype(np.float64) for c in corner}
    acc = np.zeros((len(ci), 3))
    cnt = np.zeros(len(ci))
    for a in corner:
        for b in corner:
            if sum(abs(np.array(a) - np.array(b))) != 1 or a > b:
                continue
            va, vb = val[a], val[b]
            cross = (va > 0) != (vb > 0)
            t = np.where(cross, va / np.where(cross, va - vb, 1.0), 0.0)
            p = np.array(a)[None] + t[:, None] * (np.array(b) - np.array(a))[None]
            acc += np.where(cross[:, None], p, 0.0)
            cnt += cross
    verts = ci + acc / np.maximum(cnt, 1)[:, None]

    faces = []
    for ax in range(3):
        u, v = [(1, 2), (2, 0), (0, 1)][ax]
        n = s.shape[ax]
        a, b = s.take(range(0, n - 1), axis=ax), s.take(range(1, n), axis=ax)
        e = np.argwhere(a != b)                   # ax 방향 격자 모서리 (시작 정점)
        # 모서리를 둘러싼 셀 네 개: 모서리 시작 (i,j,k) 에서 u,v 축으로 -1..0
        ok = (e[:, u] >= 1) & (e[:, v] >= 1)
        # 다른 축 상한 (셀 범위)
        lim = np.array(vid.shape)
        ok &= (e[:, u] < lim[u]) & (e[:, v] < lim[v]) & (e[:, ax] < lim[ax])
        e = e[ok]
        flip = a[tuple(e.T)]                      # 시작 정점이 안이면 방향을 뒤집는다
        cells = []
        for du, dv in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
            c = e.copy()
            c[:, u] += du
            c[:, v] += dv
            cells.append(vid[tuple(c.T)])
        q = np.stack(cells, 1)
        good = (q >= 0).all(1)
        q, flip = q[good], flip[good]
        # 시작 정점이 안쪽이면 그대로, 아니면 뒤집어 면이 바깥을 향하게 한다
        q = np.where(flip[:, None], q, q[:, ::-1])
        faces.append(q[:, [0, 1, 2]])
        faces.append(q[:, [0, 2, 3]])
    return verts, np.concatenate(faces).astype(np.int32)
