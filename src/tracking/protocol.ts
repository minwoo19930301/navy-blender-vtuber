/**
 * src/tracking/protocol.ts — 메인 ↔ 트래킹 워커 메시지 (타입만, 런타임 코드 없음).
 *
 * 흐름: worker 스크립트 실행 시작 → {alive}
 *       main → {init} → worker 가 WASM·모델 로드 → {ready} | {init-error}
 *       main → {frame, 비트맵 transfer} → worker 검출 → {result, RigFrame}  (프레임당 1:1)
 * 한 번에 비행 중인 frame은 최대 1개다 (메인이 result를 받기 전엔 다음 frame을 보내지 않는다).
 */
import type { RigFrame } from '../contract'
import type { AssetUrls, Delegate } from './landmarkers'

export interface InitMsg {
  type: 'init'
  /** 모두 절대 URL — 워커 안에서는 document.baseURI가 없고, 상대 경로는 워커 스크립트 기준이 된다 */
  urls: AssetUrls
  /** 포즈·손 매 프레임 판정 예산 (ms). 생략하면 워커 기본값 */
  everyFrameBudgetMs?: number
}

export interface FrameMsg {
  type: 'frame'
  /** transfer 된다. 워커가 검출 후 close() 한다 */
  bitmap: ImageBitmap
  /** 메인의 단일 시간축(performance.now). dt·타임스탬프·타이머 전부 이 값 기준 */
  nowMs: number
}

export type ToWorker = InitMsg | FrameMsg

/** 워커 스크립트가 로드되어 실행되기 시작했다 (로드 실패가 error 이벤트 없이 조용히 멈추는 경우를 잡는다) */
export interface AliveMsg {
  type: 'alive'
}

export interface ReadyMsg {
  type: 'ready'
  delegates: { face: Delegate; hand: Delegate; pose: Delegate }
}

export interface InitErrorMsg {
  type: 'init-error'
  message: string
}

/** 워커 콘솔은 페이지 콘솔(스모크가 읽는 곳)에 안 보이므로 경고·오류는 메인이 대신 찍는다 */
export interface LogMsg {
  type: 'log'
  level: 'warn' | 'error'
  message: string
}

export interface ResultMsg {
  type: 'result'
  /** 완성된 최신 프레임 (구조화 복제본) */
  rig: RigFrame
  fps: number
  everyFrame: boolean
  costMs: { face: number; pose: number; hand: number }
  poseVis: { armL: number; armR: number; body: number; legs: number } | null
  /** 워커 안에서 이 프레임 처리에 걸린 시간 (ms) */
  workMs: number
  /** 디버그용 큰 필드는 ≈4Hz로만 싣는다 (프레임마다 복제하지 않으려고) */
  blendshapes?: Record<string, number>
  matrix?: number[]
}

export type FromWorker = AliveMsg | ReadyMsg | InitErrorMsg | LogMsg | ResultMsg
