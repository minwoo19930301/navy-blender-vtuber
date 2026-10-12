/**
 * 리액션 팔 제스처 라이브러리와 점프 보조 함수.
 *
 * 팔은 ArmPose 방향(상완·전완·손·손바닥)과 손가락 말림만으로 표현한다 (모델이 공 몸에 맞게 풀어 준다, docs/MODEL-SPEC.md 4장).
 * 숫자는 하네스 프리셋(src/harness/presets.ts)에서 이미 공 몸에 맞춰 검증된 값을 복사했다. 프리셋 파일을 런타임 번들에 끌어오지 않으려고 복사한다.
 * 제스처는 캐릭터 왼팔(side +1) 기준으로 적고, 오른팔은 x 를 뒤집는다.
 */
import type { Dir3 } from '../contract'
import { type ArmTarget, type Target } from './types'
import { slerpInto } from './util'

type V3 = readonly [number, number, number]
type F5 = readonly [number, number, number, number, number]

export interface Gesture {
  upper: V3
  lower: V3
  hand: V3
  palm: V3
  fingers: F5
  spread: number
  /** 팔 길이 배율 (생략하면 1) */
  stretch?: number
}

const OPEN: F5 = [0, 0, 0, 0, 0]

/** 양팔 순회용 (eval 이 프레임마다 배열 리터럴을 만들지 않게) */
export const SIDES = [0, 1] as const

