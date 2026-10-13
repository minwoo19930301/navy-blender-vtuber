"""rebake.py 가 굽은 베이스컬러를 군집 기준으로 정리한다 (UV 공간, 차트 안에서만).

복셀 색은 경계(깃·셔츠·머리선)에 하얀 털 같은 테두리, 주머니의 보라·자주 얼룩, 피부의 점·삼각 얼룩, 청록 눈썹이 남는다.
그래서 색을 군집(머리/재킷/셔츠/피부)으로 나눠 다수결로 경계를 정리하고, 군집 대표색 x 부드러운 밝기비로 다시 칠한다.
피부만 양방향 필터로 편다 (진짜 음영은 살린다). 모든 필터는 같은 차트 텍셀끼리만 섞는다.
"""
import numpy as np
from scipy.cluster.vq import kmeans2
from scipy.spatial import cKDTree

# 군집 대표색 (생성 입력 apose-s1.png 에서 잰 값). 번호 = 클래스
DARK, JACKET, SHIRT, SKIN, HILITE = 0, 1, 2, 3, 4      # HILITE: 눈의 하이라이트
PROTO = np.array([
    (32, 31, 43), (42, 46, 70), (239, 234, 225), (238, 192, 170), (210, 155, 135), (20, 20, 24), (130, 110, 120),
], np.float32)
PROTO_CLS = [DARK, JACKET, SHIRT, SKIN, SKIN, DARK, SKIN]
HAIR_RGB = np.array([31, 29, 37], np.float32)
BROW_RGB = np.array([40, 30, 30], np.float32)        # 눈썹: 레퍼런스는 청록·남색이 아닌 검은 갈색
EYE_RGB = np.array([24, 18, 19], np.float32)
IRIS_RGB = np.array([58, 38, 32], np.float32)         # 홍채: 레퍼런스는 갈색 눈 (복셀은 청록 + 회색 테)
HILITE_RGB = np.array([248, 244, 242], np.float32)
# 눈썹·눈 자리 (모델 좌표 x 는 좌우 대칭, z 는 높이; 눈 중심 z=0.19, 눈 폭 0.066). 반경은 (x, z)
BROW_ZONE = (0.074, 0.259, 0.058, 0.026)
EYE_ZONE = (0.074, 0.19, 0.042, 0.034)
# 얼굴 피부 중앙값이 가야 할 곳. 앱 조명이 구운 색을 약 (0.95,0.89,0.83)배로 어둡게 보여서, 렌더가 레퍼런스(235,190,167)에 가도록 미리 올려 둔다
HEAD_Z = 0.03
MOUTH = (0.004, 0.065, 0.055, 0.022)     # 입 중심 x, z 와 반폭 (모델 좌표, 정면은 y<0). rig json face.mouth 와 같은 자리
MOUTH_GAIN = 2.0
SIGMA_C = 20.0
FACE_TARGET = np.array([243, 205, 188], np.float32)


def _shifts(r):
    return [(dy, dx) for dy in range(-r, r + 1) for dx in range(-r, r + 1)]


def same_filter(vals, key, r, ss, valid=None, ref=None, sc=None):
    """같은 key(차트·클래스) 이웃끼리 (r 반경) 가우시안 가중 평균. valid 가 False 인 텍셀은 이웃으로 안 쓴다.
    ref/sc 가 있으면 색 차이(ref 거리)가 큰 이웃의 가중을 낮춘다 (양방향). 반환: (평균, 가중합)"""
    H, W = key.shape
    C = vals.shape[2]
    kp = np.pad(key, r, constant_values=-1)
    vp = np.pad(vals, ((r, r), (r, r), (0, 0)))
    ok_p = np.pad(valid if valid is not None else np.ones((H, W), bool), r, constant_values=False)
    rp = np.pad(ref, ((r, r), (r, r), (0, 0))) if ref is not None else None
    num = np.zeros((H, W, C), np.float32)
    den = np.zeros((H, W), np.float32)
    for dy, dx in _shifts(r):
        sl = (slice(r + dy, r + dy + H), slice(r + dx, r + dx + W))
        w = ((kp[sl] == key) & ok_p[sl]).astype(np.float32) * np.float32(np.exp(-(dy * dy + dx * dx) / (2 * ss * ss)))
        if rp is not None:
            d2 = ((rp[sl] - ref) ** 2).sum(-1)
            w *= np.exp(-d2 / np.float32(2 * sc * sc))
        num += vp[sl] * w[..., None]
        den += w
    return num / np.maximum(den, 1e-6)[..., None], den


