#!/usr/bin/env node
/**
 * 트래킹 E2E — 웹캠 없이 "가짜 사람" 영상으로 거울 매핑 부호를 검증한다.
 *
 *   npm run e2e
 *   ACTOR_VRM=/path/to/humanoid.vrm npm run e2e     (기본: ../animal-hood-girl-vtuber/public/models/placeholder.vrm)
 *
 * 1) scripts/e2e/actor 페이지가 VRM 배우를 웹캠 화각으로 렌더 → YUV420 y4m (ffmpeg 불필요)
 * 2) smoke-tracking.mjs가 그 영상을 Chrome 가짜 카메라로 주입해 원본 RigFrame을 샘플링
 * 3) 타임라인 구간별 기대 부호를 단언한다. 핵심: 배우가 **오른팔**을 들면 네이비 **왼팔(armL, 화면 오른쪽)**이 든다.
 *
 * 한계: 애니 렌더 손은 손톱·손금 같은 앞뒤 단서가 없어 MediaPipe가 손바닥 앞/뒤를 구분하지 못한다.
 * palmNormal 부호는 여기서 단언하지 않는다(유도는 src/tracking/math.ts handOrientFromWorld).
 */
import { spawn, spawnSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, openSync, writeSync, closeSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { findChrome, VITE_BIN } from '../lib/platform.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '../..')
const ACTOR_DIR = join(HERE, 'actor')
const CACHE = join(HERE, '.cache')
const PORT = 5296
const CDP_PORT = 9496
const CHROME = findChrome()
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const vrmPath = resolve(process.env.ACTOR_VRM ?? join(ROOT, '../animal-hood-girl-vtuber/public/models/placeholder.vrm'))
if (!existsSync(vrmPath)) {
  console.error(`배우 VRM이 없습니다: ${vrmPath}\nACTOR_VRM=휴머노이드.vrm 으로 지정하세요 (VRoid 공식 CC0 샘플 등).`)
  process.exit(2)
}
mkdirSync(CACHE, { recursive: true })
copyFileSync(vrmPath, join(ACTOR_DIR, 'actor.vrm'))
const clip = join(CACHE, 'actor.y4m')

/* ---------- 1) 배우 영상 렌더 ---------- */
async function renderClip() {
  const vite = spawn(process.execPath, [VITE_BIN, ACTOR_DIR, '--port', String(PORT), '--strictPort'], { stdio: 'pipe', cwd: ROOT })
  await new Promise((res, rej) => {
    const to = setTimeout(() => rej(new Error('actor vite timeout')), 20000)
    vite.stdout.on('data', (d) => { if (d.toString().includes(String(PORT))) { clearTimeout(to); setTimeout(res, 300) } })
  })
  const profile = mkdtempSync(join(tmpdir(), 'smiley-actor-'))
  const chrome = spawn(CHROME, ['--headless=new', '--enable-unsafe-swiftshader', `--remote-debugging-port=${CDP_PORT}`,
    '--window-size=640,480', '--force-device-scale-factor=1', `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' })
  let ws
  try {
    let wsUrl = null
    for (let i = 0; i < 50 && !wsUrl; i++) {
      await sleep(200)
      try { wsUrl = (await (await fetch(`http://localhost:${CDP_PORT}/json`)).json()).find((t) => t.type === 'page')?.webSocketDebuggerUrl } catch { /* 기동 중 */ }
    }
    if (!wsUrl) throw new Error('actor CDP not found')
    ws = new WebSocket(wsUrl)
    await new Promise((r) => { ws.onopen = r })
    let id = 0
    const pend = new Map()
    const errs = []
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id) }
      if (m.method === 'Runtime.exceptionThrown') errs.push(m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text)
    }
    const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
    const ev = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true })).result?.result?.value
    await send('Runtime.enable')
    await send('Page.enable')
    await send('Page.navigate', { url: `http://localhost:${PORT}/index.html` })
    for (let i = 0; i < 160 && (await ev('document.title')) !== 'READY'; i++) await sleep(250)
    if ((await ev('document.title')) !== 'READY') throw new Error('actor not READY\n' + errs.join('\n'))
    const meta = await ev('window.ACTOR')
    const n = Math.round(meta.DURATION * 30)
    const fd = openSync(clip, 'w')
    writeSync(fd, `YUV4MPEG2 W${meta.W} H${meta.H} F30:1 Ip A1:1 C420jpeg\n`)
    for (let i = 0; i < n; i++) {
      const b64 = await ev(`window.frameYuvAt(${i / 30})`)
      writeSync(fd, 'FRAME\n')
      writeSync(fd, Buffer.from(b64, 'base64'))
    }
    closeSync(fd)
    console.log(`[e2e] 배우 영상 ${n}프레임 → ${clip}`)
    return meta
  } finally {
    try { ws?.close() } catch { /* noop */ }
    chrome.kill('SIGTERM')
    vite.kill('SIGTERM')
    // Chrome이 종료 직후에도 프로필에 쓰는 중일 수 있어 재시도, 실패해도 테스트 결과와 무관
    try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }) } catch { /* 임시 폴더 */ }
  }
}

const meta = await renderClip()

