import * as T from 'three'
import type { RigFrame } from '../contract'

/** public/navy-rig.json (rig/CONTRACT.md) */
export interface NavyRig {
  height: number
  joints: Record<string, [number, number, number]>
  face: {
    eyeL?: { center: [number, number, number]; width: number; height: number }
    eyeR?: { center: [number, number, number]; width: number; height: number }
    mouth?: { center: [number, number, number]; width: number; upper: [number, number, number]; lower: [number, number, number] }
  }
}

/**
 * 구운 눈·입 위에 깜빡임·입 벌림·볼터치만 덧그린다. 평소엔 아무것도 안 보인다.
 *
 * 방식: bind 때 얼굴 앞면을 높이장(heightfield)으로 래스터해 둔다 (메시 정점 → 격자의 가장 앞 z + 텍스처 uv).
 * 눈/입 자리마다 그 높이장에 얹은 격자 패치 하나와 캔버스 텍스처 하나를 만들고, 상태가 바뀔 때만 캔버스를 다시 그린다.
 * 눈꺼풀 색은 구운 텍스처에서 눈 주변 피부를 재서 쓴다. 패치는 head 뼈의 자식이라 고개를 따라간다.
 * 디버그: ?facedebug=1 이면 찾아낸 눈 영역을 색으로 표시한다.
 */

/* ------------------------------------------------------------------ */
/* 높이장                                                              */
/* ------------------------------------------------------------------ */

const CELL = 0.004
const HX0 = -0.7, HX1 = 0.7, HY0 = 1.3, HY1 = 2.25
/** 패치를 피부 앞으로 띄우는 거리 (높이장 평활 후) */
const LIFT = 0.005

interface Heightfield {
  nx: number
  ny: number
  /** 가장 앞 표면 z (평활 전) */
  raw: Float32Array
  /** 패치가 얹히는 평활된 z */
  z: Float32Array
  u: Float32Array
  v: Float32Array
  zAt(x: number, y: number): number
}

/** 가로·세로 분리 박스 필터 (kind: 'max' 팽창 / 'avg' 평균) */
function filter1d(src: Float32Array, nx: number, ny: number, r: number, kind: 'max' | 'avg'): Float32Array {
  const tmp = new Float32Array(src.length), out = new Float32Array(src.length)
  const run = (a: Float32Array, b: Float32Array, len: number, lines: number, stride: number, step: number) => {
    for (let l = 0; l < lines; l++) {
      const base = l * stride
      for (let i = 0; i < len; i++) {
        let acc = kind === 'max' ? -Infinity : 0, cnt = 0
        for (let k = -r; k <= r; k++) {
          const j = i + k
          if (j < 0 || j >= len) continue
          const val = a[base + j * step]!
          if (kind === 'max') { if (val > acc) acc = val } else acc += val
          cnt++
        }
        b[base + i * step] = kind === 'max' ? acc : acc / cnt
      }
    }
  }
  run(src, tmp, nx, ny, nx, 1)
  run(tmp, out, ny, nx, 1, nx)
  return out
}

function buildHeightfield(mesh: T.SkinnedMesh): Heightfield {
  const nx = Math.round((HX1 - HX0) / CELL), ny = Math.round((HY1 - HY0) / CELL)
  const raw = new Float32Array(nx * ny).fill(-Infinity)
  const U = new Float32Array(nx * ny), V = new Float32Array(nx * ny)
  const geo = mesh.geometry
  const pos = geo.getAttribute('position'), uv = geo.getAttribute('uv')
  const n = pos.count
  const P = new Float32Array(n * 3)
  const tmp = new T.Vector3()
  mesh.updateWorldMatrix(true, false)
  for (let i = 0; i < n; i++) {
    mesh.getVertexPosition(i, tmp) // 스킨 적용 (bind 자세)
    tmp.applyMatrix4(mesh.matrixWorld)
    P[i * 3] = tmp.x; P[i * 3 + 1] = tmp.y; P[i * 3 + 2] = tmp.z
  }
  const idx = geo.index
  const tris = idx ? idx.count / 3 : n / 3
  for (let t = 0; t < tris; t++) {
    const ia = idx ? idx.getX(t * 3) : t * 3, ib = idx ? idx.getX(t * 3 + 1) : t * 3 + 1, ic = idx ? idx.getX(t * 3 + 2) : t * 3 + 2
    const ax = P[ia * 3]!, ay = P[ia * 3 + 1]!, az = P[ia * 3 + 2]!
    const bx = P[ib * 3]!, by = P[ib * 3 + 1]!, bz = P[ib * 3 + 2]!
    const cx = P[ic * 3]!, cy = P[ic * 3 + 1]!, cz = P[ic * 3 + 2]!
    if (az < 0.1 && bz < 0.1 && cz < 0.1) continue
    const minx = Math.min(ax, bx, cx), maxx = Math.max(ax, bx, cx), miny = Math.min(ay, by, cy), maxy = Math.max(ay, by, cy)
    if (maxx < HX0 || minx > HX1 || maxy < HY0 || miny > HY1) continue
    const det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if (Math.abs(det) < 1e-12) continue
    const i0 = Math.max(0, Math.floor((minx - HX0) / CELL)), i1 = Math.min(nx - 1, Math.floor((maxx - HX0) / CELL))
    const j0 = Math.max(0, Math.floor((miny - HY0) / CELL)), j1 = Math.min(ny - 1, Math.floor((maxy - HY0) / CELL))
    for (let j = j0; j <= j1; j++) {
      const py = HY0 + (j + 0.5) * CELL
      for (let i = i0; i <= i1; i++) {
        const px = HX0 + (i + 0.5) * CELL
        const l1 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / det
        const l2 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / det
        const l3 = 1 - l1 - l2
        if (l1 < -1e-5 || l2 < -1e-5 || l3 < -1e-5) continue
        const z = l1 * az + l2 * bz + l3 * cz
        const k = j * nx + i
        if (z > raw[k]!) {
          raw[k] = z
          U[k] = l1 * uv.getX(ia) + l2 * uv.getX(ib) + l3 * uv.getX(ic)
          V[k] = l1 * uv.getY(ia) + l2 * uv.getY(ib) + l3 * uv.getY(ic)
        }
      }
    }
  }
  // 빈 칸(작은 삼각형 틈)은 이웃으로 메운다
  let minZ = Infinity
  for (const z of raw) if (z > -Infinity && z < minZ) minZ = z
  if (!Number.isFinite(minZ)) minZ = 0
  for (let pass = 0; pass < 3; pass++) {
    const snap = raw.slice()
    for (let j = 1; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++) {
      const k = j * nx + i
      if (snap[k]! > -Infinity) continue
      let s = 0, c = 0, src = -1
      for (const d of [-1, 1, -nx, nx, -nx - 1, -nx + 1, nx - 1, nx + 1]) {
        const z = snap[k + d]!
        if (z > -Infinity) { s += z; c++; if (src < 0) src = k + d }
      }
      if (c >= 2) { raw[k] = s / c; U[k] = U[src]!; V[k] = V[src]! }
    }
  }
  for (let k = 0; k < raw.length; k++) if (raw[k]! === -Infinity) raw[k] = minZ
  // 패치용 z: 울퉁불퉁한 면 위로 뜨지도 파묻히지도 않게 팽창 후 평활
  let z = filter1d(raw, nx, ny, 2, 'max')
  z = filter1d(z, nx, ny, 3, 'avg')
  z = filter1d(z, nx, ny, 3, 'avg')
  const hf: Heightfield = {
    nx, ny, raw, z, u: U, v: V,
    zAt(x, y) {
      const fx = Math.min(nx - 1.001, Math.max(0, (x - HX0) / CELL - 0.5)), fy = Math.min(ny - 1.001, Math.max(0, (y - HY0) / CELL - 0.5))
      const i = Math.floor(fx), j = Math.floor(fy), tx = fx - i, ty = fy - j
      const k = j * nx + i
      return (z[k]! * (1 - tx) + z[k + 1]! * tx) * (1 - ty) + (z[k + nx]! * (1 - tx) + z[k + nx + 1]! * tx) * ty
    },
  }
  return hf
}

