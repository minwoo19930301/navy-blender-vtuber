/**
 * 하네스 포즈 프리셋 — 트래킹 없이 RigFrame을 직접 만들어 모델을 검증한다.
 *
 * 좌표계는 계약과 같다: x=캐릭터 왼쪽+(화면에서 뷰어 오른쪽), y=위+, z=앞(카메라)+.
 * armL = 캐릭터 왼팔 = 화면 오른쪽에 보이는 팔.
 */
import { neutralFrame, neutralArm, neutralMotion, type ArmPose, type Dir3, type RigFrame } from '../contract'

const n = (x: number, y: number, z: number): Dir3 => {
  const l = Math.hypot(x, y, z) || 1
  return { x: x / l, y: y / l, z: z / l }
}

type Fingers = ArmPose['fingers']
const OPEN: Fingers = [0, 0, 0, 0, 0]
const FIST: Fingers = [1, 1, 1, 1, 1]

/** side: +1 = 캐릭터 왼팔(armL), -1 = 오른팔(armR). x 성분은 side를 곱해 대칭 작성 */
function arm(
  side: 1 | -1,
  upper: [number, number, number],
  lower: [number, number, number],
  handDir: [number, number, number],
  palm: [number, number, number],
  fingers: Fingers,
  spread = 0.3,
): ArmPose {
  return {
    present: 1,
    upperDir: n(side * upper[0], upper[1], upper[2]),
    lowerDir: n(side * lower[0], lower[1], lower[2]),
    handDir: n(side * handDir[0], handDir[1], handDir[2]),
    palmNormal: n(side * palm[0], palm[1], palm[2]),
    fingers: [...fingers] as Fingers,
    spread,
    wave: 0,
  }
}

const idleArm = (side: 1 | -1): ArmPose => ({ ...neutralArm(side), present: 1 })

export type PresetName =
  | 'idle' | 'tpose' | 'wave' | 'armsUp' | 'forward' | 'fist' | 'point' | 'vsign' | 'thumbsup'
  | 'heart' | 'cheeks' | 'mouth' | 'talk' | 'blink' | 'winkL' | 'happy' | 'frown'
  | 'yawL' | 'yawR' | 'pitchUp' | 'pitchDown' | 'roll' | 'lean' | 'twist' | 'shrug'

