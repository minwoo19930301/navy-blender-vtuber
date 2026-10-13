"""절차 가중치 (numpy 만 쓴다). rig.py 가 불러 쓴다.

뼈 선분까지의 거리를 반경으로 나눠 "팔이냐 몸통이냐"를 가르고(게이트),
관절의 이등분 평면을 기준으로 위아래 뼈를 매끈하게 섞는다. 머리·머리카락은 head 1.0.
좌표는 앱 좌표(Blender Z 위, 정면 -Y)이고 L 쪽이 +x 다.
"""
import numpy as np

# 손으로 맞춘 값들. rig.py 에서 바꿔 넣을 수 있다.
CFG = dict(
    # 척추 구간 (z): 이 구간에서 위쪽 뼈로 넘어간다
    hips_spine=(0.10, 0.45), spine_chest=(0.65, 1.05), chest_neck=(1.12, 1.30),
    head_pad=(-0.12, 0.04),          # head.z 기준 머리 띠 (이 위는 head 1.0)
    # 팔 게이트: 소매 겉면에서 e 만큼 바깥까지 팔 가중치가 번진다 (band). front_k: 앞뒤로 벗어난 점을 덜 끌어가는 정도
    r_up=0.20, r_fo=0.19, sy=0.78,   # sy: 소매 단면이 앞뒤로 더 길어서(타원) y 를 줄여 잰다
    band=(0.0, 0.14), front_k=0.0,
    # 어깨 덮개: 목에서 어깨로 가는 윗면은 x(옆 거리)로 섞는다
    cap_x=(0.28, 0.55), cap_dz=(0.35, 0.05),
    # 관절 이등분 평면 기준 블렌드 반폭
    bw_elbow=0.16, bw_shoulder=0.20,
    smooth_iters=2, smooth_lam=0.5,
)


def ss(x, a, b):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / (np.linalg.norm(v) + 1e-12)


def seg_dist(P, a, b):
    """선분 a→b 까지의 거리 d 와, a 에서 축 방향 거리 t (잘리지 않음)"""
    ab = b - a
    L = np.linalg.norm(ab)
    u = ab / L
    t = (P - a) @ u
    c = a + np.clip(t, 0, L)[:, None] * u
    off = P - c
    return np.linalg.norm(off, axis=1), t, off


def torso_weights(z, head_z, cfg):
    s_hs = ss(z, *cfg['hips_spine'])
    s_sc = ss(z, *cfg['spine_chest'])
    s_cn = ss(z, *cfg['chest_neck'])
    s_nh = ss(z, head_z + cfg['head_pad'][0], head_z + cfg['head_pad'][1])
    return {'hips': 1 - s_hs, 'spine': s_hs - s_sc, 'chest': s_sc - s_cn, 'neck': s_cn - s_nh, 'head': s_nh}, s_nh


def arm_weights(P, side, C, S, E, W, s_nh, cfg):
    """한쪽 팔: (게이트, {shoulder, upper_arm, forearm} 가중치)"""
    # 소매 겉면에서 바깥으로 얼마나 떨어졌나(e). 앞뒤(y) 방향으로 떨어진 점(가슴·등)은 e 를 부풀려 팔을 덜 따라가게 한다.
    # 옆구리(x 방향)의 팔 겨드랑이 쪽 점만 팔과 함께 움직인다.
    sc = np.array([1.0, cfg['sy'], 1.0])
    d_up, _, o_up = seg_dist(P * sc, S * sc, E * sc)
    Wx = W + unit(W - E) * 0.25      # 소매 끝 아래쪽 자락까지 아래팔로 본다
    d_fo, _, o_fo = seg_dist(P * sc, E * sc, Wx * sc)
    use_up = (d_up - cfg['r_up']) < (d_fo - cfg['r_fo'])
    d = np.where(use_up, d_up, d_fo)
    o = np.where(use_up[:, None], o_up, o_fo)
    e = np.maximum(d - np.where(use_up, cfg['r_up'], cfg['r_fo']), 0)
    ydom = np.abs(o[:, 1]) / np.maximum(d, 1e-6)
    e_eff = e * (1 + cfg['front_k'] * ydom)
    gate_arm = 1 - ss(e_eff, *cfg['band'])
    xs = side * P[:, 0]
    gate_cap = ss(xs, *cfg['cap_x']) * ss(P[:, 2], S[2] - cfg['cap_dz'][0], S[2] - cfg['cap_dz'][1])
    gate = np.maximum(gate_arm, gate_cap) * (1 - s_nh)
    u_sh, u_up, u_fo = unit(S - C), unit(E - S), unit(W - E)
    ramp_e = ss((P - E) @ unit(u_up + u_fo), -cfg['bw_elbow'], cfg['bw_elbow'])
    ramp_s = ss((P - S) @ unit(u_sh + u_up), -cfg['bw_shoulder'], cfg['bw_shoulder'])
    return gate, {'forearm': ramp_e, 'upper_arm': (1 - ramp_e) * ramp_s, 'shoulder': (1 - ramp_e) * (1 - ramp_s)}


