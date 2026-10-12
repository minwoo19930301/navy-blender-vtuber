#!/usr/bin/env node
/**
 * 트래킹 메인 스레드 비용 벤치 (headless Chrome + 가짜 카메라)
 *
 *   npm run build && node scripts/bench-tracking.mjs
 *   QUERY=trackworker=0 node scripts/bench-tracking.mjs        인스레드(워커 이전 전과 같은 구조)
 *   QUERY=nocam=1 node scripts/bench-tracking.mjs              트래킹 없이 렌더만 (메인 스레드 바닥값)
 *   DIST=/path/to/dist VIDEO=clip.y4m node scripts/bench-tracking.mjs
 *
 * 측정(모두 메인 스레드 기준, 워밍업 후 MEASURE_S초):
 *   busy%      CDP Performance.TaskDuration 증가분 / 경과 시간 — 렌더+트래킹을 합친 메인 스레드 점유율
 *   rVFC       requestVideoFrameCallback 콜백 본문 소요(ms) — 인스레드면 detect 전체, 워커면 비트맵 생성·전송 호출뿐
 *   longtask   50ms 이상 걸린 메인 스레드 태스크 수
 *   tracking   __mingoTracking의 mode / fps / costMs / everyFrame
 * headless+SwiftShader(소프트웨어 GL) 수치라 실기기 GPU 값과 절대치는 다르다 — 같은 조건끼리의 차이를 본다.
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { findChrome, VITE_BIN } from './lib/platform.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')
const PORT = Number(process.env.PORT ?? 5299)
const CDP_PORT = Number(process.env.CDP_PORT ?? 9499)
const WARMUP_S = Number(process.env.WARMUP_S ?? 8)
const MEASURE_S = Number(process.env.MEASURE_S ?? 15)
const QUERY = process.env.QUERY ?? ''
const DIST = resolve(process.env.DIST ?? join(ROOT, 'dist'))
const VIDEO = resolve(process.env.VIDEO ?? join(ROOT, 'scripts/e2e/.cache/actor.y4m'))
const CHROME = findChrome()
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const noCam = /(^|&)nocam=1/.test(QUERY)

if (!existsSync(join(DIST, 'index.html'))) { console.error(`${DIST}/index.html 없음 — npm run build 먼저`); process.exit(2) }
if (!noCam && !existsSync(VIDEO)) { console.error(`${VIDEO} 없음 — npm run e2e로 배우 영상을 만들거나 VIDEO=를 지정하세요`); process.exit(2) }

const preview = spawn(process.execPath, [VITE_BIN, 'preview', '--outDir', DIST, '--port', String(PORT), '--strictPort'], { stdio: 'pipe', cwd: ROOT })
await new Promise((res, rej) => {
  const to = setTimeout(() => rej(new Error('vite preview timeout')), 15000)
  preview.stdout.on('data', (d) => { if (d.toString().includes(String(PORT))) { clearTimeout(to); setTimeout(res, 300) } })
  preview.on('exit', () => rej(new Error('vite preview exited early')))
})

const profile = mkdtempSync(join(tmpdir(), 'smiley-bench-'))
let chrome = null
let ws = null
let out = null
try {
  chrome = spawn(CHROME, [
    '--headless=new', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required',
    `--remote-debugging-port=${CDP_PORT}`, '--window-size=600,620', `--user-data-dir=${profile}`,
    '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
    ...(noCam ? [] : [`--use-file-for-fake-video-capture=${VIDEO}`]), 'about:blank',
  ], { stdio: 'ignore' })

  let wsUrl = null
  for (let i = 0; i < 50 && !wsUrl; i++) {
    await sleep(200)
    try { wsUrl = (await (await fetch(`http://localhost:${CDP_PORT}/json`)).json()).find((t) => t.type === 'page')?.webSocketDebuggerUrl ?? null } catch { /* 기동 중 */ }
  }
  if (!wsUrl) throw new Error('CDP endpoint not found')
  ws = new WebSocket(wsUrl)
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('CDP ws error')) })
  let id = 0
  const pending = new Map()
  const logs = []
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data)
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
    if (msg.method === 'Runtime.consoleAPICalled') logs.push(`[${msg.params.type}] ` + msg.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
  }
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true })).result?.result?.value
  const metrics = async () => Object.fromEntries((await send('Performance.getMetrics')).result.metrics.map((m) => [m.name, m.value]))

  await send('Runtime.enable')
  await send('Page.enable')
  await send('Performance.enable')
  // 페이지 스크립트보다 먼저: rVFC 콜백 본문 시간 측정 + longtask 관찰
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `(() => {
      const st = window.__bench = { rvfc: [], longtasks: 0, on: false }
      const orig = HTMLVideoElement.prototype.requestVideoFrameCallback
      HTMLVideoElement.prototype.requestVideoFrameCallback = function (cb) {
        return orig.call(this, (now, meta) => {
          const t0 = performance.now()
          try { cb(now, meta) } finally { if (st.on) st.rvfc.push(performance.now() - t0) }
        })
      }
      try { new PerformanceObserver((l) => { if (st.on) st.longtasks += l.getEntries().length }).observe({ entryTypes: ['longtask'] }) } catch {}
    })()`,
  })
  await send('Page.navigate', { url: `http://localhost:${PORT}/index.html?debug=1${QUERY ? '&' + QUERY : ''}` })

  if (!noCam) {
    const deadline = Date.now() + 40000
    while (Date.now() < deadline && !logs.some((l) => l.includes('[navy] tracking started'))) await sleep(300)
    if (!logs.some((l) => l.includes('[navy] tracking started'))) throw new Error('tracking did not start\n' + logs.join('\n'))
  }
  await sleep(WARMUP_S * 1000)

  await evaluate('window.__bench.rvfc.length = 0; window.__bench.longtasks = 0; window.__bench.on = true')
  const m0 = await metrics()
  await sleep(MEASURE_S * 1000)
  const m1 = await metrics()
  const stats = await evaluate(`(() => {
    const b = window.__bench; b.on = false
    const a = b.rvfc.slice().sort((x, y) => x - y)
    const q = (p) => (a.length ? a[Math.min(a.length - 1, Math.floor(a.length * p))] : 0)
    const t = window.__mingoTracking ?? {}
    return { rvfcN: a.length, rvfcMean: a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0, rvfcP95: q(0.95), rvfcMax: a.length ? a[a.length - 1] : 0,
      longtasks: b.longtasks, mode: t.mode ?? 'main(legacy)', fps: t.fps ?? 0, everyFrame: t.everyFrame ?? null, costMs: t.costMs ?? null,
      mainMs: t.mainMs ?? null, latencyMs: t.latencyMs ?? null }
  })()`)
  const dt = m1.Timestamp - m0.Timestamp
  const busy = ((m1.TaskDuration - m0.TaskDuration) / dt) * 100
  const script = ((m1.ScriptDuration - m0.ScriptDuration) / dt) * 100
  out = { query: QUERY || '(기본)', measureS: +dt.toFixed(1), mainBusyPct: +busy.toFixed(1), mainScriptPct: +script.toFixed(1), ...stats }
  const r = (x) => (typeof x === 'number' ? +x.toFixed(2) : x)
  for (const k of Object.keys(out)) if (typeof out[k] === 'number') out[k] = r(out[k])
  if (out.costMs) out.costMs = Object.fromEntries(Object.entries(out.costMs).map(([k, v]) => [k, r(v)]))
  console.log(JSON.stringify(out, null, 1))
} finally {
  try { ws?.close() } catch { /* noop */ }
  chrome?.kill('SIGTERM')
  preview.kill('SIGTERM')
  await sleep(300)
  try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }) } catch { /* 임시 폴더 */ }
}
process.exit(out ? 0 : 1)
