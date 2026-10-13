/**
 * 숫자키 리액션 9종의 타임라인 (공식 Smileee 애니메이션 참고: 웃으며 만세 + 꽃, 눈물 글썽, 뽀뽀 ε, 깜짝, 졸음 …).
 *
 * 각 리액션은 시간(초) → 목표(Target) 순수 함수 + FX 이벤트 목록이다. 난수는 FX 이벤트의 rng(시드 고정)로만 쓴다.
 * 길이 2.0~3.0초. 들어올 때 0.15초, 나갈 때 0.35초는 엔진이 엔벨로프로 처리하므로 여기서는 시간 윈도(ss)를 그 안쪽에 둔다.
 *
 * 좌표 감각 (공 지름 1, 공 중심 높이 0.5): FX 오프셋은 공 중심 기준이다 (+x 화면 오른쪽, +y 위).
 */
import { FxKind, CONFETTI_COLORS, type Fx, type FxKindId } from './fx'
import { G, SIDES, armSet, armSetMix, hop, nudge } from './poses'
import { GIFT_POP, HORN_BLOWS, HORN_BLOW_LEN, PROP_CUES, PropId } from './propdefs'
import type { FxEvent, Spec } from './types'
import { TAU, bell, ss } from './util'

type Rng = () => number
const R = (rng: Rng, a: number, b: number): number => a + (b - a) * rng()

/* ---------------- FX 보조 ---------------- */

const FLOWERS: readonly FxKindId[] = [FxKind.flowerA, FxKind.flowerB, FxKind.flowerC]

/** 공 위쪽 부채꼴에서 꽃·반짝이를 터뜨린다 (공식 만세 컷: 얼굴 위에 작은 꽃이 흩어진다) */
function flowerBurst(fx: Fx, rng: Rng, flowers: number, sparkles: number, lifeScale = 1): void {
  for (let i = 0; i < flowers; i++) {
    const th = R(rng, 0.1 * Math.PI, 0.9 * Math.PI)
    const r0 = R(rng, 0.5, 0.7)
    const p = fx.emit(FLOWERS[Math.floor(rng() * 3) % 3], Math.cos(th) * r0, Math.sin(th) * r0)
    if (!p) return
    const v = R(rng, 0.14, 0.34)
    p.vx = Math.cos(th) * v
    p.vy = Math.sin(th) * v + 0.04
    p.kx = 2; p.ky = 2
    p.g = R(rng, 0.05, 0.14)
    p.life = R(rng, 1.4, 1.9) * lifeScale
    p.size = R(rng, 0.075, 0.13)
    p.spin = R(rng, -2.2, 2.2)
    p.rot = R(rng, 0, TAU)
    p.delay = R(rng, 0, 0.18)
    p.shrink = 0.25
    p.follow = 0.35
  }
  for (let i = 0; i < sparkles; i++) {
    const th = R(rng, 0.12 * Math.PI, 0.88 * Math.PI)
    const r0 = R(rng, 0.58, 0.82)
    const p = fx.emit(FxKind.sparkle, Math.cos(th) * r0, Math.sin(th) * r0)
    if (!p) return
    p.vy = R(rng, 0.02, 0.1)
    p.life = R(rng, 1.0, 1.5) * lifeScale
    p.size = R(rng, 0.13, 0.22)
    p.twinkle = 0.55
    p.swayPh = R(rng, 0, TAU)
    p.spin = R(rng, -0.6, 0.6)
    p.delay = R(rng, 0, 0.3)
    p.follow = 0.35
  }
}

function sparkleAt(fx: Fx, rng: Rng, ox: number, oy: number, size: number, life = 1.3, follow = 0.4): void {
  const p = fx.emit(FxKind.sparkle, ox, oy)
  if (!p) return
  p.life = life
  p.size = size
  p.twinkle = 0.5
  p.swayPh = R(rng, 0, TAU)
  p.spin = R(rng, -0.5, 0.5)
  p.vy = 0.03
  p.follow = follow
}