/* ------------------------------------------------------------------ */
/* 텍스처 색 읽기                                                       */
/* ------------------------------------------------------------------ */

type RGB = [number, number, number]
const DEFAULT_SKIN: RGB = [236, 196, 172]
const RING_N = 16
/** 눈 덮개: 구운 눈 반축 + 이 값까지가 바깥 끝(알파 0), 그 안쪽 FULL 까지는 완전 불투명 */
const EYE_OUT = 0.05, EYE_FULL = 0.012

function makeTexReader(map: T.Texture | null): ((u: number, v: number) => RGB) | null {
  try {
    const img = map?.image as (CanvasImageSource & { width: number; height: number }) | undefined
    if (!img || !img.width) return null
    const c = document.createElement('canvas')
    c.width = img.width; c.height = img.height
    const g = c.getContext('2d', { willReadFrequently: true })!
    g.drawImage(img, 0, 0)
    const w = c.width, h = c.height
    const data = g.getImageData(0, 0, w, h).data
    const flip = !!map!.flipY
    return (u, v) => {
      const px = Math.min(w - 1, Math.max(0, Math.floor(u * w)))
      const py = Math.min(h - 1, Math.max(0, Math.floor((flip ? 1 - v : v) * h)))
      const o = (py * w + px) * 4
      return [data[o]!, data[o + 1]!, data[o + 2]!]
    }
  } catch { return null }
}

const luma = (c: RGB) => 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
const median = (a: number[]) => { if (!a.length) return 0; const s = a.slice().sort((x, y) => x - y); return s[s.length >> 1]! }
const medianRGB = (cs: RGB[]): RGB => [median(cs.map(c => c[0])), median(cs.map(c => c[1])), median(cs.map(c => c[2]))]
const css = (c: RGB, a = 1) => `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${a})`
const smooth = (a: number, b: number, x: number) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t) }
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, Number.isFinite(v) ? v : 0))

/** 덮개 타원 바로 바깥의 피부색을 각도 구간별 중앙값으로 잰다. 눈썹·머리 같은 어두운 칸은 빼고, 빈 구간은 이웃에서 채운다 */
function sampleRing(hf: Heightfield, tex: ((u: number, v: number) => RGB) | null, cx: number, cy: number, A: number, B: number, skin: RGB): RGB[] {
  const bins: RGB[][] = Array.from({ length: RING_N }, () => [])
  if (tex) {
    const r = Math.max(A, B) * 1.5
    const i0 = Math.floor((cx - r - HX0) / CELL), i1 = Math.floor((cx + r - HX0) / CELL)
    const j0 = Math.floor((cy - r - HY0) / CELL), j1 = Math.floor((cy + r - HY0) / CELL)
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      const x = HX0 + (i + 0.5) * CELL - cx, y = HY0 + (j + 0.5) * CELL - cy
      const n = Math.hypot(x / A, y / B)
      if (n < 1.06 || n > 1.4) continue
      const k = j * hf.nx + i
      const c = tex(hf.u[k]!, hf.v[k]!)
      if (luma(c) < luma(skin) * 0.8 || c[0] - c[2] < 20) continue
      let ang = Math.atan2(y, x); if (ang < 0) ang += Math.PI * 2
      bins[Math.round(ang / (Math.PI * 2) * RING_N) % RING_N]!.push(c)
    }
  }
  const out: (RGB | null)[] = bins.map(b => (b.length >= 6 ? medianRGB(b) : null))
  if (out.every(c => c === null)) return new Array<RGB>(RING_N).fill(skin)
  const filled = out.map((c, i) => {
    if (c) return c
    for (let d = 1; d < RING_N; d++) { const n = out[(i + d) % RING_N] ?? out[(i - d + RING_N) % RING_N]; if (n) return n }
    return skin
  })
  // 눈 안쪽은 어느 방향 색이 맞는지 알 수 없으니 평균 쪽으로 반쯤 당겨 쐐기 무늬를 줄인다
  const mean = medianRGB(filled)
  // 덮개가 구운 피부보다 밝아 보이지 않게 살짝 어둡게 (0.96)
  return filled.map(c => [(c[0] * 0.55 + mean[0] * 0.45) * 0.96, (c[1] * 0.55 + mean[1] * 0.45) * 0.96, (c[2] * 0.55 + mean[2] * 0.45) * 0.96] as RGB)
}

