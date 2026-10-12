import { defineConfig } from 'vite'
import { resolve } from 'node:path'

// HARNESS_ONLY=1 → 하네스 페이지만 빌드 (스크린샷 QA용)
const harnessOnly = process.env.HARNESS_ONLY === '1'

export default defineConfig({
  root: 'src',
  base: './',
  publicDir: '../public',
  // 워크트리 병렬 빌드에서 node_modules를 심링크로 공유할 때 캐시 레이스 방지
  ...(process.env.VITE_CACHE_DIR ? { cacheDir: process.env.VITE_CACHE_DIR } : {}),
  server: { port: 5187, strictPort: true },
  // 트래킹 워커는 모듈 워커(new Worker(url, { type: 'module' }))라 번들도 ES 포맷이어야 한다.
  // (기본값 iife는 동적 import()·code splitting을 못 쓴다 — tasks-vision wasm 로더가 import()로 로드됨)
  worker: { format: 'es' },
  build: {
    // 하네스 전용 빌드는 따로 둔다 — 앱(런처 번들)이 읽는 dist를 스크린샷 빌드가 덮어쓰지 않게
    outDir: harnessOnly ? '../' + (process.env.HARNESS_OUT ?? 'dist-harness') : '../dist',
    emptyOutDir: true,
    target: 'es2022',
    rollupOptions: {
      input: harnessOnly
        ? { harness: resolve(import.meta.dirname, 'src/harness.html') }
        : {
            main: resolve(import.meta.dirname, 'src/index.html'),
            harness: resolve(import.meta.dirname, 'src/harness.html'),
          },
    },
  },
})
