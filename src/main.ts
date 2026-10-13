import * as THREE from 'three'
import { createNavy, applyEnvironment } from './model/index'
import { createTracker } from './tracking/index'
import { createCameraSession } from './camera'
import { createAliveness } from './aliveness/index'
import { createReactions } from './reactions/index'
import { prewarmShaders } from './reactions/warm'
import { neutralFrame, type CursorInfo, type RigFrame } from './contract'
import { reflectArms, reflectFrame } from './frameOps'

const canvas = document.getElementById('stage') as HTMLCanvasElement
const video = document.getElementById('cam') as HTMLVideoElement
const debugEl = document.getElementById('debug') as HTMLDivElement
const toastEl = document.getElementById('toast') as HTMLDivElement

declare global {
  interface Window {
    /** 디버그 모드에서 최신 트래킹 원본 프레임 (스모크/E2E 테스트가 읽는다) */
    __navyRaw?: RigFrame
  }
}

/* ---------------- 뷰어 설정 (로컬에만 저장) ---------------- */

type BgMode = 'transparent' | 'green' | 'solid'
type MirrorMode = 'none' | 'arms' | 'full'
const BG_MODES: readonly BgMode[] = ['transparent', 'green', 'solid']
const MIRROR_MODES: readonly MirrorMode[] = ['none', 'arms', 'full']
const BG_LABEL: Record<BgMode, string> = { transparent: '배경: 투명', green: '배경: 크로마키 그린', solid: '배경: 단색' }
const MIRROR_LABEL: Record<MirrorMode, string> = {
  none: '좌우: 기본 (거울)',
  arms: '좌우: 팔만 반전',
  full: '좌우: 전체 반전 (인형 모드)',
}

function loadSetting<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v && (allowed as readonly string[]).includes(v) ? (v as T) : fallback
  } catch {
    return fallback
  }
}
function saveSetting(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* 저장소 차단 환경 — 무시 */ }
}

const query = new URLSearchParams(location.search)
let bgMode: BgMode = loadSetting('navy-bg', BG_MODES, 'transparent')
let mirrorMode: MirrorMode = loadSetting('navy-mirror', MIRROR_MODES, 'none')
let debugOn = query.get('debug') === '1'
/** nocam=1: 카메라를 열지 않는다 (Electron 셸 스모크, 데모 녹화 등) */
const noCam = query.get('nocam') === '1'
if (query.get('bg') && (BG_MODES as readonly string[]).includes(query.get('bg')!)) bgMode = query.get('bg') as BgMode

let toastTimer = 0
function toast(msg: string, ms = 1400) {
  toastEl.textContent = msg
  toastEl.classList.add('show')
  clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => toastEl.classList.remove('show'), ms)
}

function applyBg() {
  document.body.classList.toggle('bg-green', bgMode === 'green')
  document.body.classList.toggle('bg-solid', bgMode === 'solid')
}
applyBg()
document.body.classList.toggle('debug', debugOn)

function cycleBg() {
  bgMode = BG_MODES[(BG_MODES.indexOf(bgMode) + 1) % BG_MODES.length]
  saveSetting('navy-bg', bgMode)
  applyBg()
  toast(BG_LABEL[bgMode])
}
function cycleMirror() {
  mirrorMode = MIRROR_MODES[(MIRROR_MODES.indexOf(mirrorMode) + 1) % MIRROR_MODES.length]
  saveSetting('navy-mirror', mirrorMode)
  toast(MIRROR_LABEL[mirrorMode])
}
function toggleDebug() {
  debugOn = !debugOn
  document.body.classList.toggle('debug', debugOn)
  toast(debugOn ? '디버그 오버레이 켬' : '디버그 오버레이 끔')
}

/* ---------------- 렌더러 ---------------- */

const renderer = new THREE.WebGLRenderer({
  canvas,
  alpha: true,
  antialias: true,
  premultipliedAlpha: true,
  powerPreference: 'low-power',
})
renderer.setClearColor(0x000000, 0) // 완전 투명 배경 (배경색은 body CSS가 담당)
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))

