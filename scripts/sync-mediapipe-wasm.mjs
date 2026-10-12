#!/usr/bin/env node
// MediaPipe WASM 런타임을 node_modules에서 public/wasm으로 복사한다.
// JS 패키지 버전과 WASM 버전이 항상 일치하도록 커밋하지 않고 설치 시 동기화한다.
import { cpSync, existsSync, mkdirSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = join(root, 'node_modules/@mediapipe/tasks-vision/wasm')
const dst = join(root, 'public/wasm')

if (!existsSync(src)) {
  console.warn('[sync-mediapipe-wasm] @mediapipe/tasks-vision 미설치 — 건너뜀')
  process.exit(0)
}
mkdirSync(dst, { recursive: true })
for (const f of readdirSync(src)) cpSync(join(src, f), join(dst, f))
console.log(`[sync-mediapipe-wasm] ${readdirSync(dst).length}개 파일 → public/wasm`)