export const G = {
  /** 만세: 양팔을 위로 (armsUp 프리셋) */
  up: { upper: [0.35, 0.94, 0], lower: [0.25, 0.97, 0], hand: [0.2, 0.98, 0], palm: [0, 0, 1], fingers: OPEN, spread: 0.7 },
  /** 더 크게 벌린 만세 (축하) */
  upWide: { upper: [0.58, 0.8, 0.02], lower: [0.42, 0.9, 0.02], hand: [0.3, 0.95, 0.02], palm: [0, 0, 1], fingers: OPEN, spread: 0.85 },
  /** 공 앞에서 두 손이 모이는 안음 (heart 프리셋의 팔: 손바닥 카메라향, 손끝 아래 가운데) */
  hug: { upper: [0.15, -0.8, 0.58], lower: [-0.4, 0.5, 0.77], hand: [-0.5, -0.8, 0.3], palm: [0, 0.3, 1], fingers: [0.25, 0.12, 0.12, 0.12, 0.12], spread: 0 },
  /** 두 손을 모아 쥔 감동 (손가락을 살짝 말아 모은다. 평균 말림 0.5 미만이라 주먹 해석이 켜지지 않는다) */
  clasp: { upper: [0.15, -0.8, 0.58], lower: [-0.4, 0.5, 0.77], hand: [-0.5, -0.8, 0.3], palm: [0, 0.3, 1], fingers: [0.42, 0.34, 0.34, 0.34, 0.34], spread: 0 },
  /** 손 흔들기: 팔꿈치를 옆으로 들고 전완이 위로 (wave 프리셋보다 팔꿈치를 높였다) */
  wave: { upper: [0.86, 0.12, 0.2], lower: [0.5, 0.85, 0.1], hand: [0.4, 0.9, 0.05], palm: [0, 0, 1], fingers: OPEN, spread: 0.8 },
  /** 주먹 (fist 프리셋: 공 옆으로 들어 올린 주먹) */
  fist: { upper: [0.5, -0.8, 0.3], lower: [-0.1, 0.15, 0.98], hand: [0, 0.55, 0.83], palm: [-0.6, -0.5, 0.6], fingers: [1, 1, 1, 1, 1], spread: 0.1 },
  /** 깜짝 점프: 양팔이 옆 위로 */
  jump: { upper: [0.62, 0.72, 0.1], lower: [0.66, 0.7, 0.1], hand: [0.6, 0.78, 0.05], palm: [0, 0, 1], fingers: OPEN, spread: 0.9 },
  /** 입 옆으로 손 (뽀뽀 던지기 전): cheeks 프리셋의 한쪽 팔 */
  kissHand: { upper: [0.6, 0.3, 0.5], lower: [-0.3, 0.85, 0.4], hand: [-0.3, 0.93, 0.2], palm: [-0.9, 0, 0.35], fingers: OPEN, spread: 0.2 },
  /** 뽀뽀를 날리는 손: 앞 옆으로 쭉 */
  kissThrow: { upper: [0.78, 0.3, 0.3], lower: [0.5, 0.82, 0.25], hand: [0.35, 0.9, 0.2], palm: [0, 0, 1], fingers: OPEN, spread: 0.8 },
  /**
   * 뿔피리를 쥔 손 (입 오른쪽 아래, 가는 목을 주먹으로 쥠): 손바닥이 카메라 쪽(안쪽 앞)을 보고 손가락이 아래로 목을 앞에서 감싼다 (손가락 마디가 보인다).
   * 손바닥 앵커 (0.151, -0.025, 0.569), 목(소품 items/horn.ts)이 손 가로축과 나란하고 말린 손가락 한가운데(손바닥 앵커에서 손가락 쪽 0.04, 앞 0.02)를 지난다. 팔꿈치가 앞으로 나오고 전완이 안쪽 아래로 내려와 입 옆에 닿는다. 팔을 1.3배 늘린다
   */
  horn: { upper: [-0.089, 0.151, 0.985], lower: [-0.849, -0.426, 0.312], hand: [-0.243, -0.97, 0], palm: [-0.554, 0.139, 0.821], fingers: [0.75, 1, 1, 1, 1], spread: 0, stretch: 1.3 },
  /**
   * 하트를 안은 손 (왼팔 기준): 손바닥이 하트 아래쪽 옆면(0.166, -0.254, 0.624)에 안쪽 위를 향해 닿고 손가락은 아래·안쪽·앞으로 하트 밑을 감싼다 (소품 items/heart.ts).
   * 상완이 앞으로 곧게 나가고 전완이 안쪽 아래로 내려온다 (안음 해석 회피: 전완이 앞으로 거의 안 나간다). 팔을 1.6배 늘려야 공 앞 아래까지 닿는다
   */
  holdHeart: { upper: [0.027, -0.11, 0.994], lower: [-0.721, -0.666, 0.19], hand: [-0.457, -0.762, 0.457], palm: [-0.722, 0.619, 0.309], fingers: [0.5, 0.65, 0.65, 0.65, 0.65], spread: 0, stretch: 1.6 },
  /**
   * 알람시계를 든 손 (왼팔 기준, 오른팔이 쓰면 화면 왼쪽): 시계의 안쪽(공 쪽) 아래 테두리를 옆에서 쥔다 — 손바닥이 시계 가운데(바깥 위)를 보고 손가락이 카메라 쪽을 가리켜 말린 손가락이 테두리 앞을 감싼다.
   * 손바닥 앵커 (0.446, 0.186, 0.42). 팔꿈치가 바깥 앞으로 나오고 전완이 안쪽으로 돌아와 팔이 굽는 게 보인다 (이전엔 시계가 공에서 0.74 떨어져 오버레이 가장자리에서 잘렸다). 시계 소품 items/clock.ts
   */
  holdClock: { upper: [0.698, 0.187, 0.691], lower: [-0.919, 0.103, 0.38], hand: [0, 0, 1], palm: [0.707, 0.707, 0], fingers: [0.6, 0.9, 0.9, 0.9, 0.9], spread: 0, stretch: 1 },
  /**
   * 손수건을 쥔 손 (왼팔 기준, 쉬는 자리): 손바닥이 얼굴을 보고 손가락이 눈 쪽(안쪽 위)을 가리킨다. 손바닥 앵커 (0.30, 0.08, 0.50)이고 천(items/cloth.ts)은 손바닥과 볼 사이에 끼어 눈 아래 바깥쪽 볼에 닿는다.
   * 팔꿈치가 낮게 처지고 전완이 가파르게 서서 팔이 굽는 게 보인다 (상완이 앞으로 곧게 가는 자세는 팔꿈치가 혹으로 보인다). 팔을 1.6배 늘린다
   */
  holdCloth: { upper: [0.195, -0.66, 0.725], lower: [-0.589, 0.762, 0.269], hand: [-0.612, 0.764, 0.204], palm: [-0.377, -0.055, -0.925], fingers: [0.5, 0.75, 0.75, 0.75, 0.75], spread: 0, stretch: 1.6 },
  /** 손수건으로 눈가를 톡 닦는 순간 (holdCloth 와 섞는다): 손바닥 앵커 (0.26, 0, 0.50), 천이 눈 아래 바깥 볼에 눌린다. 팔을 1.6배 늘린다 */
  dabCloth: { upper: [0.008, -0.834, 0.552], lower: [-0.502, 0.743, 0.442], hand: [-0.612, 0.764, 0.204], palm: [-0.377, -0.055, -0.925], fingers: [0.5, 0.75, 0.75, 0.75, 0.75], spread: 0, stretch: 1.6 },
  /**
   * 꽃다발을 쥔 손 (왼팔 기준, 오른팔이 쓰면 화면 왼쪽 가슴 앞): 손바닥이 카메라를 보고 손가락이 안쪽(공 쪽)을 가리켜 가로축(손의 X)이 위다. 손바닥 앵커 (0.27, -0.10, 0.62).
   * 주먹이 종이 원뿔의 가는 아래를 쥐고(말린 손가락이 앞을 덮는다) 꽃은 위로 솟는다 (items/bouquet.ts). 상완이 앞으로, 전완이 안쪽 아래로. 팔을 1.3배 늘린다
   */
  holdBouquet: { upper: [0.136, 0.001, 0.991], lower: [-0.729, -0.539, 0.422], hand: [-0.954, 0, 0.301], palm: [0.301, 0, 0.954], fingers: [0.6, 0.9, 0.9, 0.9, 0.9], spread: 0, stretch: 1.3 },
  /**
   * 선물 상자를 안은 손 (왼팔 기준): 손바닥이 상자 옆면(0.205, -0.36, 0.66)에 안쪽으로 닿고, 손가락이 앞 모서리(z 0.74)를 넘어 앞면 쪽으로 감싼다 (items/party.ts).
   * 팔꿈치가 앞으로 나온 안는 팔(상완이 앞으로 곧게, 전완이 안쪽 아래로 — 안음 해석 회피). 팔을 1.58배 늘린다
   */
  holdGift: { upper: [-0.049, -0.158, 0.986], lower: [-0.494, -0.835, 0.242], hand: [-0.1, -0.201, 0.974], palm: [-0.995, 0.04, -0.094], fingers: [0.45, 0.6, 0.6, 0.6, 0.6], spread: 0, stretch: 1.58 },
} as const satisfies Record<string, Gesture>