/** 하트를 공 위에서 띄운다 */
function risingHearts(fx: Fx, rng: Rng, n: number, minSize: number, maxSize: number): void {
  for (let i = 0; i < n; i++) {
    const p = fx.emit(FxKind.heart, R(rng, -0.5, 0.5), R(rng, 0.32, 0.58))
    if (!p) return
    p.vy = R(rng, 0.34, 0.5)
    p.vx = R(rng, -0.05, 0.07)
    p.ky = 0.6; p.kx = 1
    p.g = 0
    p.life = R(rng, 1.6, 2.1)
    p.size = R(rng, minSize, maxSize)
    p.swayAmp = R(rng, 0.02, 0.05)
    p.swayF = R(rng, 0.8, 1.4)
    p.swayPh = R(rng, 0, TAU)
    p.rot = R(rng, -0.35, 0.35)
    p.spin = R(rng, -0.4, 0.4)
    p.delay = R(rng, 0, 0.16)
    p.shrink = 0.2
    p.follow = 0.3
  }
}

/**
 * 색종이 한 번 터짐. (ox, oy) = 터지는 자리(공 중심 기준), 부채꼴은 center(rad, π/2 = 위)를 가운데로 ±half.
 * 머리 위 가운데에는 모자가, 얼굴 아래에는 활짝 웃는 입이 있어서, 손(만세)·선물 상자 양옆에서 바깥쪽 위로 쏜다 (가리지 않는다).
 * 조각은 몇 개만, 도톰하고 둥근 알약 모양으로 (가는 막대 수십 개는 잡음으로 보인다)
 */
function confettiBurst(fx: Fx, rng: Rng, n: number, power: number, ox: number, oy: number, center: number, half: number): void {
  for (let i = 0; i < n; i++) {
    const p = fx.emit(FxKind.confetti, ox + R(rng, -0.04, 0.04), oy + R(rng, -0.05, 0.05))
    if (!p) return
    const th = center + R(rng, -half, half)
    const sp = R(rng, 0.55, 1.2) * power
    p.vx = Math.cos(th) * sp
    p.vy = Math.sin(th) * sp
    p.kx = 1.15; p.ky = 1.2
    p.g = R(rng, 0.45, 0.7)
    p.life = R(rng, 1.8, 2.4)
    p.size = R(rng, 0.045, 0.07)
    p.aspect = R(rng, 0.55, 0.9)
    p.rot = R(rng, 0, TAU)
    p.spin = R(rng, -4, 4)
    p.flutter = 0.28
    p.flutterF = R(rng, 8, 13)
    p.flutterPh = R(rng, 0, TAU)
    p.swayAmp = R(rng, 0.008, 0.025)
    p.swayF = R(rng, 1.5, 2.6)
    p.swayPh = R(rng, 0, TAU)
    p.color = CONFETTI_COLORS[Math.floor(rng() * CONFETTI_COLORS.length) % CONFETTI_COLORS.length]
    p.pop = 0.05
    p.fadeAt = 0.8
    p.delay = R(rng, 0, 0.1)
  }
}

function dustPuffs(fx: Fx): void {
  for (const sx of [-1, 1]) {
    const p = fx.emit(FxKind.puff, sx * 0.4, -0.43)
    if (!p) return
    p.vx = sx * 0.4
    p.vy = 0.05
    p.kx = 3.2; p.ky = 3
    p.size = 0.15
    p.grow = 0.9
    p.life = 0.55
    p.alpha = 0.85
    p.pop = 0.06
    p.fadeAt = 0.3
  }
}

const ev = (t: number, run: FxEvent['run']): FxEvent => ({ t, run })

/* ---------------- 1 웃음 (+ 뿔피리) ---------------- */

const cue = (id: number) => PROP_CUES.find((c) => c.prop === id)!
const HORN_CUE = cue(PropId.horn)
const CLOCK_CUE = cue(PropId.clock)
const CLOTH_CUE = cue(PropId.cloth)
const BOUQUET_CUE = cue(PropId.bouquet)
const GIFT_CUE = cue(PropId.gift)

/** 뿔피리를 부는 중이면 0..1 (한 번 불 때 올랐다 내려온다). 입 모양·볼이 이걸 따른다 */
function blowing(tl: number): number {
  let b = 0
  for (let k = 0; k < HORN_BLOWS.length; k++) {
    const tau = tl - HORN_BLOWS[k]
    if (tau > 0 && tau < HORN_BLOW_LEN + 0.1) b = Math.max(b, ss(0, 0.07, tau) * (1 - ss(HORN_BLOW_LEN - 0.12, HORN_BLOW_LEN + 0.1, tau)))
  }
  return b
}

