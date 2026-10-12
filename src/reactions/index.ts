/**
 * 리액션 엔진 — 숫자키 1~9 로 재생하는 결정적 타임라인 (docs/REACTIONS.md).
 *
 * 파이프라인에서의 자리: tracking → mirror → aliveness → **reactions** → model.apply.
 * 트래킹은 리액션 아래에서 계속 살아 있고, 엔벨로프가 0 으로 돌아가면 부드럽게 다시 넘겨받는다.
 *
 * - 리액션 하나 = Layer 하나 (타임라인 + 엔벨로프 가중치 w). 다른 키를 누르면 이전 레이어는 0.22초에 걸쳐 나가고 새 레이어가 0.15초에 걸쳐 들어온다 (교차).
 *   같은 키를 다시 누르면 새 레이어가 0 초부터 다시 시작한다. 레이어는 최대 3개이고, 오래된 것부터 차례로 겹쳐 쓴다.
 * - 얼굴 채널은 w 만큼 덮어쓰고, 머리·몸통은 더하고, 팔은 목표 자세 쪽으로 방향을 섞는다. 표정 플래그(눈·입 모양)는 w 가 문턱을 넘은 가장 최근 레이어가 정한다.
 * - 같은 (트리거 순서, 시각) 이면 같은 결과다: 시간은 호출자가 넘기는 t 뿐이고 난수는 트리거마다 시드가 정해진 mulberry32 뿐이다.
 * - compose() 는 aliveness 가 새로 만든 프레임을 그 자리에서 고쳐 쓴다 (프레임당 할당 없음).
 */
import * as THREE from 'three'
import { neutralMotion, type ArmPose, type BodyMotion, type RigFrame } from '../contract'
import { mulberry32 } from '../aliveness/rng'
import { createFx, type Fx } from './fx'
import { SPECS } from './timelines'
import { createTarget, resetTarget, type ArmTarget, type Spec, type Target } from './types'
import { slerpInto, ss } from './util'

export type { Spec } from './types'

/** 레이어 하나의 현재 상태 — 소품(props.ts)이 팝 엔벨로프와 애니메이션 시각을 읽는다. 엔진이 compose 마다 제자리에서 채운다 (할당 없음) */
export interface LayerView {
  /** 재생 중인 리액션 번호, 비어 있으면 0 */
  id: number
  /** 이 리액션을 트리거한 뒤 지난 시간(초) */
  tl: number
  /** 엔벨로프 가중치 0..1 (smoothstep) */
  w: number
  /** 교체·취소·종료로 나가는 중이면 true */
  leaving: boolean
}

export interface Reactions {
  /** id 1..9 재생 시작 (이미 재생 중이면 처음부터 다시, 다른 번호면 교차). t = 현재 시각(초) */
  trigger(id: number, t: number): void
  /** 재생 중인 리액션을 모두 접는다 (0.3초에 걸쳐 사라진다) */
  cancel(t: number): void
  /** aliveness 출력 위에 리액션을 합성한다. frame 을 그 자리에서 고쳐 쓰고 그대로 돌려준다 */
  compose(frame: RigFrame, dt: number, t: number): RigFrame
  /** 하트·꽃·색종이 등 FX 루트. 씬에 추가한다 (main.ts, harness.ts) */
  fxRoot: THREE.Group
  /** 레이어 3개의 상태 (직전 compose 기준). 소품이 읽는다 */
  layers: readonly LayerView[]
  /** 지금 재생 중인(교체·취소·종료로 나가는 중이 아닌) 리액션 번호, 없으면 null */
  active(): number | null
  /** 리액션이 아직 화면에 영향을 주고 있으면 true (나가는 중인 레이어와 떠 있는 FX 포함). 렌더 루프가 프레임 상한을 올리는 데 쓴다 */
  busy(): boolean
  /** 모든 리액션 명세 (메뉴·하네스 시트용) */
  specs: readonly Spec[]
  dispose(): void
}

const IN_SEC = 0.15
const OUT_SEC = 0.35
const SWAP_OUT_SEC = 0.22
const CANCEL_SEC = 0.3
/**
 * 표정 플래그(눈·입 모양)를 쓰는 문턱. 들어올 때는 0.35 부터 켜고, 나갈 때는 0.12 까지 유지한다.
 * 같은 문턱을 쓰면 나가는 길에 플래그만 먼저 꺼져서 미소·입 벌림이 35% 남은 채 점 눈에 반쯤 벌어진 입이 몇 프레임 보인다.
 */
