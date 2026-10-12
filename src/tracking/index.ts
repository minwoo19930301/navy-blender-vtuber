/**
 * src/tracking/index.ts — MediaPipe Tasks(Face + Hand + Pose Landmarker) 웹캠 트래커.
 *
 * 계약 v2: createTracker(): Tracker (src/contract.ts — ArmPose/BodyPose)
 *
 * 두 가지 실행 모드 (window.__mingoTracking.mode):
 *   'worker'  기본. 검출·매핑·필터링 전부 worker.ts(모듈 워커)에서 돈다. 이 파일은 프레임 펌프만 한다:
 *             rVFC → (워커가 놀고 있으면) createImageBitmap(video) → transfer → result 수신 → latest().
 *             메인 스레드는 렌더에만 집중한다.
 *   'main'    폴백. 같은 core를 메인 스레드 rVFC 안에서 직접 돌린다 (워커 이전의 동작).
 *             워커를 만들 수 없거나(미지원·보안 오류), 워커 초기화 실패·정지(무응답)·런타임 오류, 또는
 *             URL ?trackworker=0 일 때 자동으로 쓰고 이유를 콘솔에 남긴다.
 *
 * 프레임당 계산(필터·매핑·상태·더블버퍼)은 core.ts, 검출기 생성은 landmarkers.ts에 있다.
 */
import type { RigFrame, Tracker } from '../contract'
import { neutralFrame } from '../contract'
import type { TrackingCore } from './core'
import type { AssetUrls, LandmarkerSet } from './landmarkers'
import type { FromWorker, ReadyMsg, ResultMsg, ToWorker } from './protocol'

/* ---------------- 디버그 훅 ---------------- */

export interface MingoTrackingDebug {
  /** 실행 모드 — 워커가 돌면 'worker', 메인 스레드 폴백이면 'main' */
  mode?: 'worker' | 'main'
  /** 검출기별 델리게이트 (GPU 실패 시 CPU 폴백이 보인다) */
  delegates?: { face: 'GPU' | 'CPU'; hand: 'GPU' | 'CPU'; pose: 'GPU' | 'CPU' }
  /** 포즈·손을 매 프레임 돌리는 중인가 (검출 비용이 예산 안일 때) */
  everyFrame?: boolean
  /** 태스크별 검출 비용 EMA (ms) */
  costMs?: { face: number; pose: number; hand: number }
  /** 메인 스레드가 프레임 하나에 쓴 시간 EMA (ms): 워커 모드는 펌프+결과 수신, 메인 모드는 검출 전체 */
  mainMs?: number
  /** 워커 모드: 프레임을 캡처한 뒤 결과가 돌아오기까지 EMA (ms) */
  latencyMs?: number
  /** 처리된 프레임 속도 EMA (Hz) — 카메라가 아니라 트래커가 실제로 소화한 속도 */
  fps: number
  lastBlendshapes: Record<string, number> | null
  lastMatrix: number[] | null
  /** 포즈 visibility 게이팅 관찰용 (armL/armR=min(어깨,팔꿈치,손목), body=어깨, legs=무릎) */
  lastPoseVis: { armL: number; armR: number; body: number; legs: number } | null
}

declare global {
  interface Window {
    __mingoTracking?: MingoTrackingDebug
  }
}

/* ---------------- 상수 ---------------- */

// 메인 스레드 폴백은 렌더와 CPU를 나눠 쓰므로 워커(33ms)보다 보수적으로
const MAIN_EVERY_FRAME_BUDGET_MS = 24
// 워커 스크립트가 로드·실행돼 alive를 보내기까지 (에러 이벤트 없이 조용히 멈추는 로드 실패를 잡는다)
const WORKER_ALIVE_TIMEOUT_MS = 10_000
// 워커 초기화(11MB wasm + 모델 3개 로드)는 오래 걸릴 수 있다 — 이건 "영원히 안 끝남"만 잡는 안전망
const WORKER_INIT_TIMEOUT_MS = 60_000
// 비행 중인 프레임이 이 시간 동안 안 돌아오면 워커가 멈춘 것으로 보고 메인 스레드로 내린다
const WORKER_STALL_MS = 8_000

const ema = (prev: number | undefined, v: number, a = 0.1): number =>
  prev === undefined ? v : prev + (v - prev) * a

const errText = (err: unknown): string => (err instanceof Error ? err.message : String(err))

/* ---------------- 트래커 ---------------- */