const laugh: Spec = {
  id: 1,
  name: '웃음',
  dur: 2.6,
  // 첫 번째 불기 한가운데 (뿔피리 HORN_BLOWS[0] + 0.12): 종이 혀가 쫙 펴져 있다
  peak: 0.9,
  eval(tl, tg) {
    // 처음엔 깔깔 웃다가 뿔피리를 물고(0.42~) ε 입으로 세 번 불고, 마지막에 다시 웃는다
    const horn = tl > HORN_CUE.in + 0.05 && tl < HORN_CUE.out - 0.1
    const b = blowing(tl)
    tg.happy = true
    if (horn) {
      tg.kiss = true
      tg.mouthOpen = 0.12 + 0.3 * b
      tg.mouthSmile = 0.5
      tg.blush = 0.55 + 0.4 * b
    } else {
      tg.mouthOpen = 0.74 + 0.13 * Math.sin(TAU * 5.2 * tl)
      tg.mouthSmile = 0.9
      tg.blush = 0.5
    }
    tg.headRoll = 0.07 * Math.sin(TAU * 2.1 * tl)
    tg.headPitch = 0.05 * Math.sin(TAU * 4.2 * tl)
    hop(tg, tl, 0.2, 0.4, 0.07, 0.07)
    hop(tg, tl, 0.85, 0.4, 0.07, 0.07)
    const wig = ss(0.1, 0.4, tl)
    for (let si = 0; si < 2; si++) {
      const i = SIDES[si]
      const s = Math.sin(TAU * 3.4 * tl + i * Math.PI)
      if (i === 0) {
        // 캐릭터 왼팔: 만세로 흔들다가 입 앞으로 가서 뿔피리를 쥐고, 끝나면 다시 만세
        const k = ss(HORN_CUE.in - 0.2, HORN_CUE.in + 0.15, tl) * (1 - ss(HORN_CUE.out - 0.3, HORN_CUE.out - 0.02, tl))
        armSetMix(tg, 0, 1, G.up, G.horn, k)
        const x = 1 - k
        nudge(tg, 0, 'upper', 0.2 * s * wig * x)
        nudge(tg, 0, 'lower', 0.3 * Math.sin(TAU * 3.4 * tl + 0.9) * wig * x, 0.04 * s * wig * x)
        nudge(tg, 0, 'hand', 0.35 * Math.sin(TAU * 3.4 * tl + 1.6) * wig * x)
        // 불 때 손도 같이 끄덕
        nudge(tg, 0, 'lower', 0, 0.025 * b * k)
        // 머리를 돌려도 주먹이 입술을 따라간다 (follow.ts)
        tg.mouthFollow = k
      } else {
        armSet(tg, i, 1, G.up)
        nudge(tg, i, 'upper', 0.2 * s * wig)
        nudge(tg, i, 'lower', 0.3 * Math.sin(TAU * 3.4 * tl + i * Math.PI + 0.9) * wig, 0.04 * s * wig)
        nudge(tg, i, 'hand', 0.35 * Math.sin(TAU * 3.4 * tl + i * Math.PI + 1.6) * wig)
      }
    }
  },
  events: [
    ev(0.12, (fx, rng) => flowerBurst(fx, rng, 9, 4)),
    ev(1.05, (fx, rng) => flowerBurst(fx, rng, 5, 3)),
  ],
}

/* ---------------- 2 사랑 ---------------- */

const love: Spec = {
  id: 2,
  name: '사랑',
  dur: 2.7,
  peak: 1.0,
  eval(tl, tg) {
    tg.heart = true
    tg.mouthSmile = 0.85
    tg.mouthOpen = 0
    tg.blush = 1
    tg.headRoll = 0.07 * Math.sin(TAU * 0.9 * tl)
    // 두근두근: 공이 1.6Hz 로 살짝 커졌다 줄어든다
    const beat = Math.max(0, Math.sin(TAU * 1.6 * tl))
    tg.push = 0.55 * Math.pow(beat, 5) * ss(0.2, 0.5, tl)
    tg.squash = 0.02 * Math.sin(TAU * 0.9 * tl)
    // 큰 하트를 앞에 안는다 (소품 heart: 0.22초에 팝, 두 손이 아래쪽 옆구리를 감싼다)
    const a = ss(0.06, 0.36, tl)
    armSet(tg, 0, a, G.holdHeart)
    armSet(tg, 1, a, G.holdHeart)
  },
  events: [
    ev(0.2, (fx, rng) => risingHearts(fx, rng, 3, 0.16, 0.26)),
    ev(0.65, (fx, rng) => risingHearts(fx, rng, 2, 0.12, 0.19)),
    ev(1.05, (fx, rng) => risingHearts(fx, rng, 3, 0.14, 0.25)),
    ev(1.55, (fx, rng) => risingHearts(fx, rng, 2, 0.12, 0.2)),
    ev(1.95, (fx, rng) => risingHearts(fx, rng, 1, 0.13, 0.18)),
  ],
}