/* ------------------------------------------------------------------ */
/* 눈 찾기                                                              */
/* ------------------------------------------------------------------ */

interface EyeShape {
  cx: number; cy: number
  /** 눈(어두운 부분)의 반축 */
  a: number; b: number
  /** 장축 기울기 (rad) */
  th: number
  /** 눈 둘레 피부색 (각도 N등분, 장축 기준 반시계) */
  ring: RGB[]
  found: boolean
}

/** 눈 주변 피부색을 재고, 어두운 눈 덩어리를 flood fill 해서 타원으로 맞춘다. 실패하면 rig json 치수로 대신한다 */
function detectEye(hf: Heightfield, tex: ((u: number, v: number) => RGB) | null, cx0: number, cy0: number, w: number): EyeShape {
  const fallback: EyeShape = { cx: cx0, cy: cy0, a: w * 0.5, b: w * 0.46, th: 0, ring: new Array<RGB>(RING_N).fill(DEFAULT_SKIN), found: false }
  if (!tex) return fallback
  const col = (k: number) => tex(hf.u[k]!, hf.v[k]!)
  // 전체 피부색(눈 덩어리 임계값용): 눈에서 떨어진 고리 중 밝은 칸
  const R = w * 0.5
  const i0 = Math.floor((cx0 - 0.3 - HX0) / CELL), i1 = Math.floor((cx0 + 0.3 - HX0) / CELL)
  const j0 = Math.floor((cy0 - 0.3 - HY0) / CELL), j1 = Math.floor((cy0 + 0.22 - HY0) / CELL)
  const all: RGB[] = []
  for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
    const x = HX0 + (i + 0.5) * CELL, y = HY0 + (j + 0.5) * CELL
    const r = Math.hypot((x - cx0) / R, (y - cy0) / R)
    if (r < 1.55 || r > 2.2) continue
    const c = col(j * hf.nx + i)
    if (luma(c) < 140 || c[0] - c[2] < 25) continue // 눈썹·머리카락·옷 제외
    all.push(c)
  }
  if (all.length < 40) return fallback
  const skin = medianRGB(all)
  const darkT = luma(skin) * 0.62
  // 눈 덩어리: 중심 근처 어두운 칸에서 번져 나간다
  const win = (i: number, j: number) => {
    const x = HX0 + (i + 0.5) * CELL, y = HY0 + (j + 0.5) * CELL
    return Math.abs(x - cx0) < w * 0.9 && Math.abs(y - cy0) < w * 0.8
  }
  const seen = new Set<number>(), stack: number[] = []
  const si = Math.floor((cx0 - HX0) / CELL), sj = Math.floor((cy0 - HY0) / CELL)
  const sr = Math.ceil(0.05 / CELL)
  for (let j = sj - sr; j <= sj + sr; j++) for (let i = si - sr; i <= si + sr; i++) {
    const k = j * hf.nx + i
    if (luma(col(k)) < darkT) { seen.add(k); stack.push(k) }
  }
  const cells: number[] = []
  while (stack.length) {
    const k = stack.pop()!
    cells.push(k)
    const i = k % hf.nx, j = (k - i) / hf.nx
    for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
      const ni = i + di, nj = j + dj
      if (ni < 0 || nj < 0 || ni >= hf.nx || nj >= hf.ny || !win(ni, nj)) continue
      const nk = nj * hf.nx + ni
      if (seen.has(nk) || luma(col(nk)) >= darkT) continue
      seen.add(nk); stack.push(nk)
    }
  }
  if (cells.length < 80) return fallback
  // 무게중심·주축
  let mx = 0, my = 0
  const pts = cells.map(k => { const i = k % hf.nx, j = (k - i) / hf.nx; return [HX0 + (i + 0.5) * CELL, HY0 + (j + 0.5) * CELL] as const })
  for (const [x, y] of pts) { mx += x; my += y }
  mx /= pts.length; my /= pts.length
  let sxx = 0, sxy = 0, syy = 0
  for (const [x, y] of pts) { const dx = x - mx, dy = y - my; sxx += dx * dx; sxy += dx * dy; syy += dy * dy }
  let th = 0.5 * Math.atan2(2 * sxy, sxx - syy)
  th = 0 // 거의 원이라 각도가 불안정하다 → 축 정렬 타원으로 둔다
  const c = Math.cos(th), s = Math.sin(th)
  let umin = Infinity, umax = -Infinity, vmin = Infinity, vmax = -Infinity
  for (const [x, y] of pts) {
    const p = (x - mx) * c + (y - my) * s, q = -(x - mx) * s + (y - my) * c
    umin = Math.min(umin, p); umax = Math.max(umax, p); vmin = Math.min(vmin, q); vmax = Math.max(vmax, q)
  }
  const ucx = (umin + umax) / 2, vcy = (vmin + vmax) / 2
  const ex = mx + ucx * c - vcy * s, ey = my + ucx * s + vcy * c
  let a = (umax - umin) / 2, b = (vmax - vmin) / 2
  // 모든 칸이 타원 안에 들어오게 키운다
  let kmax = 1
  for (const [x, y] of pts) {
    const p = (x - ex) * c + (y - ey) * s, q = -(x - ex) * s + (y - ey) * c
    kmax = Math.max(kmax, Math.hypot(p / a, q / b))
  }
  a *= kmax; b *= kmax
  // 비정상(너무 작거나 창을 꽉 채움)이면 rig 값
  if (a < w * 0.25 || b < w * 0.2 || a > w * 0.85 || b > w * 0.75) return fallback
  const ring = sampleRing(hf, tex, ex, ey, a + EYE_OUT, b + EYE_OUT, skin)
  return { cx: ex, cy: ey, a, b, th, ring, found: true }
}