const scene = new THREE.Scene()
const renderStats = { frames: 0, triangles: 0, drawCalls: 0, frameErrors: 0 }
;(window as any).__navyPerformance = renderStats

// 좁은 FOV(준직교) — 2D 일러처럼 읽히게 원근 왜곡을 줄인다
const camera = new THREE.PerspectiveCamera(17, 1, 0.1, 100)

// 환경광·톤매핑은 하네스와 같게 model/index.ts 한 곳에서 건다
applyEnvironment(renderer, scene)
const avatar = createNavy()
scene.add(avatar.root)
// 숫자키 리액션: 트래킹 → 미러 → aliveness → 리액션 → 모델. FX(하트·꽃·색종이 …)는 씬에 따로 얹는다
const reactions = createReactions()
reactions.fxRoot.scale.setScalar(.8)
reactions.fxRoot.position.y=.98
scene.add(reactions.fxRoot)


/** 아바타 줌 (1 = 기본, 클수록 멀리 = 더 작게) */
let avatarZoom = 1.0
function setAvatarZoom(z: number) {
  avatarZoom = Math.min(1.8, Math.max(0.85, z))
  frameCamera()
}

/** 책상 윗면 높이와 앞 모서리 z (props.glb 의 desk). 화면 아래 가장자리를 여기에 맞춘다 */
const DESK_Y = 0.28, DESK_FRONT_Z = 1.5

function frameCamera() {
  const w = Math.max(1, window.innerWidth)
  const h = Math.max(1, window.innerHeight)
  renderer.setSize(w, h, true)
  camera.aspect = w / h
  const bodyH = Math.max(0.5, avatar.height || 1.0)
  const fitH = bodyH * 1.16 * avatarZoom
  const fitW = bodyH * 1.12 * avatarZoom
  const halfFov = THREE.MathUtils.degToRad(camera.fov / 2)
  const distH = fitH / 2 / Math.tan(halfFov)
  const distW = fitW / 2 / (Math.tan(halfFov) * camera.aspect)
  const dist = Math.max(distH, distW)
  // 화면 아래 가장자리를 책상(투명 가림판) 앞 모서리에 맞춘다: 몸이 잘린 선이 창 밖으로 나가서 '책상 줄'이 안 보인다.
  // 가림판 앞 모서리(y=DESK_Y, z=DESK_FRONT_Z)가 화면 맨 아래에 오도록 바라보는 높이를 정한다 (src/reactions/props.ts, blender/props_export.py)
  const lookY = DESK_Y + (dist - DESK_FRONT_Z) * Math.tan(halfFov)
  camera.position.set(0, lookY, dist)
  camera.lookAt(0, lookY, 0)
  camera.far = Math.max(100, dist * 10)
  camera.updateProjectionMatrix()
}
frameCamera()
window.addEventListener('resize', frameCamera)
// 모델이 준비되면 소품·FX 셰이더를 미리 컴파일해 둔다 (처음 누른 키의 팝 등장 한가운데서 컴파일이 돌아 프레임이 끊기는 걸 막는다)
;(avatar.ready ?? Promise.resolve()).then(() => {
  frameCamera()
  prewarmShaders(renderer, scene, camera).catch(() => {})
})

function handleCommand(cmd: string) {
  if (cmd === 'avatar-smaller') setAvatarZoom(avatarZoom + 0.1)
  else if (cmd === 'avatar-larger') setAvatarZoom(avatarZoom - 0.1)
  else if (cmd === 'avatar-reset') setAvatarZoom(1)
  else if (cmd === 'bg-cycle') cycleBg()
  else if (cmd === 'mirror-toggle') cycleMirror()
  else if (cmd === 'debug-toggle') toggleDebug()
  else if (cmd === 'quit') window.mingo?.quit()
  else if (cmd === 'reaction-cancel') reactions.cancel(elapsed)
  else if (cmd === 'camera-toggle') toggleCamera()
  else if (cmd.startsWith('reaction-')) reactions.trigger(Number(cmd.slice('reaction-'.length)), elapsed)
}
window.mingo?.onDebugCommand?.(handleCommand)