export function createTracker(): Tracker {
  let videoEl: HTMLVideoElement | null = null
  let running = false
  let startPromise: Promise<void> | null = null
  let rvfcHandle = 0
  // start/stop 세대: 이미 정리된 워커의 늦은 메시지를 무시한다
  let gen = 0

  // 워커 모드 상태
  let worker: Worker | null = null
  let workerRig: RigFrame = neutralFrame()
  let busy = false // 프레임이 워커에 가 있거나 비트맵을 만드는 중 (동시에 최대 1개)
  let dropped = false // busy 동안 새 비디오 프레임이 지나갔다 → 결과가 오면 곧바로 최신 프레임을 보낸다
  let lastPresented = 0 // 가장 최근 rVFC의 presentedFrames
  let submittedPresented = -1 // 마지막으로 보낸 프레임의 presentedFrames (같은 프레임 중복 전송 방지)
  let lastSubmitNow = 0
  let busySinceMs = 0
  let mainAcc = 0 // 이 프레임 사이클에 메인이 쓴 누적 시간

  // 메인 모드 상태 (폴백 때만 만든다 — 코어·tasks-vision 청크는 지연 로드)
  let mainCore: TrackingCore | null = null
  let mainLm: LandmarkerSet | null = null

  const dbg: MingoTrackingDebug = {
    fps: 0,
    lastBlendshapes: null,
    lastMatrix: null,
    lastPoseVis: null,
  }
  if (typeof window !== 'undefined') window.__mingoTracking = dbg

  // ?trackbudget=<ms>: 포즈·손 매 프레임 판정 예산을 덮어쓴다 (벤치·튜닝용)
  const budgetOverride = (): number | undefined => {
    const v = Number(new URLSearchParams(location.search).get('trackbudget'))
    return v > 0 ? v : undefined
  }

  const assetUrls = (): AssetUrls => {
    // 워커 안에는 document가 없으므로 절대 URL로 만들어 보낸다 (file:// 포함)
    const abs = (p: string): string => new URL(p, document.baseURI).href
    return {
      wasmBase: abs('./wasm'),
      face: abs('./models/face_landmarker.task'),
      hand: abs('./models/hand_landmarker.task'),
      pose: abs('./models/pose_landmarker.task'),
    }
  }

  /* ---------- 워커 모드 ---------- */

  const forwardLog = (m: Extract<FromWorker, { type: 'log' }>): void => {
    if (m.level === 'error') console.error(m.message)
    else console.warn(m.message)
  }

  const onResult = (m: ResultMsg): void => {
    const t0 = performance.now()
    workerRig = m.rig
    dbg.fps = m.fps
    dbg.everyFrame = m.everyFrame
    dbg.costMs = m.costMs
    dbg.lastPoseVis = m.poseVis
    if (m.blendshapes) dbg.lastBlendshapes = m.blendshapes
    if (m.matrix) dbg.lastMatrix = m.matrix
    dbg.latencyMs = ema(dbg.latencyMs, t0 - busySinceMs)
    busy = false
    mainAcc += performance.now() - t0
    dbg.mainMs = ema(dbg.mainMs, mainAcc)
    mainAcc = 0
    // 처리 중에 새 비디오 프레임이 지나갔다면 다음 rVFC를 기다리지 않고 지금 최신 프레임을 보낸다.
    // (검출이 프레임 간격보다 길어도 처리율이 간격의 배수로 뚝 떨어지지 않게. 비행 중 1개 제한은 그대로)
    if (dropped && running && worker && videoReady()) submit(performance.now(), lastPresented)
  }

  const videoReady = (): boolean => !!videoEl && videoEl.readyState >= 2 && videoEl.videoWidth > 0

  /** busy가 false일 때만 호출 */
  const submit = (nowMs: number, presented: number): void => {
    const w = worker
    const v = videoEl
    if (!w || !v) return
    const myGen = gen
    // 타임스탬프는 단조 증가여야 한다 (캐치업 전송은 performance.now를 쓰므로 rVFC now와 어긋날 수 있다)
    nowMs = Math.max(nowMs, lastSubmitNow + 1)
    lastSubmitNow = nowMs
    busy = true
    dropped = false
    submittedPresented = presented
    busySinceMs = performance.now()
    createImageBitmap(v).then(
      (bitmap) => {
        const t0 = performance.now()
        if (myGen !== gen || worker !== w) {
          bitmap.close()
          return
        }
        const msg: ToWorker = { type: 'frame', bitmap, nowMs }
        w.postMessage(msg, [bitmap])
        mainAcc += performance.now() - t0
      },
      (err) => {
        // 비디오가 막 정지/교체된 경우 등. 다음 rVFC에서 다시 시도한다
        if (myGen === gen) busy = false
        console.warn('[tracking] createImageBitmap 실패', err)
      },
    )
  }

  const pumpWorker = (nowMs: number, meta: VideoFrameCallbackMetadata): void => {
    const t0 = performance.now()
    lastPresented = meta.presentedFrames
    if (busy) {
      dropped = true
      if (t0 - busySinceMs > WORKER_STALL_MS) void degradeToMain(`워커가 ${WORKER_STALL_MS / 1000}초 넘게 응답하지 않음`)
      return
    }
    if (!videoReady() || meta.presentedFrames <= submittedPresented) return
    submit(nowMs, meta.presentedFrames)
    mainAcc += performance.now() - t0
  }

  /** 워커를 만들고 초기화(WASM·모델 로드)가 끝날 때까지 기다린다. 실패하면 던진다 */
  const startWorker = async (): Promise<ReadyMsg> => {
    // 형태 주의: Vite가 이 리터럴(new Worker(new URL('./x', import.meta.url), { type: 'module' }))을 보고 번들한다
    const w = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })
    worker = w
    try {
      return await new Promise<ReadyMsg>((resolve, reject) => {
        const aliveTimer = setTimeout(
          () => reject(new Error(`워커 스크립트가 ${WORKER_ALIVE_TIMEOUT_MS / 1000}초 안에 시작되지 않음`)),
          WORKER_ALIVE_TIMEOUT_MS,
        )
        const timer = setTimeout(
          () => reject(new Error(`초기화가 ${WORKER_INIT_TIMEOUT_MS / 1000}초 안에 끝나지 않음`)),
          WORKER_INIT_TIMEOUT_MS,
        )
        const done = <T>(fn: (v: T) => void) => (v: T) => {
          clearTimeout(aliveTimer)
          clearTimeout(timer)
          fn(v)
        }
        w.onmessage = (e: MessageEvent<FromWorker>) => {
          const m = e.data
          if (m.type === 'alive') clearTimeout(aliveTimer)
          else if (m.type === 'ready') done(resolve)(m)
          else if (m.type === 'init-error') done(reject)(new Error(m.message))
          else if (m.type === 'log') forwardLog(m)
        }
        // 스크립트 로드 실패(file:// 보안 등)·초기화 전 크래시는 여기로 온다
        w.onerror = (ev) =>
          done(reject)(new Error(`워커 오류: ${ev.message || '스크립트를 불러오지 못함'}`))
        w.onmessageerror = () => done(reject)(new Error('워커 메시지 역직렬화 실패'))
        const init: ToWorker = { type: 'init', urls: assetUrls(), everyFrameBudgetMs: budgetOverride() }
        w.postMessage(init)
      })
    } catch (err) {
      w.terminate()
      if (worker === w) worker = null
      throw err
    }
  }

  const attachWorkerRuntime = (w: Worker): void => {
    const myGen = gen
    w.onmessage = (e: MessageEvent<FromWorker>) => {
      if (myGen !== gen || worker !== w) return
      const m = e.data
      if (m.type === 'result') onResult(m)
      else if (m.type === 'log') forwardLog(m)
    }
    w.onerror = (ev) => {
      if (myGen !== gen || worker !== w) return
      void degradeToMain(`워커 런타임 오류: ${ev.message || '알 수 없음'}`)
    }
  }

  const disposeWorker = (): void => {
    if (worker) {
      worker.onmessage = null
      worker.onerror = null
      worker.terminate()
      worker = null
    }
    busy = false
    dropped = false
    submittedPresented = -1
    mainAcc = 0
  }

  /* ---------- 메인 모드 (폴백) ---------- */

  const startMain = async (): Promise<void> => {
    // 폴백 때만 필요하다 — 워커가 정상이면 이 청크들은 내려받지 않는다
    const [{ createTrackingCore }, { createLandmarkers }] = await Promise.all([
      import('./core'),
      import('./landmarkers'),
    ])
    if (!mainCore) {
      mainCore = createTrackingCore({ everyFrameBudgetMs: budgetOverride() ?? MAIN_EVERY_FRAME_BUDGET_MS })
    }
    mainLm?.close()
    // 메인 스레드는 classic <script> 로더를 그대로 쓴다 (워커 이전과 같은 경로)
    mainLm = await createLandmarkers(assetUrls(), false)
    dbg.mode = 'main'
    dbg.delegates = mainLm.delegates
  }

  const stepMain = (nowMs: number): void => {
    if (!mainCore || !mainLm || !videoEl || !videoReady()) return
    const t0 = performance.now()
    mainCore.step(videoEl, nowMs, mainLm.lm)
    const d = mainCore.debug
    dbg.fps = d.fps
    dbg.everyFrame = d.everyFrame
    dbg.costMs = d.costMs
    dbg.lastPoseVis = d.lastPoseVis
    dbg.lastBlendshapes = d.lastBlendshapes
    dbg.lastMatrix = d.lastMatrix
    dbg.mainMs = ema(dbg.mainMs, performance.now() - t0)
  }

  /** 실행 중에 워커가 죽었을 때: 같은 비디오로 메인 스레드 모드로 갈아탄다 */
  let degrading = false
  const degradeToMain = async (reason: string): Promise<void> => {
    if (degrading || dbg.mode !== 'worker') return
    degrading = true
    const myGen = gen
    console.warn(`[tracking] 워커 트래킹 중단 → 메인 스레드 폴백: ${reason}`)
    disposeWorker()
    dbg.mode = 'main' // 이 시점부터 펌프가 stepMain을 부른다 (mainLm이 준비되기 전엔 건너뜀)
    try {
      await startMain()
      if (myGen !== gen) {
        // 폴백 초기화 중에 stop()이 왔다 — 방금 만든 검출기를 버린다
        mainLm?.close()
        mainLm = null
      }
    } catch (err) {
      console.error('[tracking] 메인 스레드 폴백도 초기화 실패 — 트래킹 중단', err)
      if (myGen === gen) running = false
    } finally {
      degrading = false
    }
  }

  /* ---------- 루프 ---------- */

  const scheduleLoop = (): void => {
    if (!videoEl || !running) return
    rvfcHandle = videoEl.requestVideoFrameCallback((now, meta) => {
      if (!running) return
      try {
        if (dbg.mode === 'worker') pumpWorker(now, meta)
        else stepMain(now)
      } finally {
        scheduleLoop()
      }
    })
  }

  const workerSupported = (): string | null => {
    if (typeof Worker === 'undefined') return 'Worker 미지원'
    if (typeof OffscreenCanvas === 'undefined') return 'OffscreenCanvas 미지원 (워커에서 GPU 델리게이트 불가)'
    if (typeof createImageBitmap !== 'function') return 'createImageBitmap 미지원'
    if (new URLSearchParams(location.search).get('trackworker') === '0') return 'URL ?trackworker=0'
    return null
  }

  const doStart = async (video: HTMLVideoElement): Promise<void> => {
    gen++
    workerRig = neutralFrame()
    delete dbg.mode
    delete dbg.mainMs
    delete dbg.latencyMs

    let fallback = workerSupported()
    if (!fallback) {
      try {
        const ready = await startWorker()
        attachWorkerRuntime(worker!)
        dbg.mode = 'worker'
        dbg.delegates = ready.delegates
        const d = ready.delegates
        console.log(`[tracking] 워커 모드 (face ${d.face}, hand ${d.hand}, pose ${d.pose})`)
      } catch (err) {
        fallback = errText(err)
      }
    }
    if (fallback) {
      console.warn(`[tracking] 메인 스레드 폴백: ${fallback}`)
      try {
        await startMain()
      } catch (err) {
        mainLm = null
        console.error('[tracking] mediapipe 초기화 실패 — ./wasm 및 ./models/*.task 경로/파일 확인', err)
        throw new Error('tracking init failed: ' + errText(err), { cause: err })
      }
    }

    videoEl = video
    running = true
    scheduleLoop()
  }

  return {
    start(video: HTMLVideoElement): Promise<void> {
      if (running) return Promise.resolve()
      startPromise ??= doStart(video).finally(() => {
        startPromise = null
      })
      return startPromise
    },

    stop(): void {
      // 초기화 중의 stop()은 무시한다. start()는 끝까지 가고, 호출측(main.ts)이 resolve 뒤에
      // camWanted를 다시 보고 필요하면 stop()을 부른다 (hide→show가 겹치면 시작이 맞는 결과다).
      if (startPromise) return
      running = false
      gen++
      if (videoEl && rvfcHandle !== 0) {
        videoEl.cancelVideoFrameCallback(rvfcHandle)
        rvfcHandle = 0
      }
      disposeWorker()
      mainLm?.close()
      mainLm = null
      videoEl = null
      degrading = false
    },

    latest(): RigFrame {
      return dbg.mode === 'main' && mainCore ? mainCore.latest() : workerRig
    },
  }
}