/** 구운 웃는 입선의 높이를 찾는다 (가운데 열들에서 주변보다 가장 어두운 줄). 못 찾으면 null */
function detectMouthY(hf: Heightfield, tex: ((u: number, v: number) => RGB) | null, mx: number, my: number): number | null {
  if (!tex) return null
  const ys: number[] = []
  const d = Math.round(0.022 / CELL)
  for (let x = mx - 0.05; x <= mx + 0.05; x += CELL) {
    const i = Math.floor((x - HX0) / CELL)
    let best = 0, by = NaN
    for (let y = my - 0.04; y <= my + 0.08; y += CELL) {
      const j = Math.floor((y - HY0) / CELL)
      const l = (jj: number) => { const k = jj * hf.nx + i; return luma(tex(hf.u[k]!, hf.v[k]!)) }
      const c = (l(j - d) + l(j + d)) / 2 - l(j) // 위아래 평균보다 얼마나 어두운가
      if (c > best) { best = c; by = y }
    }
    if (best > 3) ys.push(by)
  }
  return ys.length >= 8 ? median(ys) : null
}

/* ------------------------------------------------------------------ */
/* 패치 (피부에 얹힌 격자 + 캔버스 텍스처)                                  */
/* ------------------------------------------------------------------ */

interface Patch {
  mesh: T.Mesh
  tex: T.CanvasTexture
  ctx: CanvasRenderingContext2D
  /** 월드 단위(원점=패치 중심, y 위) 로 그릴 수 있게 변환을 걸어 둔다 */
  begin(): CanvasRenderingContext2D
  size: number
}

function makePatch(hf: Heightfield, cx: number, cy: number, sx: number, sy: number, px: number, res: number, toLocal: T.Matrix4, parent: T.Object3D, order: number): Patch {
  const gx = res, gy = Math.max(2, Math.round(res * sy / sx))
  const positions = new Float32Array((gx + 1) * (gy + 1) * 3), uvs = new Float32Array((gx + 1) * (gy + 1) * 2)
  const v = new T.Vector3()
  for (let j = 0; j <= gy; j++) for (let i = 0; i <= gx; i++) {
    const x = cx - sx / 2 + sx * i / gx, y = cy - sy / 2 + sy * j / gy
    v.set(x, y, hf.zAt(x, y) + LIFT).applyMatrix4(toLocal)
    const o = j * (gx + 1) + i
    positions.set([v.x, v.y, v.z], o * 3)
    uvs.set([i / gx, j / gy], o * 2)
  }
  const index: number[] = []
  for (let j = 0; j < gy; j++) for (let i = 0; i < gx; i++) {
    const a = j * (gx + 1) + i, b = a + 1, c = a + gx + 1, d = c + 1
    index.push(a, b, d, a, d, c)
  }
  const geo = new T.BufferGeometry()
  geo.setAttribute('position', new T.BufferAttribute(positions, 3))
  geo.setAttribute('uv', new T.BufferAttribute(uvs, 2))
  geo.setIndex(index)
  geo.computeVertexNormals()
  const canvas = document.createElement('canvas')
  canvas.width = px; canvas.height = Math.round(px * sy / sx)
  const ctx = canvas.getContext('2d')!
  const tex = new T.CanvasTexture(canvas)
  tex.colorSpace = T.SRGBColorSpace
  const mat = new T.MeshStandardMaterial({
    map: tex, transparent: true, roughness: 0.82, metalness: 0, side: T.DoubleSide,
    depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
  })
  const mesh = new T.Mesh(geo, mat)
  mesh.renderOrder = order
  mesh.frustumCulled = false
  mesh.visible = false
  parent.add(mesh)
  const k = px / sx
  return {
    mesh, tex, ctx, size: sx,
    begin() {
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.setTransform(k, 0, 0, -k, canvas.width / 2, canvas.height / 2) // 월드 단위, y 위
      return ctx
    },
  }
}

/** 지금까지 그린 것을 타원 가장자리에서 서서히 지운다 (rFull 안쪽은 그대로, rx/ry 에서 알파 0) */
function featherEllipse(g: CanvasRenderingContext2D, rx: number, ry: number, rFullX: number) {
  g.save()
  g.globalCompositeOperation = 'destination-in'
  g.scale(1, ry / rx)
  const rg = g.createRadialGradient(0, 0, 0, 0, 0, rx)
  const f = Math.min(0.98, rFullX / rx)
  rg.addColorStop(0, 'rgba(0,0,0,1)'); rg.addColorStop(f, 'rgba(0,0,0,1)'); rg.addColorStop(1, 'rgba(0,0,0,0)')
  g.fillStyle = rg
  g.fillRect(-2, -2, 4, 4)
  g.restore()
}

/* ------------------------------------------------------------------ */
/* 그리기                                                               */
/* ------------------------------------------------------------------ */

const LASH = '#2a1b1e'

/** gaze: 눈동자 가로 이동 (눈 반폭 단위, -0.15..0.15), 뷰어 오른쪽이 + */
interface EyeState { lid: number; arch: number; heart: number; gaze: number }