/* ---------------- 3 인사 ---------------- */

const greet: Spec = {
  id: 3,
  name: '인사',
  dur: 2.5,
  peak: 0.95,
  eval(tl, tg) {
    tg.mouthSmile = 0.85
    tg.mouthOpen = 0
    tg.blush = 0.4
    tg.headRoll = 0.13 * ss(0.1, 0.4, tl)
    tg.headPitch = 0.04
    tg.leanX = 0.04 * ss(0.1, 0.4, tl)
    hop(tg, tl, 0.12, 0.26, 0.045, 0.05)
    const w = ss(0.08, 0.3, tl) * (1 - ss(1.95, 2.15, tl))
    // 팔꿈치를 옆으로 들고 전완을 좌우로 크게 흔든다
    const amp = ss(0.3, 0.55, tl)
    const ph = TAU * 2.7 * (tl - 0.3)
    armSet(tg, 0, w, G.wave)
    nudge(tg, 0, 'lower', 0.4 * Math.sin(ph) * amp, 0.04)
    nudge(tg, 0, 'hand', 0.5 * Math.sin(ph + 0.5) * amp)
    nudge(tg, 0, 'upper', 0.06 * Math.sin(ph - 0.5) * amp, 0.04 * Math.sin(ph) * amp)
  },
  events: [
    ev(0.5, (fx, rng) => sparkleAt(fx, rng, 0.74, 0.62, 0.15, 1.2)),
    ev(0.95, (fx, rng) => sparkleAt(fx, rng, 0.86, 0.38, 0.12, 1.2)),
    ev(1.4, (fx, rng) => sparkleAt(fx, rng, 0.7, 0.7, 0.13, 1.1)),
  ],
}

/* ---------------- 4 놀람 ---------------- */

const surprise: Spec = {
  id: 4,
  name: '놀람',
  dur: 2.3,
  peak: 0.42,
  eval(tl, tg) {
    tg.surprised = true
    tg.mouthOpen = 0.5 - 0.15 * ss(0.3, 0.9, tl)
    tg.mouthSmile = -0.5
    tg.blush = 0.2
    tg.headPitch = 0.12 * bell(0.05, 0.7, tl)
    hop(tg, tl, 0.16, 0.52, 0.32, 0.2)
    hop(tg, tl, 0.98, 0.26, 0.06, 0.07)
    // 깜짝 점프: 양팔이 옆 위로 확 벌어졌다가 착지하며 내려온다
    const w = ss(0.1, 0.24, tl) * (1 - ss(0.78, 1.05, tl))
    armSet(tg, 0, w, G.jump)
    nudge(tg, 0, 'lower', 0.12 * Math.sin(TAU * 4 * tl) * w)
    // 캐릭터 오른팔(화면 왼쪽)은 점프하는 동안 알람시계를 잡아 올리고(소품 clock) 울릴 때까지 든다.
    // 점프 제스처와 섞지 않는다: 두 제스처의 손바닥 법선이 정반대(앞 ↔ 뒤)라 성분 보간의 중간이 영벡터가 된다
    const wc = ss(0.02, 0.34, tl) * (1 - ss(CLOCK_CUE.out - 0.02, CLOCK_CUE.out + 0.28, tl))
    armSet(tg, 1, wc, G.holdClock)
    const ring = ss(0.3, 0.5, tl) * (1 - ss(1.65, 1.85, tl))
    nudge(tg, 1, 'lower', 0.02 * Math.sin(TAU * 14 * tl) * ring, 0.015 * Math.sin(TAU * 11 * tl) * ring)
  },
  events: [
    ev(0.14, (fx) => {
      const p = fx.emit(FxKind.exclaim, 0.38, 0.62)
      if (!p) return
      p.size = 0.3
      p.rot = -0.18
      p.life = 1.35
      p.follow = 1
      p.pop = 0.16
      p.pulseAmp = 0.06
      p.pulseF = 3
      p.fadeAt = 0.78
    }),
    ev(0.5, (fx) => {
      const p = fx.emit(FxKind.sweat, 0.42, 0.36)
      if (!p) return
      p.size = 0.15
      p.aspect = 1.2
      p.vy = 0.05
      p.g = 0.2
      p.life = 1.15
      p.follow = 1
      p.pop = 0.14
      p.fadeAt = 0.65
    }),
    ev(0.68, (fx) => dustPuffs(fx)),
  ],
}