def mode_filter(lab, key, nl, r, bias=0.5):
    """같은 차트 안에서 (2r+1)^2 창 다수결. 자기 자신 라벨에 bias 를 줘서 동률이면 그대로"""
    H, W = key.shape
    kp = np.pad(key, r, constant_values=-1)
    lp = np.pad(lab, r, constant_values=-1)
    cnt = np.zeros((nl, H, W), np.float32)
    for dy, dx in _shifts(r):
        sl = (slice(r + dy, r + dy + H), slice(r + dx, r + dx + W))
        same = kp[sl] == key
        lv = lp[sl]
        for k in range(nl):
            cnt[k] += same & (lv == k)
    for k in range(nl):
        cnt[k] += bias * (lab == k)
    return cnt.argmax(0).astype(lab.dtype), cnt


def luma(c):
    return c[..., 0] * 0.299 + c[..., 1] * 0.587 + c[..., 2] * 0.114


def clean(rgb, cid, pos, mask, neck_z, log, seed=1):
    """rgb [H,W,3] 0..255 float32 (차트 여백까지 채워진 것), cid 차트 번호, zt 텍셀 z, mask 실제 래스터 텍셀"""
    H, W, _ = rgb.shape
    rgb = rgb.astype(np.float32)
    zt = pos[..., 2]
    head = zt > HEAD_Z                      # 머리 (머리카락·얼굴). 어깨·깃은 이보다 아래다
    torso = zt < neck_z - 0.03              # 목 아래 (머리카락이 없다)

    front = pos[..., 1] < -0.1

    def zone(zn):                                           # 타원 안 1, 가장자리 0 으로 부드럽게 (좌우 대칭)
        r_ = np.sqrt(((np.abs(pos[..., 0]) - zn[0]) / zn[2]) ** 2 + ((pos[..., 2] - zn[1]) / zn[3]) ** 2)
        return np.clip(1.6 - r_ * 1.0, 0, 1) * front
    wb, we = zone(BROW_ZONE), zone(EYE_ZONE)

    # 1. k-means 7개 → 대표색에 가장 가까운 클래스로 이름 붙인다
    samp = rgb[mask][::7]
    cent, _ = kmeans2(samp, PROTO.copy(), minit='matrix')            # 대표색에서 시작해서 셔츠 같은 작은 군집도 살린다
    cls_of_cent = np.array([PROTO_CLS[int(np.argmin(((PROTO - c) ** 2).sum(1)))] for c in cent])
    flat = rgb.reshape(-1, 3)
    cl = cls_of_cent[cKDTree(cent).query(flat, workers=-1)[1]].reshape(H, W).astype(np.int8)
    log('texclean: centroids ' + ' '.join(f'({c[0]:.0f},{c[1]:.0f},{c[2]:.0f})->{n}' for c, n in zip(cent, cls_of_cent)))

    # 목 아래에는 머리카락이 없다: 어두운 건 전부 재킷. 보라·자주(B>R+15 이고 어두운 것, R>B-10)도 재킷으로
    lm = luma(rgb) / 255
    # 머리에는 재킷·셔츠가 없다: 붉은 자주(R>B)는 귀·구레나룻의 붉은 피부 → 피부, 푸른 어두운 색은 머리카락(푸른 기가 도는 흑색), 흰 것은 피부
    hj = head & (cl == JACKET)
    cl[hj] = np.where(rgb[..., 0][hj] > rgb[..., 2][hj], SKIN, DARK)
    cl[head & (cl == SHIRT)] = SKIN
    cl[torso & (cl == DARK)] = JACKET
    cl[torso & (cl != SKIN) & (cl != SHIRT) & (lm < 0.3)] = JACKET
    purple = torso & (cl != SKIN) & (cl != SHIRT) & (rgb[..., 2] > rgb[..., 0] + 15) & (lm < 0.25)
    cl[purple] = JACKET

    # 눈 자리: 피부색 밝은 곳만 피부, 그 외 밝은 무채색은 하이라이트, 나머지(홍채·테·속눈썹)는 눈
    ez = we > 0.5
    skin_hue0 = (rgb[..., 0] - rgb[..., 1] > 12) & (rgb[..., 1] - rgb[..., 2] > -8)
    L8 = luma(rgb)
    cl[ez & ~(skin_hue0 & (L8 > 150))] = DARK
    cl[ez & ~skin_hue0 & (L8 > 165)] = HILITE

    # 2. 5x5 다수결 (차트별). 경계 털·점을 지운다
    cl, _ = mode_filter(cl, cid, 5, 2)
    cl, _ = mode_filter(cl, cid, 5, 3)                    # 7x7 한 번 더: 눈·머리선 가장자리의 톱니를 편다
    # 3. 셔츠 경계 2 텍셀 침식: 재킷·머리·피부와 닿은 셔츠 텍셀은 이웃 다수 클래스로 (하얀 털 테두리)
    nonshirt = (cl != SHIRT)
    near = np.zeros((H, W), bool)
    kp = np.pad(cid, 2, constant_values=-1)
    npd = np.pad(nonshirt, 2, constant_values=False)
    for dy, dx in _shifts(2):
        sl = (slice(2 + dy, 2 + dy + H), slice(2 + dx, 2 + dx + W))
        near |= (kp[sl] == cid) & npd[sl]
    er = (cl == SHIRT) & near
    if er.any():
        _, cnt = mode_filter(cl, cid, 5, 2, bias=0)
        cnt[SHIRT] = -1
        cl[er] = cnt.argmax(0)[er].astype(np.int8)
    log('texclean: classes ' + ' '.join(f'{n}={np.mean(cl[mask] == k) * 100:.0f}%' for k, n in enumerate(['dark', 'jacket', 'shirt', 'skin', 'hilite'])))

    out = np.zeros_like(rgb)
    key = cid.astype(np.int64) * 8 + cl
    # 4. 밝기비: 클래스 안에서 부드럽게 평활한 밝기 / 클래스 대표 밝기 (피부는 따로)
    lsm, _ = same_filter(luma(rgb)[..., None], key, 3, 2.0)
    lsm = lsm[..., 0]

    # 재킷: 대표색 (잰 값) x 밝기비. 보라·붉은 텍셀(R > B-10)은 대표색으로
    jm = np.median(rgb[mask & (cl == JACKET) & (rgb[..., 0] < rgb[..., 2] - 10)], 0)
    jl = luma(jm)
    ratio = np.clip(lsm / jl, 0.85, 1.15)
    out[cl == JACKET] = (jm * ratio[..., None])[cl == JACKET]
    log(f'texclean: jacket median ({jm[0]:.0f},{jm[1]:.0f},{jm[2]:.0f})')
    # 셔츠
    sm_ = np.median(rgb[mask & (cl == SHIRT)], 0)
    ratio = np.clip(lsm / luma(sm_), 0.85, 1.15)
    out[cl == SHIRT] = (sm_ * ratio[..., None])[cl == SHIRT]
    # 머리카락·눈썹·눈: 청록 눈썹도 머리카락색으로. 눈은 더 어둡게 남도록 밝기비 범위를 넓힌다
    dm = np.median(rgb[mask & (cl == DARK)], 0)
    ratio = np.clip(lsm / max(luma(dm), 1.0), 0.45, 1.3)
    dcol = HAIR_RGB * (1 - wb[..., None]) + BROW_RGB * wb[..., None]
    dcol = dcol * (1 - we[..., None]) + EYE_RGB * we[..., None]
    # 눈 자리의 중간 밝기(홍채)는 갈색으로, 아주 어두운 테·속눈썹은 검은 갈색 그대로
    wi = (np.clip((L8 - 30) / 15, 0, 1) * np.clip((110 - L8) / 20, 0, 1) * we)[..., None]
    dcol = dcol * (1 - wi) + IRIS_RGB * wi
    ratio_e = np.where(we > 0.5, 1.0, ratio)
    out[cl == DARK] = (dcol * ratio_e[..., None])[cl == DARK]
    out[cl == HILITE] = HILITE_RGB
    # 피부: 튀는 점은 이웃 평균으로 메운 뒤 9x9 양방향 (sigma_color 12), 색 이동은 얼굴 중앙값을 목표로
    sk = cl == SKIN
    smed = np.median(rgb[mask & sk], 0)
    # 입꼬리 선은 아주 옅은 분홍 줄이라 필터가 지운다. 입 자리(정면, 모델 좌표)는 원래 색을 살리고 대비를 키운다
    mw = np.clip(1.6 - np.sqrt(((pos[..., 0] - MOUTH[0]) / MOUTH[2]) ** 2 + ((pos[..., 2] - MOUTH[1]) / MOUTH[3]) ** 2), 0, 1) * (pos[..., 1] < -0.12)
    # 피부 색조(R>G>B 쪽, 밝기 충분)면 음영(살구→연어)이라도 그대로 둔다. 어둡거나 청록·보라인 점만 이웃 평균으로 메운다
    skin_hue = (rgb[..., 0] - rgb[..., 1] > 12) & (rgb[..., 1] - rgb[..., 2] > -8) & (luma(rgb) > 0.40 * 255)
    good = sk & (skin_hue | (mw > 0))
    pre, den = same_filter(rgb * good[..., None], key, 4, 3.0, valid=good)
    work = np.where(good[..., None], rgb, np.where((den > 0.2)[..., None], pre, smed))
    work, _ = same_filter(work, key, 4, 3.0, valid=sk, ref=work, sc=SIGMA_C)     # 양방향 (계단이 생기지 않게 sigma_color 를 넉넉히)
    work, _ = same_filter(work, key, 3, 2.0, valid=sk)                            # 그 위에 약한 가우시안
    mws = same_filter(mw[..., None].astype(np.float32), key, 2, 1.2, valid=sk)[0][..., 0]
    soft = same_filter(rgb, key, 3, 2.0, valid=sk)[0]
    work = work + mws[..., None] * (MOUTH_GAIN * (rgb - soft) + soft - work)          # 입 자리: 부드러운 바탕 + 원래 선을 키워서
    hs = mask & sk & head
    face_sel = hs & (luma(work) > np.median(luma(work)[hs]))        # 밝은 쪽 절반 (조명이 닿는 얼굴)
    fm = np.median(work[face_sel], 0)
    shift = FACE_TARGET - fm
    log(f'texclean: face skin median ({fm[0]:.0f},{fm[1]:.0f},{fm[2]:.0f}) -> shift ({shift[0]:+.0f},{shift[1]:+.0f},{shift[2]:+.0f})')
    out[sk] = np.clip(work + shift, 0, 255)[sk]
    # 5. 경계 안티에일리어싱: 같은 차트에서 3x3 가우시안 (sigma 0.8) 만 약하게
    out, _ = same_filter(out, cid.astype(np.int64), 1, 0.8)
    return np.clip(out, 0, 255)