/** 뜬 눈: 갈색 홍채 + 동공 + 윗속눈썹 + 흰 하이라이트 2개. 좌표는 눈 중심 원점, y 위 */
function drawOpenEye(g: CanvasRenderingContext2D, eye: EyeShape, gaze: number, alpha: number, Te: (s: number) => number) {
  const a = eye.a, b = eye.b
  g.save()
  g.globalAlpha = alpha
  g.beginPath(); g.ellipse(0, 0, a * 1.01, b * 1.01, 0, 0, Math.PI * 2)
  g.clip()
  const sh = gaze * a
  // 시선이 옆으로 갈 때만 흰자가 보이게 한다 (평소엔 홍채가 눈을 꽉 채움)
  const wa = smooth(0.03, 0.12, Math.abs(gaze))
  if (wa > 0.01) {
    g.globalAlpha = alpha * wa
    g.fillStyle = '#f3ebe4'
    g.fillRect(-a * 1.1, -b * 1.1, a * 2.2, b * 2.2)
    g.globalAlpha = alpha
  }
  // 홍채
  const ia = a * 0.9, ib = b * 0.95
  g.save()
  g.translate(sh, 0)
  g.scale(1, ib / ia)
  const rg = g.createRadialGradient(0, -ia * 0.12, 0, 0, 0, ia)
  rg.addColorStop(0, '#4e3022'); rg.addColorStop(0.6, '#3a2217'); rg.addColorStop(1, '#1c110d')
  g.fillStyle = rg
  g.beginPath(); g.arc(0, 0, ia, 0, Math.PI * 2); g.fill()
  // 동공
  g.fillStyle = 'rgba(13,8,8,0.8)'
  g.beginPath(); g.arc(0, 0, ia * 0.45, 0, Math.PI * 2); g.fill()
  g.restore()
  g.restore()
  // 윗속눈썹: 눈 윗호를 따라가는 가늘어지는 띠 (눈 높이의 약 12%)
  g.save()
  g.globalAlpha = alpha
  g.fillStyle = '#1a1210'
  const t = 0.24 * b, N = 24, sa = a * 0.99
  const w = (s: number) => t * Math.pow(Math.max(0, 1 - (s / sa) ** 2), 0.6)
  g.beginPath()
  for (let i = 0; i <= N; i++) { const s = -sa + 2 * sa * i / N; g.lineTo(s, Te(s) + w(s) * 0.3) }
  for (let i = N; i >= 0; i--) { const s = -sa + 2 * sa * i / N; g.lineTo(s, Te(s) - w(s) * 0.7) }
  g.closePath(); g.fill()
  // 하이라이트: 큰 것은 왼쪽 위, 작은 것은 오른쪽 아래. 시선이 움직여도 조금만 따라간다
  const hs = sh * 0.4
  g.fillStyle = '#ffffff'
  g.globalAlpha = alpha * 0.95
  g.beginPath(); g.arc(-0.28 * a + hs, 0.28 * b, 0.22 * a, 0, Math.PI * 2); g.fill()
  g.beginPath(); g.arc(0.3 * a + hs, -0.3 * b, 0.09 * a, 0, Math.PI * 2); g.fill()
  g.restore()
}

/** 눈꺼풀 폴리곤 + 속눈썹 선. 눈 장축 좌표계(s: 가로, t: 위) */
function drawEye(p: Patch, eye: EyeShape, st: EyeState, debug: boolean) {
  const g = p.begin()
  g.save()
  g.rotate(eye.th)
  const A = eye.a + EYE_OUT, B = eye.b + EYE_OUT
  const M2 = 28
  const T_ = (s: number) => B * Math.sqrt(Math.max(0, 1 - (s / A) ** 2)) // 덮개 윗호
  const Te = (s: number) => eye.b * Math.sqrt(Math.max(0, 1 - (s / eye.a) ** 2)) // 구운 눈의 윗호 (눈꺼풀은 여기서 내려온다)
  const x2 = (s: number) => (s / eye.a) ** 2
  // 감은 선 모양: ∪(약하게 아래로 휜) ↔ ∩(행복 눈)
  const line = (s: number) => {
    const u = -0.3 * eye.b + 0.227 * eye.b * x2(s)
    const n = 0.3 * eye.b - 0.347 * eye.b * x2(s)
    return u + (n - u) * st.arch
  }
  const L = st.lid
  const edge = (s: number) => Math.min(T_(s), Te(s) + (line(s) - Te(s)) * L)
  const grad = g.createConicGradient(0, 0, 0) // 눈 둘레 피부색을 각도별로 이어 붙인다
  for (let i = 0; i <= RING_N; i++) grad.addColorStop(i / RING_N, css(eye.ring[i % RING_N]!))
  g.fillStyle = grad
  const open = eye.found && L < 0.97
  if (open) {
    // 1) 구운 눈 + 회분홍 테두리를 피부색 덮개로 묻는다
    g.beginPath(); g.ellipse(0, 0, A, B, 0, 0, Math.PI * 2); g.fill()
    // 2) 새 눈: 홍채·동공·윗속눈썹·하이라이트 (하트일 때는 숨김)
    const oa = (1 - smooth(0.85, 0.97, L)) * (1 - smooth(0.1, 0.6, st.heart))
    if (oa > 0.01) drawOpenEye(g, eye, st.gaze, oa, Te)
  }
  if (L > 0.01 || st.heart > 0.01 || open) {
    g.filter = 'blur(0.8px)'
    // 윗눈꺼풀: 눈 윗호 ~ 눈꺼풀 선
    g.beginPath()
    for (let i = 0; i <= M2; i++) { const s = -A + 2 * A * i / M2; if (i) g.lineTo(s, T_(s) + 0.004); else g.moveTo(s, T_(s) + 0.004) }
    for (let i = M2; i >= 0; i--) { const s = -A + 2 * A * i / M2; g.lineTo(s, edge(s)) }
    g.closePath(); g.fill()
    // 아랫눈꺼풀: 눈 밑 호에서 눈꺼풀 선 쪽으로 올라와 만난다 (감을수록 위로)
    const rise = Math.max(smooth(0.45, 1, L), st.heart)
    g.beginPath()
    for (let i = 0; i <= M2; i++) { const s = -A + 2 * A * i / M2; if (i) g.lineTo(s, -T_(s) - 0.004); else g.moveTo(s, -T_(s) - 0.004) }
    for (let i = M2; i >= 0; i--) { const s = -A + 2 * A * i / M2; const be = -Te(s); g.lineTo(s, be + (edge(s) + 0.002 - be) * rise) }
    g.closePath(); g.fill()
    g.filter = 'none'
    featherEllipse(g, A, B, Math.max(eye.a + EYE_FULL, A * (eye.b + 0.012) / B))
    // 속눈썹 선: 양끝이 가늘어지는 띠
    const la = smooth(0.04, 0.4, L) * (1 - st.heart)
    if (la > 0.01) {
      const wmax = 0.011 + 0.006 * L + 0.003 * st.arch
      const sa = eye.a + 0.018
      g.globalAlpha = la
      g.fillStyle = LASH
      g.beginPath()
      const N = 24
      for (let i = 0; i <= N; i++) { const s = -sa + 2 * sa * i / N, w = wmax * Math.pow(Math.max(0, 1 - (s / sa) ** 2), 0.45); g.lineTo(s, edge(s) + w * 0.5) }
      for (let i = N; i >= 0; i--) { const s = -sa + 2 * sa * i / N, w = wmax * Math.pow(Math.max(0, 1 - (s / sa) ** 2), 0.45); g.lineTo(s, edge(s) - w * 0.5) }
      g.closePath(); g.fill()
      g.globalAlpha = 1
    }
  }
  // 하트 눈
  if (st.heart > 0.01) {
    const r = Math.min(A, B) * 0.95 * smooth(0, 1, st.heart)
    g.fillStyle = '#ee4d6e'
    g.beginPath()
    g.moveTo(0, -r * 0.85)
    g.bezierCurveTo(r * 1.35, -r * 0.05, r * 0.75, r * 0.95, 0, r * 0.38)
    g.bezierCurveTo(-r * 0.75, r * 0.95, -r * 1.35, -r * 0.05, 0, -r * 0.85)
    g.closePath(); g.fill()
    g.fillStyle = 'rgba(255,255,255,0.75)'
    g.beginPath(); g.ellipse(-r * 0.42, r * 0.38, r * 0.14, r * 0.1, 0.5, 0, Math.PI * 2); g.fill()
  }
  if (debug) {
    g.lineWidth = 0.003
    g.strokeStyle = '#00ffff'; g.beginPath(); g.ellipse(0, 0, eye.a, eye.b, 0, 0, Math.PI * 2); g.stroke()
    g.strokeStyle = eye.found ? '#00ff00' : '#ff0000'; g.beginPath(); g.ellipse(0, 0, A, B, 0, 0, Math.PI * 2); g.stroke()
  }
  g.restore()
  p.tex.needsUpdate = true
}

