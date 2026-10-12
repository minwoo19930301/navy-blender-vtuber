#!/usr/bin/env node
/**
 * 트래킹 파이프라인 스모크 테스트 (웹캠 없이)
 *
 * vite build → vite preview → Chrome headless + 가짜 카메라 장치로 index.html을 열고
 * getUserMedia → MediaPipe(WASM+.task 로드, GPU→CPU 폴백) → rVFC 루프가 도는지 확인한다.
 *
 *   npm run smoke                       가짜 장치(테스트 패턴) — 얼굴은 안 잡히지만 루프 fps > 0 이어야 함
 *   VIDEO=clip.mjpeg npm run smoke      영상 파일을 카메라로 주입 (Chrome: .y4m 또는 .mjpeg)
 *   QUERY=trackworker=0 npm run smoke   URL 쿼리를 덧붙임 (메인 스레드 폴백 경로 확인)
 *   DIST=/path/to/dist SKIP_BUILD=1 EXPECT_MODE=main npm run smoke
 *                                       다른 dist를 서빙 (워커 청크나 wasm/vision_wasm_module_internal.js를 지운 사본으로
 *                                       워커 로드/초기화 실패 → 메인 스레드 폴백 경로 확인)
 *   BASE_URL=http://localhost:5185 npm run smoke
 *                                       이미 떠 있는 서버(vite dev 등)를 대상으로 (빌드·preview 생략)
 *   FILE_URL=1 npm run smoke            http preview 대신 dist를 file://로 열고 Chrome에
 *                                       --allow-file-access-from-files 를 줌 (Electron의 file:// 로드 근사)
 *
 * 통과 조건: '[navy] tracking started' 로그, 페이지 예외 0, __mingoTracking.fps > 0,
 * 트래킹 모드가 기대값과 같음 (기본 'worker', QUERY에 trackworker=0이면 'main', EXPECT_MODE로 지정 가능).
 * 모드를 검사하는 이유: 워커가 조용히 메인 스레드 폴백으로 떨어져도 fps는 나오기 때문이다.
 * VIDEO를 주면 마지막 RigFrame 요약(얼굴 tracked, 팔 present 등)도 출력한다.
 */
