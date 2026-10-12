/**
 * src/tracking/landmarkers.ts — MediaPipe Face/Hand/Pose Landmarker 생성 (GPU → CPU 폴백).
 *
 * 워커와 메인 스레드 폴백이 공유한다. 이 파일만 @mediapipe/tasks-vision 런타임을 import 한다.
 * 에셋은 전부 로컬이다 (네트워크 금지): wasm 디렉터리와 .task 모델의 URL은 호출자가 준다.
 */
import {
  FaceLandmarker,
  FilesetResolver,
  HandLandmarker,
  PoseLandmarker,
} from '@mediapipe/tasks-vision'
import type { Landmarkers } from './core'

export interface AssetUrls {
  /** wasm 디렉터리 (끝에 / 없음). 워커에서는 절대 URL이어야 한다 */
  wasmBase: string
  face: string
  hand: string
  pose: string
}

export type Delegate = 'GPU' | 'CPU'

/**
 * 모듈 워커용 wasm 로더 훅.
 *
 * tasks-vision은 인스턴스를 만들 때마다 로더 스크립트를 다시 "실행"해 self.ModuleFactory를 얻고,
 * 만든 직후 self.ModuleFactory를 undefined로 지운다. classic importScripts는 매번 재실행하지만
 * 동적 import()는 ES 모듈을 캐시해서 두 번째 호출부터 재실행하지 않는다 → 두 번째 landmarker가
 * "ModuleFactory not set."으로 죽는다 (얼굴만 만들어지고 손에서 실패하는 식).
 * tasks-vision은 self.import가 있으면 import() 대신 그걸 호출하므로, 모듈의 default export(= 팩토리)를
 * 호출 때마다 self.ModuleFactory에 다시 꽂아 준다. 팩토리는 호출마다 새 wasm 인스턴스를 만든다.
 */
function installModuleLoaderHook(): void {
  const g = globalThis as unknown as {
    import?: (url: string) => Promise<void>
    ModuleFactory?: unknown
  }
  g.import = async (url: string): Promise<void> => {
    const mod = (await import(/* @vite-ignore */ url)) as { default?: unknown }
    g.ModuleFactory = mod.default ?? g.ModuleFactory
  }
}

export interface LandmarkerSet {
  lm: Landmarkers
  delegates: { face: Delegate; hand: Delegate; pose: Delegate }
  close(): void
}

/**
 * @param moduleLoader true면 ES 모듈 wasm 로더(vision_wasm_module_internal.js)를 쓴다.
 *   모듈 워커에는 importScripts가 없어(TypeError) tasks-vision 로더가 동적 import()로 떨어지는데,
 *   이때는 module 빌드여야 한다. 메인 스레드는 classic <script> 로더를 그대로 쓴다.
 * @param warn GPU 델리게이트 실패 같은 경고 보고 (워커는 메인으로 중계)
 */
export async function createLandmarkers(
  urls: AssetUrls,
  moduleLoader: boolean,
  warn: (msg: string, err?: unknown) => void = (m, e) => console.warn(m, e),
): Promise<LandmarkerSet> {
  if (moduleLoader) installModuleLoaderHook()
  const fileset = await FilesetResolver.forVisionTasks(urls.wasmBase, moduleLoader)
  const made: { close(): void }[] = []
  const delegates = { face: 'GPU', hand: 'GPU', pose: 'GPU' } as LandmarkerSet['delegates']

  // GPU 우선, 실패 시 CPU 폴백 (초기화는 직렬 — GPU 컨텍스트 경합 회피)
  const gpuThenCpu = async <T extends { close(): void }>(
    name: 'face' | 'hand' | 'pose',
    make: (delegate: Delegate) => Promise<T>,
  ): Promise<T> => {
    let lm: T
    try {
      lm = await make('GPU')
    } catch (e) {
      warn(`[tracking] ${name} landmarker GPU 델리게이트 실패 → CPU 폴백`, e)
      delegates[name] = 'CPU'
      lm = await make('CPU')
    }
    made.push(lm)
    return lm
  }

  try {
    const face = await gpuThenCpu('face', (delegate) =>
      FaceLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: urls.face, delegate },
        runningMode: 'VIDEO',
        numFaces: 1,
        outputFaceBlendshapes: true,
        outputFacialTransformationMatrixes: true,
      }),
    )
    const hand = await gpuThenCpu('hand', (delegate) =>
      HandLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: urls.hand, delegate },
        runningMode: 'VIDEO',
        numHands: 2,
      }),
    )
    const pose = await gpuThenCpu('pose', (delegate) =>
      PoseLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: urls.pose, delegate },
        runningMode: 'VIDEO',
        numPoses: 1,
      }),
    )
    return {
      lm: { face, hand, pose },
      delegates,
      close: () => {
        for (const m of made) m.close()
      },
    }
  } catch (err) {
    for (const m of made) {
      try {
        m.close()
      } catch {
        /* 초기화 실패 정리 중 */
      }
    }
    throw err
  }
}