interface MouthState { open: number; smile: number; kiss: number; alpha: number; rest: number }

/** 입이 닫혀 있을 때의 미소 호(∪) 폭 = 눈 사이 거리 x 0.55, 처짐 = 폭 x 0.18 */
const SMILE_W = 0.55, SMILE_SAG = 0.18, SMILE_COL = '#a45c48'

function drawMouth(p: Patch, ox: number, oy: number, mw: number, eyeDist: number, skinTop: RGB, skinBot: RGB, st: MouthState) {
  const g = p.begin()
  g.translate(ox, oy) // 입 중심이 원점
  if (st.rest > 0.01) {
    // 닫힌 입의 부드러운 미소: 양끝이 가늘어지는 호. 웃음 값에 따라 처짐이 커진다
    const W = SMILE_W * eyeDist
    const sm = clamp(st.smile, -1, 1)
    const sag = SMILE_SAG * W * clamp(0.7 + 0.7 * sm, 0.05, 1.5)
    const thick = 0.022
    const N = 28
    const cy = (s: number) => -sag * (1 - (2 * s / W) ** 2) // 가운데가 가장 낮은 ∪
    const tw = (s: number) => thick * Math.pow(Math.max(0, 1 - (2 * s / W) ** 2), 0.5)
    g.save()
    g.filter = 'blur(0.7px)'
    g.globalAlpha = st.rest * 0.9
    g.fillStyle = SMILE_COL
    g.beginPath()
    for (let i = 0; i <= N; i++) { const s = -W / 2 + W * i / N; g.lineTo(s, cy(s) + tw(s) / 2) }
    for (let i = N; i >= 0; i--) { const s = -W / 2 + W * i / N; g.lineTo(s, cy(s) - tw(s) / 2) }
    g.closePath(); g.fill()
    // 입꼬리의 작은 위쪽 꼬리
    if (sm > -0.2) {
      for (const sd of [-1, 1]) {
        g.beginPath()
        g.moveTo(sd * W / 2, 0.003)
        g.quadraticCurveTo(sd * (W / 2 + 0.012), 0.008, sd * (W / 2 + 0.016), 0.02)
        g.quadraticCurveTo(sd * (W / 2 + 0.006), 0.012, sd * (W / 2 - 0.004), -0.003)
        g.closePath(); g.fill()
      }
    }
    g.restore()
  }
  if (st.kiss > 0.01) {
    // 구운 웃는 입선을 피부로 덮고(가장자리는 서서히 지움) 작은 뽀뽀 입을 그린다
    const ka = smooth(0, 0.6, st.kiss)
    g.save()
    g.globalAlpha = ka
    const grad = g.createLinearGradient(0, 0.05, 0, -0.05)
    grad.addColorStop(0, css(skinTop)); grad.addColorStop(1, css(skinBot))
    g.fillStyle = grad
    g.fillRect(-0.3, -0.07, 0.6, 0.14)
    featherEllipse(g, mw * 0.62, 0.05, mw * 0.5)
    g.restore()
    const r = 0.046 * (0.6 + 0.4 * st.kiss)
    g.globalAlpha = ka
    g.fillStyle = '#cf5f5e'
    g.beginPath(); g.ellipse(0, -0.004, r * 1.2, r, 0, 0, Math.PI * 2); g.fill()
    g.fillStyle = '#6e2530'
    g.beginPath(); g.ellipse(0, -0.004, r * 0.5, r * 0.2, 0, 0, Math.PI * 2); g.fill()
    g.fillStyle = 'rgba(255,255,255,0.3)'
    g.beginPath(); g.ellipse(-r * 0.4, r * 0.45, r * 0.32, r * 0.16, 0, 0, Math.PI * 2); g.fill()
    g.globalAlpha = 1
  }
  if (st.alpha > 0.01) {
    const o = st.open, sm = st.smile
    const W = mw * clamp(0.36 + 0.26 * o + 0.1 * sm, 0.3, 0.82)
    const H = 0.012 + o * 0.15
    const lift = 0.016 * sm + 0.006
    const y0 = 0.002
    g.globalAlpha = st.alpha
    const path = () => {
      g.beginPath()
      g.moveTo(-W / 2, y0 + lift)
      g.quadraticCurveTo(0, y0 - lift * 0.9 - 0.004, W / 2, y0 + lift)
      g.bezierCurveTo(W * 0.46, y0 - H * 1.3, -W * 0.46, y0 - H * 1.3, -W / 2, y0 + lift)
      g.closePath()
    }
    g.save()
    path()
    const grad = g.createLinearGradient(0, y0, 0, y0 - H)
    grad.addColorStop(0, '#3b141a'); grad.addColorStop(1, '#69272e')
    g.fillStyle = grad
    g.fill()
    g.clip()
    if (H > 0.05) {
      g.fillStyle = '#d4707b'
      g.beginPath(); g.ellipse(0, y0 - H * 0.86, W * 0.3, H * 0.3, 0, 0, Math.PI * 2); g.fill()
      g.fillStyle = 'rgba(160,60,75,0.55)'
      g.beginPath(); g.ellipse(0, y0 - H * 0.7, W * 0.04, H * 0.14, 0, 0, Math.PI * 2); g.fill()
    }
    g.restore()
    g.lineWidth = 0.0055; g.lineJoin = 'round'
    g.strokeStyle = 'rgba(122,52,52,0.6)'
    path(); g.stroke()
    g.globalAlpha = 1
  }
  p.tex.needsUpdate = true
}