/* ---------------- 5 감동 ---------------- */

const touched: Spec = {
  id: 5,
  name: '감동',
  dur: 2.9,
  peak: 1.2,
  eval(tl, tg) {
    tg.teary = true
    tg.mouthSmile = 0.55
    tg.mouthOpen = 0
    tg.blush = 0.6
    tg.gazeY = 0.55 * ss(0.15, 0.5, tl)
    tg.headPitch = 0.07 * ss(0.15, 0.5, tl)
    tg.headRoll = 0.05 * Math.sin(TAU * 0.8 * tl)
    // 눈물이 두 번 흘러내린다
    tg.tear = tl < 1.45 ? Math.max(0, (tl - 0.45) / 0.9) : tl < 2.55 ? Math.max(0, (tl - 1.55) / 0.9) : 0
    // 울먹임: 공이 살짝 들썩인다
    tg.squash = 0.022 * Math.sin(TAU * 1.5 * tl) * ss(0.35, 0.8, tl)
    // 캐릭터 왼팔(화면 오른쪽)이 손수건을 쥐고 눈가를 톡톡 닦는다 (소품 cloth). 다른 팔은 가만히 쉰다
    const a = ss(CLOTH_CUE.in - 0.2, CLOTH_CUE.in + 0.25, tl) * (1 - ss(CLOTH_CUE.out - 0.2, CLOTH_CUE.out + 0.05, tl))
    // 톡톡: 주먹이 눈 바로 옆(dabCloth)까지 갔다 쉬는 자리(holdCloth)로 돌아온다 (1.1Hz)
    const dab = (0.5 - 0.5 * Math.cos(TAU * 1.1 * (tl - CLOTH_CUE.in - 0.25))) * ss(CLOTH_CUE.in + 0.15, CLOTH_CUE.in + 0.45, tl) * (1 - ss(CLOTH_CUE.out - 0.45, CLOTH_CUE.out - 0.2, tl))
    armSetMix(tg, 0, a, G.holdCloth, G.dabCloth, dab)
  },
  events: [
    ev(0.25, (fx, rng) => sparkleAt(fx, rng, -0.55, 0.64, 0.2, 1.5)),
    ev(0.55, (fx, rng) => sparkleAt(fx, rng, 0.6, 0.72, 0.26, 1.6)),
    ev(0.9, (fx, rng) => sparkleAt(fx, rng, 0.3, 0.84, 0.13, 1.3)),
    ev(1.35, (fx, rng) => sparkleAt(fx, rng, -0.7, 0.3, 0.14, 1.3)),
    ev(1.7, (fx, rng) => sparkleAt(fx, rng, 0.68, 0.34, 0.16, 1.4)),
  ],
}

/* ---------------- 6 뽀뽀 ---------------- */