def smooth(W, edges, locked, iters, lam):
    """이웃 평균으로 가중치를 살짝 풀어 준다. locked 정점은 건드리지 않는다"""
    if iters <= 0:
        return W
    n = len(W)
    a, b = edges[:, 0], edges[:, 1]
    deg = np.bincount(np.concatenate([a, b]), minlength=n).astype(np.float64)
    deg[deg == 0] = 1
    free = (~locked)[:, None]
    for _ in range(iters):
        acc = np.zeros_like(W)
        np.add.at(acc, a, W[b])
        np.add.at(acc, b, W[a])
        W = np.where(free, (1 - lam) * W + lam * acc / deg[:, None], W)
    return W


def limit_normalize(W, k=4):
    """상위 k 개만 남기고 합 1 로"""
    if W.shape[1] > k:
        thr = np.sort(W, axis=1)[:, -k][:, None]
        W = np.where(W >= thr, W, 0.0)
    s = W.sum(axis=1, keepdims=True)
    return W / np.maximum(s, 1e-9)


def compute(P, J, names, edges=None, cfg=None, lock=None, zlow=0.65, ztop=1.0):
    """P: (N,3) 앱 좌표 정점, J: 관절 dict (np 배열), names: 뼈 이름 순서 → (N, B) 가중치"""
    cfg = {**CFG, **(cfg or {})}
    idx = {n: i for i, n in enumerate(names)}
    N = len(P)
    T, s_nh = torso_weights(P[:, 2], J['head'][2], cfg)
    gates, arms = [], []
    for side, tag in ((1, 'L'), (-1, 'R')):
        g, a = arm_weights(P, side, J[f'clavicle_{tag}'], J[f'shoulder_{tag}'], J[f'elbow_{tag}'], J[f'wrist_{tag}'], s_nh, cfg)
        gates.append((g, tag))
        arms.append(a)
    if lock is not None:
        # 접촉 구간(zlow~ztop)은 면을 끊어 놨으니 팔/몸통을 딱 갈라 준다. 그 밖은 거리 규칙
        lw = 1 - ss(P[:, 2], ztop, ztop + 0.12)   # zlow 아래도 면 분류를 따른다 (거리 규칙이면 밑단 옆면이 손·아래팔에 끌려간다)
        gates = [(lw * (lock == side) * (1 - s_nh) + (1 - lw) * g, tag) for (g, tag), side in zip(gates, (1, -1))]
    g_tot = np.clip(gates[0][0] + gates[1][0], 0, 1)
    W = np.zeros((N, len(names)))
    for n, w in T.items():
        W[:, idx[n]] += w * (1 - g_tot)
    for (g, tag), a in zip(gates, arms):
        for n, w in a.items():
            W[:, idx[f'{n}_{tag}']] += w * g
    locked = s_nh > 0.999
    if edges is not None:
        W = smooth(W, edges, locked, cfg['smooth_iters'], cfg['smooth_lam'])
    if lock is not None:
        # 면을 끊어 놓은 구간에서는 팔 면 정점이 몸통 뼈를, 몸통 면 정점이 팔 뼈를 갖지 않게 한다.
        # (이웃 평균이 경계를 넘어 섞이면 팔을 들 때 소매와 옆구리 사이에 막이 늘어난다)
        lw = 1 - ss(P[:, 2], ztop, ztop + 0.12)
        tor = np.array([i for n, i in idx.items() if n in ('hips', 'spine', 'chest', 'neck', 'head')])
        arm = np.array([i for n, i in idx.items() if n.startswith(('shoulder', 'upper_arm', 'forearm'))])
        side_ok = np.zeros((N, len(names)), bool)
        for tag, sd in (('L', 1), ('R', -1)):
            for n in ('shoulder', 'upper_arm', 'forearm'):
                side_ok[:, idx[f'{n}_{tag}']] = (lock == sd)
        far = (np.abs(P[:, 0]) > 0.4)[:, None]
        kill_arm = np.zeros_like(W)
        kill_arm[:, arm] = ((~side_ok[:, arm]) & far) * 1.0   # 몸통 정점(또는 반대쪽 팔 정점)의 팔 가중치
        kill_tor = np.zeros_like(W)
        kill_tor[:, tor] = ((lock != 0)[:, None] & far) * np.ones((1, len(tor)))
        kill = np.maximum(kill_arm, kill_tor) * lw[:, None]
        W = W * (1 - kill)
        # 합이 0 으로 떨어진 정점은 몸통 구간 가중치로 되돌린다
        dead = W.sum(axis=1) < 1e-6
        if dead.any():
            for n, w in T.items():
                W[dead, idx[n]] = w[dead]
    return limit_normalize(W)