function drawBlush(p: Patch) {
  const g = p.begin()
  const rg = g.createRadialGradient(0, 0, 0, 0, 0, 0.5)
  rg.addColorStop(0, 'rgba(241,154,140,0.95)'); rg.addColorStop(0.45, 'rgba(241,154,140,0.6)'); rg.addColorStop(1, 'rgba(241,154,140,0)')
  g.fillStyle = rg
  g.save(); g.scale(0.15, 0.1)
  g.beginPath(); g.arc(0, 0, 0.5, 0, Math.PI * 2); g.fill()
  g.restore()
  p.tex.needsUpdate = true
}

/* ------------------------------------------------------------------ */
/* 공개 함수                                                            */
/* ------------------------------------------------------------------ */

export function createFaceOverlay(head: T.Bone, rig: NavyRig): { root: T.Object3D; update(f: RigFrame, dt: number): void } {
  const root = new T.Group()
  root.name = 'face_overlay'
  head.add(root)
  const noop = { root, update() {} }
  const t0 = performance.now()

  // 몸 메시 찾기 (head 의 조상 꼭대기에서 SkinnedMesh)
  let top: T.Object3D = head
  while (top.parent) top = top.parent
  let body: T.SkinnedMesh | null = null
  top.traverse(o => {
    const m = o as T.SkinnedMesh
    if (m.isSkinnedMesh && (!body || m.name === 'navy_body')) body = m
  })
  const bodyMesh = body as T.SkinnedMesh | null
  const eyeLd = rig.face.eyeL, eyeRd = rig.face.eyeR, mouthD = rig.face.mouth
  if (!bodyMesh || !eyeLd || !eyeRd || !mouthD) return noop

  let hf: Heightfield, toLocal: T.Matrix4
  try {
    top.updateWorldMatrix(false, true)
    head.updateWorldMatrix(true, false)
    toLocal = head.matrixWorld.clone().invert()
    hf = buildHeightfield(bodyMesh)
  } catch (e) {
    console.warn('faceOverlay: 높이장 실패', e)
    return noop
  }
  const debug = new URLSearchParams(location.search).get('facedebug') === '1'
  const tex = makeTexReader((bodyMesh.material as T.MeshStandardMaterial).map ?? null)

  const eyeW = (eyeLd.width + eyeRd.width) / 2
  const eyeDist = Math.abs(eyeLd.center[0] - eyeRd.center[0])
  const eL = detectEye(hf, tex, eyeLd.center[0], eyeLd.center[1] - 0.02, eyeW)
  const eR = detectEye(hf, tex, eyeRd.center[0], eyeRd.center[1] - 0.02, eyeW)
  const eyeSize = (e: EyeShape) => 2 * (Math.max(e.a, e.b) + EYE_OUT + 0.02)
  const sizeEye = Math.max(eyeSize(eL), eyeSize(eR))
  const patchEL = makePatch(hf, eL.cx, eL.cy, sizeEye, sizeEye, 192, 28, toLocal, root, 5)
  const patchER = makePatch(hf, eR.cx, eR.cy, sizeEye, sizeEye, 192, 28, toLocal, root, 5)

  // 입
  const mx = mouthD.center[0], mw = mouthD.width
  const my = detectMouthY(hf, tex, mouthD.center[0], mouthD.center[1]) ?? mouthD.center[1]
  // 입선 바로 위·아래 피부색 (뽀뽀 때 구운 입선을 덮는 데 쓴다)
  const rowSkin = (y0: number, y1: number): RGB => {
    const cs: RGB[] = []
    if (tex) {
      for (let j = Math.floor((y0 - HY0) / CELL); j <= Math.floor((y1 - HY0) / CELL); j++) {
        for (let i = Math.floor((mx - 0.1 - HX0) / CELL); i <= Math.floor((mx + 0.1 - HX0) / CELL); i++) {
          const k = j * hf.nx + i
          const c = tex(hf.u[k]!, hf.v[k]!)
          if (luma(c) > 140 && c[0] - c[2] > 25) cs.push(c)
        }
      }
    }
    return cs.length > 20 ? medianRGB(cs) : DEFAULT_SKIN
  }
  const mSkinTop = rowSkin(my + 0.035, my + 0.065), mSkinBot = rowSkin(my - 0.065, my - 0.035)
  const msx = mw * 1.5, msy = 0.46
  const patchM = makePatch(hf, mx, my - 0.1, msx, msy, 256, 32, toLocal, root, 5)
  // 입 패치의 중심은 (mx, my-0.1): 그리기 좌표를 입 중심으로 옮기려고 오프셋을 둔다
  const mOffY = 0.1

  // 볼터치
  const blushR = makePatch(hf, eR.cx + 0.03, eR.cy - 0.2, 0.34, 0.26, 128, 16, toLocal, root, 4)
  const blushL = makePatch(hf, eL.cx - 0.03, eL.cy - 0.2, 0.34, 0.26, 128, 16, toLocal, root, 4)
  drawBlush(blushR); drawBlush(blushL)
  ;(blushR.mesh.material as T.MeshStandardMaterial).opacity = 0
  ;(blushL.mesh.material as T.MeshStandardMaterial).opacity = 0

  const stL: EyeState = { lid: 0, arch: 0, heart: 0, gaze: 0 }, stR: EyeState = { lid: 0, arch: 0, heart: 0, gaze: 0 }
  const keyL = { v: '' }, keyR = { v: '' }, keyM = { v: '' }
  let closeFx = 0, archFx = 0, heartFx = 0, openS = 0, smileS = 0.15, kissS = 0, gazeS = 0

  const q = (x: number, n: number) => Math.round(x * n)

  if (debug) {
    const g = patchM.begin(); g.translate(0, mOffY)
    g.strokeStyle = '#ff00ff'; g.lineWidth = 0.002
    g.beginPath(); g.moveTo(-mw / 2, 0); g.lineTo(mw / 2, 0); g.moveTo(0, -0.03); g.lineTo(0, 0.03); g.stroke()
    patchM.tex.needsUpdate = true; patchM.mesh.visible = true
    for (const [p, e] of [[patchEL, eL], [patchER, eR]] as const) { p.mesh.visible = true; drawEye(p, e, { lid: 0, arch: 0, heart: 0, gaze: 0 }, true) }
  }

  if (debug) console.log(`faceOverlay: 준비 ${(performance.now() - t0).toFixed(0)}ms, 눈 ${eL.found}/${eR.found}, 입 y=${my.toFixed(3)}`)

  return {
    root,
    update(f: RigFrame, dt: number) {
      const fx = f.fx
      const k = 1 - Math.exp(-dt * 18)
      const happy = !!fx.happy, sleepy = !!fx.sleepy
      closeFx += ((happy || sleepy ? 1 : 0) - closeFx) * k
      archFx += ((happy ? 1 : 0) - archFx) * k
      heartFx += ((fx.heart ? 1 : 0) - heartFx) * k
      // 눈
      const lidL = Math.max(clamp(f.blinkL, 0, 1), closeFx), lidR = Math.max(clamp(f.blinkR, 0, 1), closeFx)
      const heart = heartFx
      // 눈동자: 고개 방향으로 조금 더 흘끗 + 트래킹 gaze (눈 반폭의 ±0.15)
      gazeS += (clamp(f.head.yaw * 0.22 + f.gaze.x * 0.1, -0.15, 0.15) - gazeS) * k
      for (const [p, e, s, key, lid] of [[patchEL, eL, stL, keyL, lidL], [patchER, eR, stR, keyR, lidR]] as const) {
        s.lid = lid; s.arch = archFx; s.heart = heart; s.gaze = gazeS
        const kk = `${q(lid, 40)}|${q(archFx, 20)}|${q(heart, 20)}|${q(gazeS, 60)}`
        if (kk === key.v) continue
        key.v = kk
        const vis = e.found || lid > 0.012 || heart > 0.01 || debug
        p.mesh.visible = vis
        if (vis) drawEye(p, e, s, debug)
      }
      // 입
      const surprised = !!fx.surprised
      const openT = surprised ? Math.max(f.mouthOpen, 0.5) : f.mouthOpen
      const smileT = surprised ? -0.2 : f.mouthSmile
      const km = 1 - Math.exp(-dt * 30)
      openS += (clamp(openT, 0, 1) - openS) * km
      smileS += (clamp(smileT, -1, 1) - smileS) * km
      kissS += ((fx.kiss ? 1 : 0) - kissS) * (1 - Math.exp(-dt * 20))
      const noKiss = 1 - smooth(0.2, 0.6, kissS)
      const alpha = smooth(0.06, 0.1, openS) * noKiss
      const rest = (1 - smooth(0.05, 0.09, openS)) * noKiss
      const mk = `${q(openS, 64)}|${q(smileS, 40)}|${q(kissS, 20)}|${q(alpha, 20)}|${q(rest, 20)}`
      if (mk !== keyM.v) {
        keyM.v = mk
        const vis = alpha > 0.01 || kissS > 0.01 || rest > 0.01
        patchM.mesh.visible = vis
        if (vis) {
          // 패치 중심은 입 중심보다 mOffY 아래라서 그리기 원점을 위로 옮긴다
          drawMouth(patchM, 0, mOffY, mw, eyeDist, mSkinTop, mSkinBot, { open: openS, smile: smileS, kiss: kissS, alpha, rest })
        }
      }
      // 볼터치
      const b = clamp(fx.blush ?? 0, 0, 1)
      // 평소에도 연한 볼터치(기본 0.3), fx.blush 가 켜지면 진해진다
      const bo = Math.min(1, Math.max(b, 0.3) * 1.2)
      for (const p of [blushL, blushR]) {
        const m = p.mesh.material as T.MeshStandardMaterial
        if (Math.abs(m.opacity - bo) > 0.004) m.opacity = bo
        p.mesh.visible = bo > 0.01
      }
    },
  }

}