const kiss: Spec = {
  id: 6,
  name: '뽀뽀',
  dur: 2.5,
  peak: 1.32,
  eval(tl, tg) {
    tg.kiss = true
    tg.happy = true
    tg.mouthSmile = 0.4
    // 입술이 쭈욱 나왔다 들어간다 (ε 크기)
    tg.mouthOpen = 0.35 * bell(0.7, 1.35, tl)
    tg.blush = 0.8
    const lean = ss(0.2, 0.75, tl) * (1 - ss(1.55, 1.95, tl))
    tg.push = 0.9 * lean
    tg.leanZ = 0.14 * lean
    tg.headRoll = 0.1 * lean
    tg.headPitch = -0.05 * lean
    hop(tg, tl, 1.0, 0.26, 0.04, 0.05)
    // 한 손이 입가에서 뽀뽀를 날린다
    const w = ss(0.12, 0.38, tl) * (1 - ss(1.7, 2.0, tl))
    armSetMix(tg, 0, w, G.kissHand, G.kissThrow, ss(0.95, 1.2, tl))
    nudge(tg, 0, 'hand', 0.2 * bell(0.95, 1.5, tl), 0.1 * bell(0.95, 1.5, tl))
    // 다른 팔(화면 왼쪽)은 빨간 장미 꽃다발을 앞에 들고 있다 (소품 bouquet)
    const wb = ss(BOUQUET_CUE.in - 0.27, BOUQUET_CUE.in + 0.08, tl) * (1 - ss(BOUQUET_CUE.out - 0.02, BOUQUET_CUE.out + 0.3, tl))
    armSet(tg, 1, wb, G.holdBouquet)
    nudge(tg, 1, 'lower', 0.012 * Math.sin(TAU * 1.2 * tl), 0.02 * Math.sin(TAU * 2.4 * tl))
  },
  events: [
    ev(1.02, (fx, rng) => {
      // 하트 뽀뽀: 입에서 앞 위쪽으로 한 개 크게 + 작은 두 개
      const big = fx.emit(FxKind.heart, 0.08, 0.0)
      if (big) {
        big.vx = 0.78
        big.vy = 0.9
        big.kx = 1.5; big.ky = 1.3
        big.size = 0.22
        big.life = 1.3
        big.rot = -0.2
        big.spin = 0.4
        big.pop = 0.2
        big.follow = 0.5
        big.shrink = 0.15
      }
      for (let i = 0; i < 2; i++) {
        const p = fx.emit(FxKind.heart, 0.06, 0.02)
        if (!p) return
        p.vx = R(rng, 0.3, 0.55) * (i === 0 ? 1 : -0.7)
        p.vy = R(rng, 0.6, 0.85)
        p.kx = 1.5; p.ky = 1.3
        p.size = R(rng, 0.09, 0.13)
        p.life = 1.2
        p.delay = 0.12 + 0.12 * i
        p.follow = 0.5
        p.swayAmp = 0.02
        p.swayF = 1.2
        p.swayPh = i * 2
        p.rot = R(rng, -0.4, 0.4)
      }
    }),
    ev(1.35, (fx, rng) => sparkleAt(fx, rng, 0.62, 0.55, 0.13, 1.0, 0.5)),
  ],
}

/* ---------------- 7 화남 ---------------- */

const angry: Spec = {
  id: 7,
  name: '화남',
  dur: 2.5,
  peak: 0.9,
  eval(tl, tg) {
    tg.angry = true
    tg.mouthSmile = -0.85
    tg.mouthOpen = 0
    tg.blush = 0.95
    const tr = ss(0.08, 0.25, tl) * (1 - ss(1.85, 2.15, tl))
    // 부들부들: 19Hz 로 옆으로 떨고 머리도 같이 떤다 (60fps 렌더에서 한 주기가 3프레임 이상이라 떨림으로 보인다)
    tg.shiftX = 0.026 * tr * Math.sin(TAU * 19 * tl)
    tg.headRoll = 0.045 * tr * Math.sin(TAU * 13 * tl + 1)
    tg.squash = -0.03 * tr * (0.5 + 0.5 * Math.sin(TAU * 2.8 * tl))
    tg.push = 0.4 * ss(0.1, 0.4, tl) * (1 - ss(1.85, 2.15, tl))
    const w = ss(0.1, 0.3, tl) * (1 - ss(1.85, 2.15, tl))
    for (let si = 0; si < 2; si++) {
      const i = SIDES[si]
      armSet(tg, i, w, G.fist)
      nudge(tg, i, 'lower', 0, 0.05 * Math.sin(TAU * 16 * tl + i * 1.7) * tr)
      nudge(tg, i, 'upper', 0.03 * Math.sin(TAU * 14 * tl + i) * tr)
    }
  },
  events: [
    ev(0.2, (fx) => {
      const p = fx.emit(FxKind.anger, 0.37, 0.41)
      if (!p) return
      p.size = 0.27
      p.rot = 0.12
      p.life = 1.95
      p.pop = 0.14
      p.follow = 1
      p.pulseAmp = 0.17
      p.pulseF = 2.8
      p.fadeAt = 0.82
    }),
    ev(0.45, (fx, rng) => steam(fx, rng)),
    ev(0.95, (fx, rng) => steam(fx, rng)),
    ev(1.45, (fx, rng) => steam(fx, rng)),
  ],
}

/** 머리 위로 김이 푹 올라온다 (화남) */
function steam(fx: Fx, rng: Rng): void {
  for (const sx of [-1, 1]) {
    const p = fx.emit(FxKind.puff, sx * R(rng, 0.16, 0.26), 0.52)
    if (!p) return
    p.vx = sx * 0.07
    p.vy = 0.3
    p.kx = 1.5; p.ky = 1.2
    p.size = 0.09
    p.grow = 1.3
    p.life = 0.9
    p.alpha = 0.8
    p.pop = 0.1
    p.fadeAt = 0.35
    p.follow = 0.4
    p.delay = sx > 0 ? 0.08 : 0
  }
}