export const PRESETS: Readonly<Record<PresetName, () => RigFrame>> = {
  idle: () => neutralFrame(),

  // 양팔 수평 — 손바닥 아래, 손가락 펴짐
  tpose: () => ({
    ...neutralFrame(),
    armL: arm(1, [1, 0, 0], [1, 0, 0], [1, 0, 0], [0, -1, 0], OPEN, 0.4),
    armR: arm(-1, [1, 0, 0], [1, 0, 0], [1, 0, 0], [0, -1, 0], OPEN, 0.4),
  }),

  // 캐릭터 왼팔(화면 오른쪽)로 손 흔들기 — 상완 옆, 전완 위, 손바닥 카메라향
  wave: () => ({
    ...neutralFrame(),
    mouthSmile: 0.6,
    armL: arm(1, [0.92, -0.25, 0.25], [0.15, 0.98, 0.1], [0.1, 0.99, 0.05], [0, 0, 1], OPEN, 0.8),
    armR: idleArm(-1),
  }),

  // 만세
  armsUp: () => ({
    ...neutralFrame(),
    mouthOpen: 0.5,
    mouthSmile: 0.8,
    armL: arm(1, [0.35, 0.94, 0], [0.25, 0.97, 0], [0.2, 0.98, 0], [0, 0, 1], OPEN, 0.7),
    armR: arm(-1, [0.35, 0.94, 0], [0.25, 0.97, 0], [0.2, 0.98, 0], [0, 0, 1], OPEN, 0.7),
  }),

  // 앞으로 나란히 — 손바닥 마주봄
  forward: () => ({
    ...neutralFrame(),
    armL: arm(1, [0.12, -0.05, 0.99], [0.05, 0, 1], [0.05, 0, 1], [-1, 0, 0], OPEN, 0.2),
    armR: arm(-1, [0.12, -0.05, 0.99], [0.05, 0, 1], [0.05, 0, 1], [-1, 0, 0], OPEN, 0.2),
  }),

  // 가슴 앞 주먹 쥐기 — 두 주먹이 가슴 높이(배지 옆, 목 칼라 아래)에서 따로 떨어져 보인다.
  // 초판은 전완이 위로 향해(y 0.55) 주먹이 어깨·칼라 높이에 붙었다. 이 몸통은 어깨(0.245)와 칼라(0.33)가 가까워, 전완을 거의 수평(y 0.15)으로 앞에 뻗어야 가슴에 온다.
  fist: () => ({
    ...neutralFrame(),
    mouthSmile: -0.2,
    browL: -0.6,
    browR: -0.6,
    armL: arm(1, [0.5, -0.8, 0.3], [-0.1, 0.15, 0.98], [0, 0.55, 0.83], [-0.6, -0.5, 0.6], FIST, 0.1),
    armR: arm(-1, [0.5, -0.8, 0.3], [-0.1, 0.15, 0.98], [0, 0.55, 0.83], [-0.6, -0.5, 0.6], FIST, 0.1),
  }),

  // 캐릭터 왼팔로 옆 대각선 가리키기 (검지만 펴기). 정면 카메라에서 검지가 보이게 옆으로 뻗는다
  point: () => ({
    ...neutralFrame(),
    armL: arm(1, [0.85, 0.1, 0.5], [0.88, 0.15, 0.45], [0.88, 0.15, 0.45], [0, -1, 0], [0.8, 0, 1, 1, 1], 0.1),
    armR: idleArm(-1),
  }),

  // 얼굴 옆 V 사인 (캐릭터 왼손)
  vsign: () => ({
    ...neutralFrame(),
    mouthSmile: 0.9,
    fx: { heart: false, happy: true, sweat: false, anger: false },
    armL: arm(1, [0.6, -0.55, 0.58], [-0.15, 0.95, 0.28], [-0.05, 0.99, 0.1], [0, 0, 1], [0.9, 0, 0, 1, 1], 0.7),
    armR: idleArm(-1),
  }),

  // 엄지 척 (캐릭터 오른손) — 주먹이 앞을 향하고 손바닥이 몸 안쪽
  thumbsup: () => ({
    ...neutralFrame(),
    mouthSmile: 0.7,
    armL: idleArm(1),
    armR: arm(-1, [0.3, -0.85, 0.45], [0.05, 0.15, 0.99], [0.05, 0.15, 0.99], [-1, 0, 0], [0, 1, 1, 1, 1], 0.1),
  }),

  // 가슴 앞 양손 하트 — 손바닥이 카메라를 향하고 손끝이 아래 가운데에서 만나는 V 자. 손목(소매)이 위쪽 두 둥근 봉우리, 가운데 위에 홈, 아래는 뾰족한 하트 실루엣이 된다.
  // 초판은 전완이 위로 향해(y 0.45) 두 손이 턱·칼라에 뭉쳤다 — 위를 향한 전완은 이 몸이 낮출 수 없다(손끝이 칼라 밑까지 오름). 전완을 앞쪽 위로 두고 손목만 아래·안쪽으로 꺾는다(굽힘 ≈ 88°, 클램프 90° 이내).
  heart: () => ({
    ...neutralFrame(),
    mouthSmile: 0.9,
    fx: { heart: true, happy: false, sweat: false, anger: false },
    armL: arm(1, [0.15, -0.8, 0.58], [-0.4, 0.5, 0.77], [-0.5, -0.8, 0.3], [0, 0.3, 1], [0.25, 0.12, 0.12, 0.12, 0.12], 0),
    armR: arm(-1, [0.15, -0.8, 0.58], [-0.4, 0.5, 0.77], [-0.5, -0.8, 0.3], [0, 0.3, 1], [0.25, 0.12, 0.12, 0.12, 0.12], 0),
  }),

  // 양손으로 볼 감싸기 — 손이 볼 높이(머리 중심 근처)의 얼굴 옆 가장자리에 손바닥을 대고 팔꿈치는 옆으로 벌린다.
  // 초판은 윗팔이 아래로 내려가(y -0.8) 팔 길이를 다 써서 손이 턱 아래에 닿았다. 팔꿈치를 어깨 높이로 올려야 손이 볼에 간다.
  cheeks: () => ({
    ...neutralFrame(),
    mouthOpen: 0.25,
    mouthSmile: 0.8,
    armL: arm(1, [0.6, 0.3, 0.5], [-0.3, 0.85, 0.4], [-0.3, 0.93, 0.2], [-0.9, 0, 0.35], OPEN, 0.2),
    armR: arm(-1, [0.6, 0.3, 0.5], [-0.3, 0.85, 0.4], [-0.3, 0.93, 0.2], [-0.9, 0, 0.35], OPEN, 0.2),
  }),

  mouth: () => ({ ...neutralFrame(), mouthOpen: 1, mouthSmile: 0.3 }),
  talk: () => ({ ...neutralFrame(), mouthOpen: 0.45, mouthSmile: 0.2 }),
  blink: () => ({ ...neutralFrame(), blinkL: 1, blinkR: 1 }),
  winkL: () => ({ ...neutralFrame(), blinkL: 1, blinkR: 0, mouthSmile: 0.8 }),
  happy: () => ({ ...neutralFrame(), mouthSmile: 1, mouthOpen: 0.3, fx: { heart: false, happy: true, sweat: false, anger: false } }),
  frown: () => ({ ...neutralFrame(), mouthSmile: -0.8, browL: -0.8, browR: -0.8 }),

  yawL: () => ({ ...neutralFrame(), head: { pitch: 0, yaw: 0.6, roll: 0 } }),
  yawR: () => ({ ...neutralFrame(), head: { pitch: 0, yaw: -0.6, roll: 0 } }),
  pitchUp: () => ({ ...neutralFrame(), head: { pitch: 0.45, yaw: 0, roll: 0 } }),
  pitchDown: () => ({ ...neutralFrame(), head: { pitch: -0.45, yaw: 0, roll: 0 } }),
  roll: () => ({ ...neutralFrame(), head: { pitch: 0, yaw: 0, roll: 0.4 } }),
  lean: () => {
    const f = neutralFrame()
    f.body = { ...f.body, present: 1, lean: { x: 0.25, z: 0.15 } }
    return f
  },
  twist: () => {
    const f = neutralFrame()
    f.body = { ...f.body, present: 1, twist: 0.45 }
    return f
  },
  shrug: () => {
    const f = neutralFrame()
    f.body = { ...f.body, present: 1, shrugL: 1, shrugR: 1 }
    f.mouthSmile = -0.3
    return f
  },
}

