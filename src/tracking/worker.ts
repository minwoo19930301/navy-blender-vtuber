/**
 * src/tracking/worker.ts — 트래킹 모듈 워커.
 *
 * MediaPipe 검출(얼굴·포즈·손)과 RigFrame 매핑·필터링 전부가 여기서 돈다. 메인 스레드는
 * 프레임을 비트맵으로 넘기고 결과 RigFrame을 받기만 한다 (index.ts, 메시지 정의는 protocol.ts).
 *
 * 모듈 워커에는 importScripts가 없어서(호출하면 TypeError) tasks-vision 로더가 동적 import()로
 * 떨어진다. 그래서 ES 모듈용 wasm 로더(vision_wasm_module_internal.js)를 쓰도록
 * createLandmarkers(urls, true)로 초기화한다. wasm/모델 URL은 메인이 절대 URL로 만들어 보낸다.
 */
import { createTrackingCore, type TrackingCore } from './core'
import { createLandmarkers, type LandmarkerSet } from './landmarkers'
import type { FromWorker, ResultMsg, ToWorker } from './protocol'

/** tsconfig가 DOM lib이라 WorkerGlobalScope 타입이 없다 — 필요한 면만 좁게 선언 */
interface WorkerScope {
  postMessage(msg: FromWorker): void
  onmessage: ((e: MessageEvent<ToWorker>) => void) | null
}
const scope = self as unknown as WorkerScope

// 워커는 렌더와 스레드를 나누지 않으니 예산을 넘겨도 메인 스레드는 영향이 없고, 처리율이 ≈1000/합 Hz로
// 내려갈 뿐이다. 합 40ms면 세 태스크가 모두 ≈25Hz — 얼굴 30Hz + 포즈·손 15Hz(격프레임)보다 팔이 낫다.
// 실측 합이 33ms(MacBook 메인 스레드 기준)라 카메라 프레임 간격(33ms)에 여유를 둬 경계에서 걸치지 않게 한다.
const DEFAULT_EVERY_FRAME_BUDGET_MS = 40
// blendshapes/matrix 같은 큰 디버그 필드는 이 간격으로만 싣는다
const DEBUG_PAYLOAD_EVERY_MS = 250

const send = (msg: FromWorker): void => scope.postMessage(msg)
const text = (err: unknown): string => (err instanceof Error ? `${err.name}: ${err.message}` : String(err))

let set: LandmarkerSet | null = null
let core: TrackingCore | null = null
let lastDebugPayloadMs = -Infinity

async function init(msg: Extract<ToWorker, { type: 'init' }>): Promise<void> {
  try {
    set = await createLandmarkers(msg.urls, true, (m, e) =>
      send({ type: 'log', level: 'warn', message: e === undefined ? m : `${m} — ${text(e)}` }),
    )
    core = createTrackingCore({
      everyFrameBudgetMs: msg.everyFrameBudgetMs ?? DEFAULT_EVERY_FRAME_BUDGET_MS,
      onError: (what, err) =>
        send({ type: 'log', level: 'error', message: `[tracking] ${what} detectForVideo 실패 — ${text(err)}` }),
    })
    send({ type: 'ready', delegates: set.delegates })
  } catch (err) {
    set?.close()
    set = null
    core = null
    send({ type: 'init-error', message: text(err) })
  }
}

function frame(bitmap: ImageBitmap, nowMs: number): void {
  const t0 = performance.now()
  if (!core || !set) {
    bitmap.close()
    return
  }
  try {
    core.step(bitmap, nowMs, set.lm)
  } catch (err) {
    // 검출 예외는 core가 태스크별로 삼킨다. 여기까지 온 건 예상 밖 — 그래도 응답은 반드시 보낸다
    // (메인은 result를 받아야 다음 프레임을 보낸다)
    send({ type: 'log', level: 'error', message: `[tracking] 프레임 처리 예외 — ${text(err)}` })
  } finally {
    bitmap.close()
  }

  const d = core.debug
  const msg: ResultMsg = {
    type: 'result',
    rig: core.latest(), // postMessage가 이 시점의 구조화 복제본을 만든다
    fps: d.fps,
    everyFrame: d.everyFrame,
    costMs: d.costMs,
    poseVis: d.lastPoseVis,
    workMs: performance.now() - t0,
  }
  if (t0 - lastDebugPayloadMs >= DEBUG_PAYLOAD_EVERY_MS) {
    lastDebugPayloadMs = t0
    if (d.lastBlendshapes) msg.blendshapes = d.lastBlendshapes
    if (d.lastMatrix) msg.matrix = d.lastMatrix
  }
  send(msg)
}

scope.onmessage = (e) => {
  const m = e.data
  if (m.type === 'init') void init(m)
  else if (m.type === 'frame') frame(m.bitmap, m.nowMs)
}
// 메시지 핸들러까지 준비됐다 — 메인은 이게 오기 전에 보낸 init을 큐에 쌓아 둔다
send({ type: 'alive' })