/* ---------------- 8 졸림 ---------------- */

const sleepy: Spec = {
  id: 8,
  name: '졸림',
  dur: 3.0,
  peak: 1.2,
  eval(tl, tg) {
    tg.sleepy = true
    tg.mouthSmile = 0.4
    tg.mouthOpen = 0
    tg.blush = 0.3
    tg.blink = 1
    tg.gazeX = 0
    tg.gazeY = 0
    // 꾸벅꾸벅: 고개가 앞으로 떨어졌다 올라오고 몸이 천천히 좌우로 흔들린다
    const nod = 0.5 - 0.5 * Math.cos(TAU * 0.45 * tl)
    tg.headPitch = -0.08 - 0.14 * nod
    tg.headRoll = 0.1 * Math.sin(TAU * 0.35 * tl)
    tg.leanX = 0.1 * Math.sin(TAU * 0.35 * tl)
    tg.squash = 0.035 * Math.sin(TAU * 0.5 * tl)
  },
  events: [
    ev(0.5, (fx) => zzz(fx, 0.1, 0)),
    ev(1.15, (fx) => zzz(fx, 0.145, 0)),
    ev(1.8, (fx) => zzz(fx, 0.195, 0)),
  ],
}

function zzz(fx: Fx, size: number, delay: number): void {
  const p = fx.emit(FxKind.z, 0.34, 0.3)
  if (!p) return
  p.size = size
  p.vx = 0.1
  p.vy = 0.2
  p.kx = 1; p.ky = 0.8
  p.life = 1.7
  p.rot = 0.18
  p.swayAmp = 0.03
  p.swayF = 0.7
  p.delay = delay
  p.follow = 0.5
  p.pop = 0.25
  p.fadeAt = 0.6
}

/* ---------------- 9 축하 ---------------- */

/** 부채꼴의 "위" 방향 각 (rad) */
const UP = Math.PI / 2

const celebrate: Spec = {
  id: 9,
  name: '축하',
  dur: 3.0,
  // 모자를 쓰고 선물 뚜껑이 팡 열린 직후 (뚜껑 GIFT_POP 1.2 + 0.25)
  peak: 1.45,
  eval(tl, tg) {
    tg.happy = true
    tg.mouthOpen = 0.78 + 0.1 * Math.sin(TAU * 4.5 * tl)
    tg.mouthSmile = 1
    tg.blush = 0.5
    // 점프 + 360° 자전 (체공 구간에서 한 바퀴)
    hop(tg, tl, 0.2, 0.7, 0.36, 0.18)
    hop(tg, tl, 1.3, 0.3, 0.07, 0.07)
    tg.spin = TAU * ss(0.22, 0.86, tl)
    if (tl > 0.9) tg.spin = 0
    tg.headRoll = 0.06 * Math.sin(TAU * 2.4 * tl) * ss(0.9, 1.1, tl)
    // 양팔 만세로 흔들다가, 착지하면 선물 상자(소품 gift)를 앞에 안는다
    const wig = ss(0.15, 0.5, tl) * (1 - ss(GIFT_CUE.in - 0.15, GIFT_CUE.in + 0.05, tl))
    const toGift = ss(GIFT_CUE.in - 0.2, GIFT_CUE.in + 0.12, tl)
    for (let si = 0; si < 2; si++) {
      const i = SIDES[si]
      armSetMix(tg, i, ss(0.05, 0.25, tl), G.upWide, G.holdGift, toGift)
      const s = Math.sin(TAU * 2.8 * tl + i * Math.PI)
      nudge(tg, i, 'upper', 0.16 * s * wig)
      nudge(tg, i, 'lower', 0.26 * Math.sin(TAU * 2.8 * tl + i * Math.PI + 0.9) * wig)
      nudge(tg, i, 'hand', 0.3 * Math.sin(TAU * 2.8 * tl + i * Math.PI + 1.6) * wig)
    }
  },
  events: [
    // 만세 든 두 손에서 바깥쪽 위로 (모자 위 가운데는 비워 둔다)
    ev(0.2, (fx, rng) => {
      confettiBurst(fx, rng, 8, 1, -0.6, 0.5, UP + 0.55, 0.5)
      confettiBurst(fx, rng, 8, 1, 0.6, 0.5, UP - 0.55, 0.5)
      sparkleAt(fx, rng, -0.6, 0.7, 0.2, 1.5)
      sparkleAt(fx, rng, 0.62, 0.78, 0.24, 1.6)
    }),
    ev(0.55, (fx, rng) => {
      confettiBurst(fx, rng, 5, 0.9, -0.62, 0.55, UP + 0.45, 0.45)
      confettiBurst(fx, rng, 5, 0.9, 0.62, 0.55, UP - 0.45, 0.45)
    }),
    ev(0.9, (fx) => dustPuffs(fx)),
    // 선물 상자 매듭이 팡 뛰는 순간(GIFT_POP): 상자 양옆 가장자리에서 바깥 위로 터진다 (입 앞을 지나지 않게 옆으로 크게 기울여서)
    ev(GIFT_POP, (fx, rng) => {
      confettiBurst(fx, rng, 6, 0.8, -0.24, -0.26, UP + 1.0, 0.35)
      confettiBurst(fx, rng, 6, 0.8, 0.24, -0.26, UP - 1.0, 0.35)
      sparkleAt(fx, rng, 0.34, 0.5, 0.14, 1.2)
    }),
  ],
}