const norm = (out: Dir3, x: number, y: number, z: number): void => {
  const l = Math.hypot(x, y, z) || 1
  out.x = x / l
  out.y = y / l
  out.z = z / l
}

/**
 * 한쪽 팔(i: 0 = 캐릭터 왼팔, 1 = 오른팔)의 목표를 제스처로 채우고 덮어쓰기 강도를 w 로 둔다.
 * 오른팔은 x 성분을 뒤집는다. 이후 nudge 로 흔들림을 얹는다.
 */
export function armSet(tg: Target, i: 0 | 1, w: number, g: Gesture): void {
  const s = i === 0 ? 1 : -1
  const a: ArmTarget = tg.arms[i]
  tg.armW[i] = w
  norm(a.upper, s * g.upper[0], g.upper[1], g.upper[2])
  norm(a.lower, s * g.lower[0], g.lower[1], g.lower[2])
  norm(a.hand, s * g.hand[0], g.hand[1], g.hand[2])
  norm(a.palm, s * g.palm[0], g.palm[1], g.palm[2])
  for (let k = 0; k < 5; k++) a.fingers[k] = g.fingers[k]
  a.spread = g.spread
  a.stretch = g.stretch ?? 1
}

const mixA: Dir3 = { x: 0, y: 0, z: 1 }
const mixB: Dir3 = { x: 0, y: 0, z: 1 }