/** 숫자키 1~9 → 리액션 1~9, 0 → 리액션 10(일하는 척) (자판 배열과 무관하게 e.code 로 읽고, 없으면 e.key). 숫자키가 아니면 0 */
function reactionKey(e: KeyboardEvent): number {
  const m = /^(?:Digit|Numpad)([0-9])$/.exec(e.code)
  const d = m ? m[1] : /^[0-9]$/.test(e.key) ? e.key : ''
  if (d === '') return 0
  return d === '0' ? 10 : Number(d)
}

// 브라우저 실행(npm run web / OBS 브라우저 소스)용 단축키 — Electron에서는 메뉴·전역 단축키가 담당 (창에 포커스가 있을 때는 숫자키도 바로 먹는다)
window.addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const rk = reactionKey(e)
  if (rk > 0) {
    if (!e.repeat) handleCommand(`reaction-${rk}`) // 꾹 눌러도 한 번만 (반복 입력이 리액션을 계속 처음으로 되돌리지 않게)
    return
  }
  if (e.key === 'Escape') {
    handleCommand('reaction-cancel')
    return
  }
  const k = e.key.toLowerCase()
  if (k === 'b') handleCommand('bg-cycle')
  else if (k === 'x') handleCommand('mirror-toggle')
  else if (k === 'd') handleCommand('debug-toggle')
  else if (k === '-') handleCommand('avatar-smaller')
  else if (k === '=' || k === '+') handleCommand('avatar-larger')
  else if (k === 'r') handleCommand('avatar-reset')
})

/* ---------------- 트래킹 + 생명감 ---------------- */

const aliveness = createAliveness()
let trackingUp = false
let camError = ''
let cameraEnabled = !noCam
let cameraVisible = true
const cameraButton = document.getElementById('camera-toggle') as HTMLButtonElement
const cameraSession = createCameraSession({
  video, createTracker,
  getUserMedia: () => navigator.mediaDevices.getUserMedia({video:{width:640,height:480,frameRate:30},audio:false}),
  onState(state,error) {
    trackingUp = state === 'tracking'
    camError = error ? (error instanceof Error ? error.message : String(error)) : ''
    cameraButton.textContent = state==='starting' ? '연결 중…' : state==='tracking' ? '카메라 끄기' : state==='error' ? '다시 연결' : '카메라 켜기'
    if(state==='tracking') console.log('[navy] tracking started')
    if(state==='error') toast('카메라 연결을 확인하고 메뉴의 카메라 켜기/끄기(⌘⇧C)로 다시 연결해 주세요. '+camError,6000)
  },
})
function toggleCamera() {
  cameraEnabled = camError ? true : !cameraEnabled
  cameraSession.setActive(cameraEnabled && cameraVisible)
  toast(cameraEnabled ? '카메라 켜는 중…' : '카메라 껐어요 (⌘⇧C 로 다시 켜기)', 1800)
}
cameraButton.addEventListener('click', toggleCamera)
cameraButton.addEventListener('pointerdown',e=>e.stopPropagation())
cameraButton.addEventListener('mousedown',e=>e.stopPropagation())
cameraSession.setActive(cameraEnabled)

/* ---------------- 커서(전역) → 시선 + 히트테스트 + 드래그 ---------------- */

let cursor: CursorInfo | null = null
let cursorInWindow = false
let cursorWin = { x: 0, y: 0 }
let clickThrough = true
const clampUnit = (v: number) => Math.max(-1, Math.min(1, v))

const raycaster = new THREE.Raycaster()
const hitNdc = new THREE.Vector2()
let lastHitWx = Number.NaN
let lastHitWy = Number.NaN
let dragging = false
let lastDrag = { x: 0, y: 0 }

function setClickThrough(v: boolean) {
  if (!window.mingo || v === clickThrough) return
  clickThrough = v
  window.mingo.setClickThrough(v)
}