/* ---------------- 10 일하는 척 (0 키) ---------------- */

const WORK_DUR = 5.0

const working: Spec = {
  id: 10,
  name: '일하는 척',
  dur: WORK_DUR,
  // 헤드폰을 쓰고 노트북이 펼쳐진 뒤 한창 타이핑하는 순간
  peak: 2.4,
  eval(tl, tg) {
    // 자세 진입(0.5초)과 마무리(끝나기 전 0.9초): 이 안에서 몸·고개·팔이 노트북 쪽으로 돌아갔다가 돌아온다
    const k = ss(0.05, 0.6, tl) * (1 - ss(WORK_DUR - 1.0, WORK_DUR - 0.4, tl))
    // 눈을 감은 채(blink 0.95 = 감은 ∪ 속눈썹) 은은한 미소로 건반을 친다 (working-2 레퍼런스)
    tg.gazeX = 0.12 * k
    tg.gazeY = -0.55 * k
    tg.blink = 0.95 * k
    tg.mouthOpen = 0
    tg.mouthSmile = 0.3 + 0.3 * k
    // 고개: 아래로 숙이고 노트북 쪽(캐릭터 왼쪽)으로 돌린다. 타이핑 리듬으로 아주 조금 끄덕인다
    const type = ss(0.5, 0.9, tl) * (1 - ss(WORK_DUR - 1.0, WORK_DUR - 0.5, tl))
    tg.headPitch = -0.17 * k + 0.012 * type * Math.sin(TAU * 3.1 * tl)
    tg.headYaw = 0.0 * k
    tg.headRoll = -0.03 * k + 0.012 * type * Math.sin(TAU * 0.9 * tl)
    // 캐릭터 전체를 노트북 쪽(자기 왼쪽)으로 3/4 만큼 돌리고(레퍼런스 구도), 상체를 조금 더 튼다
    tg.spin = 0.45 * k
    tg.twist = 0.2 * k
    tg.leanZ = 0.09 * k
    tg.squash = -0.01 * k
    // 팔: 양손이 키보드 위로. 손목은 위아래로 톡톡, 손가락은 엇갈려 눌린다 (구간마다 세기가 오르내려 쉬었다 치는 느낌)
    const burst = 0.6 + 0.4 * Math.sin(TAU * 0.55 * tl + 0.8)
    for (let si = 0; si < 2; si++) {
      const i = SIDES[si]
      armSet(tg, i, k, G.type)
      const a = tg.arms[i]
      const ph = i * 2.1
      const bob = Math.sin(TAU * 6.4 * tl + ph)
      nudge(tg, i, 'hand', 0, 0.06 * bob * type * burst, 0)
      nudge(tg, i, 'lower', 0, 0.02 * Math.sin(TAU * 3.2 * tl + ph + 1) * type * burst, 0)
      for (let n = 0; n < 5; n++) {
        // 손가락마다 다른 주파수·위상의 눌림 (한 번 눌릴 때 0..1 로 올랐다 내려온다)
        const f = Math.max(0, Math.sin(TAU * (5.2 + 0.7 * n) * tl + ph * 1.3 + n * 1.9))
        a.fingers[n] = Math.min(1, a.fingers[n] + 0.38 * f * f * type * burst)
      }
    }
  },
  events: [],
}

export const SPECS: readonly Spec[] = [laugh, love, greet, surprise, touched, kiss, angry, sleepy, celebrate, working]
