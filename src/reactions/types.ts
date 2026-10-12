/**
 * 리액션 타임라인이 매 프레임 채우는 "목표"(Target)와 타임라인 명세(Spec) 타입.
 *
 * 한 리액션 = 시간(초)만 받는 순수 함수 eval(tl, tg) + 시간순 FX 이벤트 목록.
 * 엔진이 목표를 트래킹 프레임 위에 엔벨로프 가중치로 섞는다 (index.ts).
 *  - 얼굴 채널(눈 깜빡임·시선·입)은 덮어쓴다. NaN = 건드리지 않음 (트래킹 값이 그대로 흐른다).
 *  - 머리·몸통(lean/twist)은 더한다. 트래킹이 계속 살아 있다.
 *  - 몸 움직임(motion)은 가중치를 곱해 합친다.
 *  - 팔은 armW(0..1) 만큼 목표 자세로 방향을 섞는다.
 */
import type { Dir3 } from '../contract'
import type { Fx } from './fx'

export const KEEP = Number.NaN

export interface ArmTarget {
  upper: Dir3
  lower: Dir3
  hand: Dir3
  palm: Dir3
  fingers: [number, number, number, number, number]
  spread: number
  /** 팔 길이 배율 (1 = 그대로). 소품을 공 앞 가운데까지 안아 들 때 팔이 늘어난다 */
  stretch: number
}

export interface Target {
  /** 얼굴 채널 — NaN 이면 트래킹/idle 값 유지 */
  blink: number
  gazeX: number
  gazeY: number
  mouthOpen: number
  mouthSmile: number
  /** 표정 플래그 (가중치가 문턱을 넘은 리액션 하나가 정한다) */
  happy: boolean
  heart: boolean
  kiss: boolean
  teary: boolean
  surprised: boolean
  sleepy: boolean
  angry: boolean
  blush: number
  tear: number
  /** 머리 (더함, rad) */
  headPitch: number
  headYaw: number
  headRoll: number
  /** 몸통 (더함, rad) */
  leanX: number
  leanZ: number
  twist: number
  /** 몸 전체 움직임 */
  bounce: number
  squash: number
  spin: number
  shiftX: number
  push: number
  /** 캐릭터 왼팔이 입을 따라가는 세기 0..1 (입에 물고 쥐는 소품: 머리를 돌리면 주먹도 입술을 따라 돈다, follow.ts) */
  mouthFollow: number
  /** 팔 덮어쓰기 강도 0..1 (L = 캐릭터 왼팔, R = 캐릭터 오른팔) */
  armW: [number, number]
  arms: [ArmTarget, ArmTarget]
}

function armTarget(): ArmTarget {
  return {
    upper: { x: 0, y: -1, z: 0 },
    lower: { x: 0, y: -1, z: 0 },
    hand: { x: 0, y: -1, z: 0 },
    palm: { x: 0, y: 0, z: 1 },
    fingers: [0, 0, 0, 0, 0],
    spread: 0,
    stretch: 1,
  }
}

export function createTarget(): Target {
  const t = {
    armW: [0, 0],
    arms: [armTarget(), armTarget()],
  } as Target
  resetTarget(t)
  return t
}

/** 매 평가 전에 중립으로 되돌린다 (팔 벡터는 armW 가 0 이면 쓰이지 않아 그대로 둔다) */
export function resetTarget(t: Target): void {
  t.blink = KEEP; t.gazeX = KEEP; t.gazeY = KEEP; t.mouthOpen = KEEP; t.mouthSmile = KEEP
  t.happy = false; t.heart = false; t.kiss = false; t.teary = false; t.surprised = false; t.sleepy = false; t.angry = false
  t.blush = 0; t.tear = 0
  t.headPitch = 0; t.headYaw = 0; t.headRoll = 0
  t.leanX = 0; t.leanZ = 0; t.twist = 0
  t.bounce = 0; t.squash = 0; t.spin = 0; t.shiftX = 0; t.push = 0
  t.armW[0] = 0; t.armW[1] = 0
  t.mouthFollow = 0
}

/** FX 이벤트: 타임라인 시각 t 에 한 번 실행된다. rng 는 트리거마다 시드가 정해진 결정적 난수 */
export interface FxEvent {
  t: number
  run(fx: Fx, rng: () => number): void
}

export interface Spec {
  id: number
  /** 한국어 이름 (메뉴·디버그) */
  name: string
  /** 전체 길이(초). 끝나기 직전 0.35초가 서서히 사라지는 구간이다 */
  dur: number
  /** 시트·미리보기용 대표 시각(초) */
  peak: number
  eval(tl: number, tg: Target): void
  events: readonly FxEvent[]
}