import { spawn, execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { findChrome, VITE_BIN } from './lib/platform.mjs'

const PORT = Number(process.env.PORT ?? 5298)
const CDP_PORT = Number(process.env.CDP_PORT ?? 9498)
const WAIT_MS = Number(process.env.WAIT_MS ?? 15000)
const QUERY = process.env.QUERY ?? ''
const FILE_URL = process.env.FILE_URL === '1'
const BASE_URL = process.env.BASE_URL ?? ''
const EXPECT_MODE = process.env.EXPECT_MODE ?? (/(^|&)trackworker=0(&|$)/.test(QUERY) ? 'main' : 'worker')
const CHROME = findChrome()
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// SKIP_BUILD여도 dist가 하네스 전용 빌드(screenshot.mjs의 HARNESS_ONLY)면 index.html이 없다 → 빌드한다
const hasMain = existsSync(join(process.env.DIST ? resolve(process.env.DIST) : join(dirname(fileURLToPath(import.meta.url)), '../dist'), 'index.html'))
if (!BASE_URL && (!process.env.SKIP_BUILD || !hasMain)) execFileSync(process.execPath, [VITE_BIN, 'build'], { stdio: 'inherit' })

const distDir = process.env.DIST ? resolve(process.env.DIST) : join(dirname(fileURLToPath(import.meta.url)), '../dist')
const preview = FILE_URL || BASE_URL ? null : spawn(process.execPath, [VITE_BIN, 'preview', '--outDir', distDir, '--port', String(PORT), '--strictPort'], { stdio: 'pipe' })
if (preview) await new Promise((res, rej) => {
  const to = setTimeout(() => rej(new Error('vite preview timeout')), 15000)
  preview.stdout.on('data', (d) => {
    if (d.toString().includes(String(PORT))) { clearTimeout(to); setTimeout(res, 300) }
  })
  preview.on('exit', () => rej(new Error('vite preview exited early')))
})

const profile = mkdtempSync(join(tmpdir(), 'smiley-smoke-'))
const camArgs = ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']
if (process.env.VIDEO) camArgs.push(`--use-file-for-fake-video-capture=${resolve(process.env.VIDEO)}`)

let chrome = null
let ws = null
let failed = false
try {
  chrome = spawn(CHROME, [
    '--headless=new', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required',
    ...(FILE_URL ? ['--allow-file-access-from-files'] : []),
    `--remote-debugging-port=${CDP_PORT}`, '--window-size=560,680', `--user-data-dir=${profile}`,
    ...camArgs, 'about:blank',
  ], { stdio: 'ignore' })

  let wsUrl = null
  for (let i = 0; i < 50 && !wsUrl; i++) {
    await sleep(200)
    try {
      const tabs = await (await fetch(`http://localhost:${CDP_PORT}/json`)).json()
      wsUrl = tabs.find((t) => t.type === 'page')?.webSocketDebuggerUrl ?? null
    } catch { /* chrome 기동 중 */ }
  }
  if (!wsUrl) throw new Error('CDP endpoint not found')

  ws = new WebSocket(wsUrl)
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('CDP ws error')) })
  let id = 0
  const pending = new Map()
  const logs = []
  const errors = []
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data)
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
    if (msg.method === 'Runtime.consoleAPICalled') {
      logs.push(`[${msg.params.type}] ` + msg.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      errors.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text)
    }
  }
  const send = (method, params = {}) =>
    new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })
  const evaluate = async (expression) =>
    (await send('Runtime.evaluate', { expression, returnByValue: true })).result?.result?.value

  await send('Runtime.enable')
  await send('Page.enable')
  const base = BASE_URL ? `${BASE_URL}/index.html` : FILE_URL ? `file://${join(distDir, 'index.html')}` : `http://localhost:${PORT}/index.html`
  await send('Page.navigate', { url: `${base}?debug=1${QUERY ? '&' + QUERY : ''}` })

  const deadline = Date.now() + WAIT_MS
  let started = false
  while (Date.now() < deadline) {
    await sleep(500)
    if (logs.some((l) => l.includes('[navy] tracking started'))) { started = true; break }
    if (logs.some((l) => l.includes('idle mode'))) break
  }
  await sleep(3000) // 루프 fps 측정 여유

  // 영상 주입 시: 원본 RigFrame을 시간축으로 샘플링 (video.currentTime ≈ 파일 재생 위치, 루프됨)
  const samples = []
  if (process.env.VIDEO && started) {
    const sampleMs = Number(process.env.SAMPLE_S ?? 20) * 1000
    const until = Date.now() + sampleMs
    while (Date.now() < until) {
      const s = await evaluate(`(() => {
        const f = window.__navyRaw; const v = document.getElementById('cam')
        if (!f) return null
        const d = (a) => [a.x, a.y, a.z].map((x) => +x.toFixed(2))
        const arm = (a) => ({ p: +a.present.toFixed(2), up: d(a.upperDir), lo: d(a.lowerDir), hd: d(a.handDir), pn: d(a.palmNormal), fi: a.fingers.map((x) => +x.toFixed(2)) })
        return { vt: +(v?.currentTime ?? 0).toFixed(2), tr: +f.tracked.toFixed(2), yaw: +f.head.yaw.toFixed(2), pitch: +f.head.pitch.toFixed(2),
          roll: +f.head.roll.toFixed(2), mo: +f.mouthOpen.toFixed(2), bl: +f.blinkL.toFixed(2), br: +f.blinkR.toFixed(2),
          body: +f.body.present.toFixed(2), L: arm(f.armL), R: arm(f.armR) }
      })()`)
      if (s) samples.push(s)
      await sleep(250)
    }
  }
  const fps = await evaluate('window.__mingoTracking?.fps ?? 0')
  const mode = await evaluate('window.__mingoTracking?.mode ?? null')
  const delegates = await evaluate('JSON.stringify(window.__mingoTracking?.delegates ?? null)')
  const cost = await evaluate('JSON.stringify(window.__mingoTracking?.costMs ?? null)')
  const dbg = await evaluate('document.getElementById("debug")?.textContent ?? ""')

  console.log('--- console ---')
  for (const l of logs) console.log(l)
  if (errors.length) {
    console.log('--- page exceptions ---')
    for (const e of errors) console.log(e)
  }
  console.log('--- debug overlay ---')
  console.log(dbg)
  if (samples.length) {
    console.log('--- samples (vt=영상 시각) ---')
    for (const s of samples) console.log(JSON.stringify(s))
    if (process.env.SAMPLES_OUT) writeFileSync(process.env.SAMPLES_OUT, JSON.stringify(samples, null, 1))
  }
  console.log('--- result ---')
  console.log(`tracking started: ${started}, mode: ${mode} (expect ${EXPECT_MODE}), loop fps: ${fps}, exceptions: ${errors.length}`)
  console.log(`delegates: ${delegates}, costMs: ${cost}`)
  failed = !started || !(fps > 0) || errors.length > 0 || mode !== EXPECT_MODE
} finally {
  try { ws?.close() } catch { /* noop */ }
  chrome?.kill('SIGTERM')
  preview?.kill('SIGTERM')
  try { rmSync(profile, { recursive: true, force: true }) } catch { /* noop */ }
}
console.log(failed ? 'SMOKE FAIL' : 'SMOKE OK')
process.exit(failed ? 1 : 0)