/** 아바타 픽셀 위에서만 클릭 받기 (레이캐스트). onCursor에서만 실행 (≤30Hz) */
function updateHitTest() {
  if (!window.mingo) return
  // 드래그 중엔 클릭스루 OFF 유지 — 레이캐스트 한 번 빗나가면 mouseup을 잃는다
  if (dragging) {
    setClickThrough(false)
    return
  }
  let hit = false
  if (cursorInWindow && avatar.hitMeshes.length > 0) {
    const iw = Math.max(1, window.innerWidth)
    const ih = Math.max(1, window.innerHeight)
    hitNdc.set((cursorWin.x / iw) * 2 - 1, -(cursorWin.y / ih) * 2 + 1)
    raycaster.setFromCamera(hitNdc, camera)
    // hitMeshes는 평평한 목록이다. 재귀로 돌면 외곽선 hull 자식까지 두 번 검사한다
    const b = cameraButton.getBoundingClientRect()
    hit = (cursorWin.x >= b.left && cursorWin.x <= b.right && cursorWin.y >= b.top && cursorWin.y <= b.bottom) || raycaster.intersectObjects(avatar.hitMeshes, false).length > 0
  }
  setClickThrough(!hit)
}

window.mingo?.onCursor((p) => {
  // 계약(CursorInfo): 윈도 중심 기준 오프셋을 화면 반폭/반높이로 정규화
  const dx = p.wx - p.winW / 2
  const dy = p.wy - p.winH / 2
  cursor = { nx: clampUnit(dx / (p.screenW / 2)), ny: clampUnit(dy / (p.screenH / 2)) }
  cursorInWindow = p.inWindow
  cursorWin = { x: p.wx, y: p.wy }
  if (p.wx !== lastHitWx || p.wy !== lastHitWy) {
    lastHitWx = p.wx
    lastHitWy = p.wy
    updateHitTest()
  }
})

// 브라우저 실행 시 창 안 마우스로 시선 대체
window.addEventListener('pointermove', (e) => {
  if (window.mingo) return
  cursor = {
    nx: clampUnit((e.clientX / Math.max(1, window.innerWidth)) * 2 - 1),
    ny: clampUnit((e.clientY / Math.max(1, window.innerHeight)) * 2 - 1),
  }
})

window.addEventListener('contextmenu', (e) => {
  e.preventDefault()
  window.mingo?.showAvatarMenu?.('avatar')
})

window.addEventListener('mousedown', (e) => {
  if (e.button !== 0 || !window.mingo) return
  dragging = true
  lastDrag = { x: e.screenX, y: e.screenY }
  setClickThrough(false)
})
window.addEventListener('mousemove', (e) => {
  if (!dragging) return
  if (e.buttons === 0) {
    dragging = false
    return
  }
  window.mingo?.dragBy(e.screenX - lastDrag.x, e.screenY - lastDrag.y)
  lastDrag = { x: e.screenX, y: e.screenY }
})
window.addEventListener('mouseup', () => { dragging = false })
window.addEventListener('blur', () => { dragging = false })

/* ---------------- 디버그 오버레이 ---------------- */

const f2 = (v: number) => (v >= 0 ? ' ' : '') + v.toFixed(2)
const d3 = (d: { x: number; y: number; z: number }) => `(${f2(d.x)},${f2(d.y)},${f2(d.z)})`
let lastDebugMs = 0
function updateDebug(raw: RigFrame, out: RigFrame, nowMs: number) {
  if (!debugOn || nowMs - lastDebugMs < 200) return
  lastDebugMs = nowMs
  const fps = window.__mingoTracking?.fps ?? 0
  const arm = (name: string, a: RigFrame['armL']) =>
    `${name} present ${a.present.toFixed(2)}\n  upper ${d3(a.upperDir)}\n  lower ${d3(a.lowerDir)}\n` +
    `  fingers ${a.fingers.map((v) => v.toFixed(1)).join(' ')}`
  debugEl.textContent =
    `cam ${trackingUp ? 'ON' : camError ? 'ERR ' + camError.slice(0, 32) : '…'}  fps ${fps}\n` +
    `${MIRROR_LABEL[mirrorMode]}\n` +
    `face ${raw.tracked.toFixed(2)}  yaw ${f2(raw.head.yaw)} pitch ${f2(raw.head.pitch)} roll ${f2(raw.head.roll)}\n` +
    `blink L${raw.blinkL.toFixed(2)} R${raw.blinkR.toFixed(2)}  mouth ${raw.mouthOpen.toFixed(2)} smile ${f2(raw.mouthSmile)}\n` +
    `body ${raw.body.present.toFixed(2)} lean ${f2(raw.body.lean.x)},${f2(raw.body.lean.z)} twist ${f2(raw.body.twist)}  reaction ${reactions.active() ?? '-'}\n` +
    `${arm('캐릭터 왼팔 (화면 오른쪽)', out.armL)}\n${arm('캐릭터 오른팔 (화면 왼쪽)', out.armR)}`
}