const FLAG_ON = 0.35
const FLAG_OFF = 0.12
const LAYERS = 3

interface Layer {
  spec: Spec | null
  t0: number
  /** 선형 엔벨로프 0..1 (가중치 w = smoothstep(raw)) */
  raw: number
  target: 0 | 1
  outSec: number
  /** 다음에 실행할 FX 이벤트 번호 */
  ev: number
  rng: () => number
  /** 시작 순서 (겹쳐 쓰는 순서) */
  seq: number
}

const mix = (a: number, b: number, w: number): number => a + (b - a) * w

export function createReactions(): Reactions {
  const fx: Fx = createFx()
  const layers: Layer[] = []
  for (let i = 0; i < LAYERS; i++) {
    layers.push({ spec: null, t0: 0, raw: 0, target: 0, outSec: OUT_SEC, ev: 0, rng: mulberry32(1), seq: 0 })
  }
  const order: Layer[] = layers.slice() // 겹쳐 쓰는 순서 (오래된 것 먼저), 프레임마다 제자리 정렬
  const views: LayerView[] = []
  for (let i = 0; i < LAYERS; i++) views.push({ id: 0, tl: 0, w: 0, leaving: false })
  const tg: Target = createTarget()
  const motion: BodyMotion = neutralMotion()
  let seq = 0
  let triggers = 0

  const byId = new Map<number, Spec>()
  for (const s of SPECS) byId.set(s.id, s)

  const blendArm = (a: ArmPose, g: ArmTarget, w: number, outward: number): void => {
    slerpInto(a.upperDir, a.upperDir, g.upper, w, outward)
    slerpInto(a.lowerDir, a.lowerDir, g.lower, w, outward)
    slerpInto(a.handDir, a.handDir, g.hand, w, outward)
    slerpInto(a.palmNormal, a.palmNormal, g.palm, w, outward)
    for (let k = 0; k < 5; k++) a.fingers[k] = mix(a.fingers[k], g.fingers[k], w)
    a.spread = mix(a.spread, g.spread, w)
    a.stretch = mix(a.stretch ?? 1, g.stretch, w)
    if (a.present < w) a.present = w
  }

  const sortOrder = (): void => {
    // 3개짜리 삽입 정렬 (seq 오름차순)
    for (let i = 1; i < order.length; i++) {
      const x = order[i]
      let j = i - 1
      while (j >= 0 && order[j].seq > x.seq) {
        order[j + 1] = order[j]
        j--
      }
      order[j + 1] = x
    }
  }

  return {
    fxRoot: fx.root,
    layers: views,
    specs: SPECS,

    trigger(id, t) {
      const spec = byId.get(Math.round(id))
      if (!spec) return
      // 지금 재생 중인 레이어는 모두 나가게 한다
      for (const L of layers) {
        if (L.spec && L.target === 1) {
          L.target = 0
          L.outSec = SWAP_OUT_SEC
        }
      }
      // 빈 슬롯, 없으면 가장 약한 레이어를 재사용
      let slot = layers[0]
      for (const L of layers) {
        if (!L.spec) {
          slot = L
          break
        }
        if (L.raw < slot.raw) slot = L
      }
      triggers++
      slot.spec = spec
      slot.t0 = t
      slot.raw = 0
      slot.target = 1
      slot.outSec = OUT_SEC
      slot.ev = 0
      slot.rng = mulberry32(spec.id * 7919 + triggers * 104729 + 12345)
      slot.seq = ++seq
    },

    cancel(t) {
      for (const L of layers) {
        if (L.spec && L.target === 1) {
          L.target = 0
          L.outSec = CANCEL_SEC
        }
      }
      fx.fadeAll(t, CANCEL_SEC)
    },

    compose(frame, dt, t) {
      fx.now = t
      let any = false
      sortOrder()
      motion.bounce = 0; motion.squash = 0; motion.spin = 0; motion.shiftX = 0; motion.push = 0
      let blush = frame.fx.blush ?? 0
      let follow = 0

      for (let li = 0; li < LAYERS; li++) {
        const L = order[li]
        const spec = L.spec
        const view = views[li]
        view.id = 0; view.w = 0
        if (!spec) continue
        const tl = t - L.t0
        if (L.target === 1 && tl >= spec.dur - OUT_SEC) {
          L.target = 0
          L.outSec = OUT_SEC
        }
        if (L.target === 1) L.raw = Math.min(1, L.raw + dt / IN_SEC)
        else L.raw = Math.max(0, L.raw - dt / L.outSec)
        if (L.target === 0 && L.raw <= 0) {
          L.spec = null
          continue
        }
        any = true
        const w = ss(0, 1, L.raw)
        view.id = spec.id; view.tl = tl; view.w = w; view.leaving = L.target === 0
        resetTarget(tg)
        spec.eval(tl, tg)

        // ---- 얼굴: 덮어쓰기 (NaN 은 건드리지 않음) ----
        if (tg.blink === tg.blink) { frame.blinkL = mix(frame.blinkL, tg.blink, w); frame.blinkR = mix(frame.blinkR, tg.blink, w) }
        if (tg.gazeX === tg.gazeX) frame.gaze.x = mix(frame.gaze.x, tg.gazeX, w)
        if (tg.gazeY === tg.gazeY) frame.gaze.y = mix(frame.gaze.y, tg.gazeY, w)
        if (tg.mouthOpen === tg.mouthOpen) frame.mouthOpen = mix(frame.mouthOpen, tg.mouthOpen, w)
        if (tg.mouthSmile === tg.mouthSmile) frame.mouthSmile = mix(frame.mouthSmile, tg.mouthSmile, w)
        blush = mix(blush, tg.blush, w)
        if (w >= (L.target === 1 ? FLAG_ON : FLAG_OFF)) {
          const f = frame.fx
          f.happy = tg.happy; f.heart = tg.heart; f.kiss = tg.kiss; f.teary = tg.teary
          f.surprised = tg.surprised; f.sleepy = tg.sleepy; f.angry = tg.angry
          f.tear = tg.tear
        }

        // ---- 머리·몸통: 더하기 (트래킹이 계속 살아 있다) ----
        frame.head.pitch += tg.headPitch * w
        frame.head.yaw += tg.headYaw * w
        frame.head.roll += tg.headRoll * w
        frame.body.lean.x += tg.leanX * w
        frame.body.lean.z += tg.leanZ * w
        frame.body.twist += tg.twist * w

        // ---- 몸 움직임: 가중 합. 자전은 한 바퀴가 곧 제자리라 도는 도중(들어가는 중)에는 그대로, 나가는 중에만 w 를 곱해 풀어 준다 ----
        motion.bounce += tg.bounce * w
        motion.squash += tg.squash * w
        motion.shiftX += tg.shiftX * w
        motion.push += tg.push * w
        motion.spin += tg.spin * (L.target === 1 ? 1 : w)

        // ---- 팔 ----
        const aL = w * tg.armW[0]
        const aR = w * tg.armW[1]
        if (aL > 1e-4) blendArm(frame.armL, tg.arms[0], aL, 1)
        if (aR > 1e-4) blendArm(frame.armR, tg.arms[1], aR, -1)
        const f = w * tg.mouthFollow
        if (f > follow) follow = f
      }

      // 입에 물고 쥐는 소품(뿔피리): 모든 레이어의 머리 가산이 끝난 최종 머리 포즈로 왼팔을 입술 쪽으로 돌린다


      if (any) {
        frame.fx.blush = blush
        frame.motion = motion
      }
      // FX: 앵커(공 중심)를 현재 몸 움직임에 맞추고 이벤트를 실행한 뒤 입자를 갱신한다
      fx.anchor.x = motion.shiftX
      fx.anchor.y = 0.5 + motion.bounce
      for (let li = 0; li < LAYERS; li++) {
        const L = order[li]
        const spec = L.spec
        if (!spec || L.target !== 1) continue
        const tl = t - L.t0
        const evs = spec.events
        while (L.ev < evs.length && evs[L.ev].t <= tl) {
          evs[L.ev].run(fx, L.rng)
          L.ev++
        }
      }
      fx.update(t)
      return frame
    },

    active() {
      let best: Layer | null = null
      for (let i = 0; i < LAYERS; i++) {
        const L = layers[i]
        if (L.spec && L.target === 1 && (!best || L.seq > best.seq)) best = L
      }
      return best && best.spec ? best.spec.id : null
    },

    busy() {
      if (fx.alive() > 0) return true
      for (let i = 0; i < LAYERS; i++) if (layers[i].spec) return true
      return false
    },

    dispose() {
      fx.dispose()
    },
  }
}