/**
 * v1 → v2 를 각도 기준(구면 보간)으로 k 만큼 섞어(좌우 부호 s 적용) out 에 쓴다.
 * 성분 보간 후 정규화는 거의 정반대인 두 방향(만세의 손끝 위 ↔ 뿔피리를 쥔 손끝 아래) 사이에서 중간이 영벡터 근처라 한 프레임에 휙 돌았다
 */
function mixDir(out: Dir3, v1: V3, v2: V3, s: number, k: number): void {
  norm(mixA, s * v1[0], v1[1], v1[2])
  norm(mixB, s * v2[0], v2[1], v2[2])
  slerpInto(out, mixA, mixB, k, s)
}

/** 두 제스처 사이를 k(0..1)로 섞어 채운다 (방향은 구면 보간) */
export function armSetMix(tg: Target, i: 0 | 1, w: number, g1: Gesture, g2: Gesture, k: number): void {
  const s = i === 0 ? 1 : -1
  const a: ArmTarget = tg.arms[i]
  tg.armW[i] = w
  mixDir(a.upper, g1.upper, g2.upper, s, k)
  mixDir(a.lower, g1.lower, g2.lower, s, k)
  mixDir(a.hand, g1.hand, g2.hand, s, k)
  mixDir(a.palm, g1.palm, g2.palm, s, k)
  for (let n = 0; n < 5; n++) a.fingers[n] = g1.fingers[n] + (g2.fingers[n] - g1.fingers[n]) * k
  a.spread = g1.spread + (g2.spread - g1.spread) * k
  const s1 = g1.stretch ?? 1
  a.stretch = s1 + ((g2.stretch ?? 1) - s1) * k
}

/** 방향 d 에 (dx, dy, dz) 를 더해 다시 정규화. dx 는 캐릭터 왼팔 기준이고 오른팔(i = 1)이면 부호를 뒤집는다 */
export function nudge(tg: Target, i: 0 | 1, which: 'upper' | 'lower' | 'hand', dx: number, dy = 0, dz = 0): void {
  const d = tg.arms[i][which]
  norm(d, d.x + (i === 0 ? dx : -dx), d.y + dy, d.z + dz)
}

/**
 * 점프 한 번을 목표에 더한다. 웅크림(-) → 도약(길쭉 +) → 공중 → 착지 스쿼시(-) → 스프링 정착.
 * t0 = 도약 시각, dur = 체공 시간, h = 높이(공 지름 단위), a = 스쿼시 세기.
 * 높이는 포물선이라 위에서 느리고 아래에서 빠르다.
 */
export function hop(tg: Target, tl: number, t0: number, dur: number, h: number, a: number): void {
  const ANT = 0.11
  const u = (tl - t0) / dur
  if (tl >= t0 - ANT && tl < t0) {
    // 웅크리기
    const p = (tl - (t0 - ANT)) / ANT
    tg.squash -= a * 0.75 * (p * p * (3 - 2 * p))
  } else if (u >= 0 && u < 1) {
    tg.bounce += 4 * h * u * (1 - u)
    // 도약 직후 길쭉하게 늘어났다가 공중에서 풀리고, 내려올 때 다시 약간 늘어난다
    const takeoff = Math.min(1, (u * dur) / 0.07)
    const tk = takeoff * takeoff * (3 - 2 * takeoff)
    const air = a * 0.55 * (1 - Math.min(1, u * 2.2)) + a * 0.3 * Math.max(0, (u - 0.65) / 0.35)
    // 착지 직전 0.045초 동안 납작한 쪽으로 미리 눌러 한 프레임에 확 꺾이지 않게 한다 (착지 스프링이 -a 에서 시작한다)
    const pre = 1 - Math.min(1, ((1 - u) * dur) / 0.045)
    tg.squash += -a * 0.75 * (1 - tk) + (air * (1 - pre) - a * pre) * tk
  } else if (u >= 1) {
    // 착지: 가장 납작한 상태에서 감쇠 스프링으로 정착
    const tau = tl - (t0 + dur)
    if (tau < 0.7) tg.squash += -a * Math.exp(-tau / 0.085) * Math.cos((Math.PI * 2 * tau) / 0.3)
  }
}