/* ---------------- 메인 루프 ---------------- */
// rAF는 ProMotion 120Hz를 따르므로 시간 게이트로 캡: idle 30fps, 트래킹 중 60fps
const IDLE_FRAME_MS = 1000 / 30
const TRACKED_FRAME_MS = 1000 / 60
let rafId = 0
let lastFrameMs = 0
let elapsed = 0
let lastRenderMs = 0
let lastTracked = 0
let loopErrors = 0

function loop() {
  rafId = requestAnimationFrame(loop)
  const nowMs = performance.now()
  // 리액션(점프·떨림·FX)이 도는 동안은 idle 이어도 60fps — 30fps 로는 떨림과 착지가 뚝뚝 끊긴다
  const targetMs = lastTracked > 0.5 || reactions.busy() ? TRACKED_FRAME_MS : IDLE_FRAME_MS
  if (nowMs - lastRenderMs < targetMs - 1) return
  lastRenderMs = nowMs

  const dt = lastFrameMs > 0 ? Math.min((nowMs - lastFrameMs) / 1000, 0.1) : 1 / 30
  lastFrameMs = nowMs
  elapsed += dt
  const t = elapsed

  try {
    const raw = cameraSession.latest() ?? neutralFrame()
    const oriented = mirrorMode === 'full' ? reflectFrame(raw) : mirrorMode === 'arms' ? reflectArms(raw) : raw
    const frame = reactions.compose(aliveness.compose(oriented, dt, t, cursor), dt, t)
    lastTracked = frame.tracked
    avatar.apply(frame, dt, t)
    renderer.render(scene, camera)
    renderStats.frames++; renderStats.triangles=renderer.info.render.triangles; renderStats.drawCalls=renderer.info.render.calls; renderStats.frameErrors=loopErrors
    updateDebug(raw, frame, nowMs)
    if (debugOn) window.__navyRaw = raw
  } catch (err) {
    // 한 프레임의 예외가 매 프레임 반복돼 아바타가 굳지 않게: 기록만 하고 다음 프레임에 다시 시도
    loopErrors++
    if (loopErrors <= 3) console.error('[navy] frame error', err)
  }
}
loop()

/* ---------------- 가시성 연동 (Cmd/Ctrl+Shift+M 퀵 하이드) ---------------- */
// hide 시 렌더 루프 + 트래커 + 카메라 LED까지 전부 멈추고, show 시 재시작
let pipelinePaused = false
function setPipelineVisible(visible: boolean) {
  if (visible === !pipelinePaused) return
  if (!visible) {
    pipelinePaused = true
    cancelAnimationFrame(rafId)
    cameraVisible = false
    cameraSession.setActive(false)
  } else {
    pipelinePaused = false
    cameraVisible = true
    cameraSession.setActive(cameraEnabled)
    lastFrameMs = 0 // 숨김 기간 델타 플러시 (복귀 프레임 점프 방지)
    cancelAnimationFrame(rafId)
    loop()
  }
}
window.mingo?.onVisibility?.((visible) => setPipelineVisible(visible))
document.addEventListener('visibilitychange', () => setPipelineVisible(!document.hidden))