/* ---------- 2) 트래커에 주입 + 샘플링 ---------- */
const samplesPath = join(CACHE, 'samples.json')
// 이전 실행의 샘플이 남아 있으면 트래킹이 실패해도 그 파일로 단언해 거짓 통과한다
rmSync(samplesPath, { force: true })
const sampleS = Math.ceil(meta.DURATION * 2 + 2)
const run = spawnSync(process.execPath, [join(ROOT, 'scripts/smoke-tracking.mjs')], {
  cwd: ROOT,
  stdio: ['ignore', 'pipe', 'inherit'],
  env: { ...process.env, VIDEO: clip, SAMPLE_S: String(sampleS), WAIT_MS: '20000', SAMPLES_OUT: samplesPath, SKIP_BUILD: process.env.SKIP_BUILD ?? '' },
  encoding: 'utf8',
  maxBuffer: 64 * 1024 * 1024,
})
const tail = run.stdout.split('\n').filter((l) => /result|SMOKE|tracking started|delegates/.test(l))
console.log(tail.join('\n'))
// 스모크가 실패했는데(예: 워커가 조용히 메인 스레드 폴백으로 떨어짐) 샘플만 보고 통과시키지 않는다
if (run.status !== 0) {
  console.error('[e2e] 스모크 실패 — 트래킹이 기대한 모드로 시작되지 않았습니다')
  process.exit(1)
}
if (!existsSync(samplesPath)) {
  console.error('[e2e] 샘플이 없습니다 — 트래킹이 시작되지 않았습니다')
  process.exit(1)
}
const S = JSON.parse(readFileSync(samplesPath, 'utf8'))

/* ---------- 3) 타임라인 정렬 + 단언 ---------- */
const D = meta.DURATION
const win = Object.fromEntries(meta.TIMELINE.map(([name, a, b]) => [name, [a, b]]))
const ft = (s, off) => (((s.vt - off) % D) + D) % D
/** 램프(0.5s)와 필터 지연을 피해 구간 안쪽만 본다 */
const inHold = (name, t) => t >= win[name][0] + 0.75 && t <= win[name][1] - 0.6

// 오프셋 탐색: 오른팔/왼팔 수평 구간이 가장 잘 맞는 오프셋
let best = { off: 0, score: -1 }
for (let off = 0; off < D; off += 0.05) {
  let score = 0
  for (const s of S) {
    const t = ft(s, off)
    if (inHold('rightArmSide', t) && s.L.up[0] > 0.8) score++
    if (inHold('leftArmSide', t) && s.R.up[0] < -0.8) score++
  }
  if (score > best.score) best = { off, score }
}
const pick = (name) => S.filter((s) => inHold(name, ft(s, best.off)))
const median = (xs) => { const a = [...xs].sort((p, q) => p - q); return a.length ? a[Math.floor(a.length / 2)] : NaN }
const max = (xs) => (xs.length ? Math.max(...xs) : NaN)
const curl4 = (s, k) => (s[k].fi[1] + s[k].fi[2] + s[k].fi[3] + s[k].fi[4]) / 4

const checks = [
  ['차렷: 양팔 아래', () => { const x = pick('neutral'); return [median(x.map((s) => s.L.up[1])) < -0.8 && median(x.map((s) => s.R.up[1])) < -0.8, `L.up.y ${median(x.map((s) => s.L.up[1])).toFixed(2)}, R.up.y ${median(x.map((s) => s.R.up[1])).toFixed(2)}`] }],
  ['배우 오른팔 수평 → armL(화면 오른쪽) +x', () => { const x = pick('rightArmSide'); const v = median(x.map((s) => s.L.up[0])); return [v > 0.8 && median(x.map((s) => s.R.up[1])) < -0.8, `armL.up.x ${v.toFixed(2)}, armR.up.y ${median(x.map((s) => s.R.up[1])).toFixed(2)}`] }],
  ['배우 왼팔 수평 → armR(화면 왼쪽) -x', () => { const x = pick('leftArmSide'); const v = median(x.map((s) => s.R.up[0])); return [v < -0.8 && median(x.map((s) => s.L.up[1])) < -0.8, `armR.up.x ${v.toFixed(2)}, armL.up.y ${median(x.map((s) => s.L.up[1])).toFixed(2)}`] }],
  ['배우 오른손 흔들기 → armL 전완·손 위로', () => { const x = pick('rightWave'); const lo = median(x.map((s) => s.L.lo[1])); const hd = median(x.map((s) => s.L.hd[1])); return [lo > 0.35 && hd > 0.5, `armL.lower.y ${lo.toFixed(2)}, handDir.y ${hd.toFixed(2)}`] }],
  ['배우 자기 오른쪽으로 고개 → yaw > 0 (화면 오른쪽을 봄)', () => { const v = max(pick('headRight').map((s) => s.yaw)); return [v > 0.15, `max yaw ${v.toFixed(2)}`] }],
  ['입 벌림 → mouthOpen 상승', () => { const v = max(pick('mouthOpen').map((s) => s.mo)); const base = median(pick('neutral').map((s) => s.mo)); return [v > base + 0.05, `max ${v.toFixed(2)} (기준 ${base.toFixed(2)})`] }],
  ['눈 감기 → 양눈 blink', () => { const v = max(pick('blink').map((s) => Math.min(s.bl, s.br))); return [v > 0.3, `max min(L,R) ${v.toFixed(2)}`] }],
  ['배우 오른손 주먹 → armL 손가락 말림', () => { const f = median(pick('rightFist').map((s) => curl4(s, 'L'))); const o = median(pick('rightWave').map((s) => curl4(s, 'L'))); return [f > 0.5 && f > o + 0.3, `fist ${f.toFixed(2)} vs open ${o.toFixed(2)}`] }],
]

console.log(`\n[e2e] 정렬 오프셋 ${best.off.toFixed(2)}s (일치 샘플 ${best.score}), 샘플 ${S.length}개`)
let fails = 0
for (const [name, fn] of checks) {
  let ok = false
  let detail = ''
  try { [ok, detail] = fn() } catch (e) { detail = String(e) }
  if (!ok) fails++
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  — ${detail}`)
}
console.log(fails ? `\nE2E FAIL (${fails}/${checks.length})` : `\nE2E OK (${checks.length}/${checks.length})`)
process.exit(fails ? 1 : 0)