export const PRESET_NAMES = Object.keys(PRESETS) as PresetName[]

export function isPreset(v: string | null): v is PresetName {
  return v != null && Object.prototype.hasOwnProperty.call(PRESETS, v)
}

/** 쿼리 파라미터로 프리셋 위 개별 채널 덮어쓰기 (yaw=0.3&mouth=1 …) */
export function applyOverrides(f: RigFrame, q: URLSearchParams): RigFrame {
  const num = (k: string): number | null => {
    const v = q.get(k)
    if (v == null || v === '') return null
    const x = Number(v)
    return Number.isFinite(x) ? x : null
  }
  const set = (k: string, fn: (v: number) => void) => {
    const v = num(k)
    if (v != null) fn(v)
  }
  set('yaw', (v) => { f.head.yaw = v })
  set('pitch', (v) => { f.head.pitch = v })
  set('roll', (v) => { f.head.roll = v })
  set('blink', (v) => { f.blinkL = v; f.blinkR = v })
  set('blinkL', (v) => { f.blinkL = v })
  set('blinkR', (v) => { f.blinkR = v })
  set('mouth', (v) => { f.mouthOpen = v })
  set('smile', (v) => { f.mouthSmile = v })
  set('gx', (v) => { f.gaze.x = v })
  set('gy', (v) => { f.gaze.y = v })
  set('brow', (v) => { f.browL = v; f.browR = v })
  set('leanX', (v) => { f.body.lean.x = v; f.body.present = 1 })
  set('leanZ', (v) => { f.body.lean.z = v; f.body.present = 1 })
  set('twist', (v) => { f.body.twist = v; f.body.present = 1 })
  set('shrug', (v) => { f.body.shrugL = v; f.body.shrugR = v; f.body.present = 1 })
  set('breath', (v) => { f.breath = v })
  // 리액션 표정·몸 움직임 단독 검증용 (kiss=1&teary=1&blush=0.8&bounce=0.3&squash=-0.2&spin=3.14 …)
  const flag = (k: 'kiss' | 'teary' | 'surprised' | 'sleepy' | 'angry' | 'happy' | 'heart') => set(k, (v) => { f.fx[k] = v >= 0.5 })
  flag('kiss'); flag('teary'); flag('surprised'); flag('sleepy'); flag('angry'); flag('happy'); flag('heart')
  set('blush', (v) => { f.fx.blush = v })
  set('tear', (v) => { f.fx.tear = v })
  const motion = (fn: (m: NonNullable<RigFrame['motion']>, v: number) => void) => (v: number) => {
    if (!f.motion) f.motion = neutralMotion()
    fn(f.motion, v)
  }
  set('bounce', motion((m, v) => { m.bounce = v }))
  set('squash', motion((m, v) => { m.squash = v }))
  set('spin', motion((m, v) => { m.spin = v }))
  set('push', motion((m, v) => { m.push = v }))
  set('shiftX', motion((m, v) => { m.shiftX = v }))
  return f
}
