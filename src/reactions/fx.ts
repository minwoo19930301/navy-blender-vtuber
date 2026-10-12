/**
 * 리액션 FX — 하트·반짝이·꽃·색종이·느낌표·땀방울·분노 마크·z·먼지를 three.js Sprite 로 띄운다.
 *
 * - 텍스처는 캔버스로 절차적으로 그린다 (외부 파일 없음). 종류당 한 장, 모듈 전역이 아니라 Fx 인스턴스가 소유한다 (dispose 가능).
 * - 스프라이트는 풀(POOL)로 미리 만들어 두고 재사용한다. 스프라이트마다 SpriteMaterial 이 따로 있어 불투명도·색을 개별로 준다 (맵만 바꿔 끼운다).
 * - 위치·크기·불투명도는 전부 나이(age)의 닫힌 식이라 같은 (시드, 시각)이면 같은 그림이 나온다 (Math.random() 없음). 프레임 사이에 객체를 만들지 않는다.
 * - FX 는 화면 위에 얹는 평면 그래픽이다 (depthTest 끔, 항상 공 앞에 그림).
 */
import * as THREE from 'three'
import { TAU, easeOutBack, ss } from './util'

export const FxKind = {
  heart: 0,
  sparkle: 1,
  flowerA: 2,
  flowerB: 3,
  flowerC: 4,
  confetti: 5,
  exclaim: 6,
  sweat: 7,
  anger: 8,
  z: 9,
  puff: 10,
} as const
export type FxKindId = (typeof FxKind)[keyof typeof FxKind]
const KIND_COUNT = 11

const TEX = 160
const POOL = 96
/** FX 가 놓이는 z (공 중심 평면 앞). depthTest 가 꺼져 있어 그리기 순서만 renderOrder 가 정한다 */
const FX_Z = 0.45

/** 색종이 팔레트 (밝은 파스텔 말고 공식 소품처럼 선명한 색) */
export const CONFETTI_COLORS: readonly number[] = [0xf2594b, 0x4da3f5, 0x55c45a, 0xa878e0, 0xff8fb8, 0xffa51f, 0x2fc4c9]

/** 풀 하나의 상태. 닫힌 식으로 위치를 계산하므로 속도·감쇠·중력만 들고 있다 */
export class Particle {
  alive = false
  kind = 0
  /** 생길 때의 절대 위치(월드)와 그때 앵커 위치 (follow 용) */
  ox = 0
  oy = 0
  ax0 = 0
  ay0 = 0
  /** 초속과 감쇠(1/s), 중력(+는 아래로 가속) */
  vx = 0
  vy = 0
  kx = 2
  ky = 2
  g = 0
  born = 0
  /** 생성 후 이만큼 지나야 보인다 (한 번에 터뜨린 입자를 어긋나게) */
  delay = 0
  life = 1
  size = 0.1
  /** 세로/가로 */
  aspect = 1
  /** 수명 후반에 줄어드는 비율 */
  shrink = 0
  /** 팝 시간(초) */
  pop = 0.18
  rot = 0
  spin = 0
  swayAmp = 0
  swayF = 0
  swayPh = 0
  pulseAmp = 0
  pulseF = 0
  /** 초당 커지는 비율 (먼지·김이 퍼진다) */
  grow = 0
  /** 반짝임(크기가 흔들리는) 비율 */
  twinkle = 0
  /** 색종이가 뒤집히는 정도 0..1 와 속도 */
  flutter = 0
  flutterF = 0
  flutterPh = 0
  /** 몸을 따라 움직이는 비율 0..1 */
  follow = 0
  color = 0xffffff
  alpha = 1
  /** 페이드 아웃이 시작되는 수명 비율 */
  fadeAt = 0.72
}

export interface FxAnchor {
  /** 공 중심 월드 좌표 (몸이 뛰면 같이 움직인다) */
  x: number
  y: number
}

export interface Fx {
  root: THREE.Group
  anchor: FxAnchor
  /** 현재 시각(초). update 가 갱신한다 */
  now: number
  /** 비어 있는 입자 하나를 기본값으로 초기화해 내준다. 풀이 가득 차면 null. 위치는 앵커 기준 오프셋 */
  emit(kind: FxKindId, offX: number, offY: number): Particle | null
  update(now: number): void
  /** 살아 있는 입자를 빠르게 사라지게 한다 (취소) */
  fadeAll(now: number, sec: number): void
  alive(): number
  dispose(): void
}

type Draw = (c: CanvasRenderingContext2D, S: number) => void

function makeTex(draw: Draw): THREE.CanvasTexture {
  const cv = document.createElement('canvas')
  cv.width = TEX
  cv.height = TEX
  const c = cv.getContext('2d')!
  c.clearRect(0, 0, TEX, TEX)
  c.translate(TEX / 2, TEX / 2)
  draw(c, TEX / 2)
  const t = new THREE.CanvasTexture(cv)
  t.colorSpace = THREE.SRGBColorSpace
  t.generateMipmaps = true
  t.minFilter = THREE.LinearMipmapLinearFilter
  t.magFilter = THREE.LinearFilter
  return t
}

/* ---------------- 텍스처 그리기: 단위는 반지름 S (캔버스 중심이 원점, +y 는 아래) ---------------- */

const heartPath = (c: CanvasRenderingContext2D, u: number, cy = 0) => {
  c.beginPath()
  c.moveTo(0, cy + u * 0.92)
  c.bezierCurveTo(-u * 1.5, cy + u * 0.05, -u * 1.0, cy - u * 0.95, 0, cy - u * 0.32)
  c.bezierCurveTo(u * 1.0, cy - u * 0.95, u * 1.5, cy + u * 0.05, 0, cy + u * 0.92)
  c.closePath()
}

const drawHeart: Draw = (c, S) => {
  const u = S * 0.62
  heartPath(c, u)
  const g = c.createLinearGradient(-u, -u, u * 0.8, u)
  g.addColorStop(0, '#FF7A6E')
  g.addColorStop(0.55, '#F2504A')
  g.addColorStop(1, '#DC3B3F')
  c.fillStyle = g
  c.fill()
  // 위쪽 왼쪽 광택
  c.fillStyle = 'rgba(255,255,255,0.5)'
  c.beginPath()
  c.ellipse(-u * 0.55, -u * 0.35, u * 0.2, u * 0.12, -0.7, 0, TAU)
  c.fill()
}

const drawSparkle: Draw = (c, S) => {
  // 부드러운 빛번짐
  const gl = c.createRadialGradient(0, 0, 0, 0, 0, S)
  gl.addColorStop(0, 'rgba(255,236,120,0.85)')
  gl.addColorStop(0.35, 'rgba(255,224,70,0.35)')
  gl.addColorStop(1, 'rgba(255,224,70,0)')
  c.fillStyle = gl
  c.fillRect(-S, -S, 2 * S, 2 * S)
  // 오목한 네 꼭짓점 별
  const R = S * 0.92
  const k = S * 0.11
  c.beginPath()
  c.moveTo(0, -R)
  c.quadraticCurveTo(k, -k, R * 0.72, 0)
  c.quadraticCurveTo(k, k, 0, R)
  c.quadraticCurveTo(-k, k, -R * 0.72, 0)
  c.quadraticCurveTo(-k, -k, 0, -R)
  c.closePath()
  const g = c.createRadialGradient(0, 0, 0, 0, 0, R)
  g.addColorStop(0, '#FFFFFF')
  g.addColorStop(0.3, '#FFF59A')
  g.addColorStop(1, '#FFD62B')
  c.fillStyle = g
  c.fill()
}

const flowerDraw = (petal: string, petalLight: string, center: string): Draw => (c, S) => {
  const pr = S * 0.34
  const ring = S * 0.46
  for (let i = 0; i < 5; i++) {
    const a = -Math.PI / 2 + (TAU * i) / 5
    const px = Math.cos(a) * ring
    const py = Math.sin(a) * ring
    const g = c.createRadialGradient(px - pr * 0.3, py - pr * 0.3, 0, px, py, pr)
    g.addColorStop(0, petalLight)
    g.addColorStop(1, petal)
    c.fillStyle = g
    c.beginPath()
    c.arc(px, py, pr, 0, TAU)
    c.fill()
  }
  c.fillStyle = center
  c.beginPath()
  c.arc(0, 0, S * 0.26, 0, TAU)
  c.fill()
  c.fillStyle = 'rgba(255,255,255,0.45)'
  c.beginPath()
  c.arc(-S * 0.07, -S * 0.08, S * 0.08, 0, TAU)
  c.fill()
}

/** 색종이: 모서리가 아주 둥근 도톰한 알약 모양 (가는 막대로 보이면 잡음 같아서). 가로세로비는 입자의 aspect 가 정한다 */
const drawConfetti: Draw = (c, S) => {
  c.fillStyle = '#FFFFFF'
  c.beginPath()
  c.roundRect(-S * 0.7, -S * 0.5, S * 1.4, S * 1.0, S * 0.5)
  c.fill()
}

const drawExclaim: Draw = (c, S) => {
  const bar = () => {
    c.beginPath()
    c.moveTo(-S * 0.27, -S * 0.82)
    c.quadraticCurveTo(0, -S * 0.98, S * 0.27, -S * 0.82)
    c.lineTo(S * 0.12, S * 0.22)
    c.quadraticCurveTo(0, S * 0.3, -S * 0.12, S * 0.22)
    c.closePath()
  }
  // 흰 테두리 → 빨강 본체 (노랑 공 위에서도 읽히게)
  c.lineJoin = 'round'
  c.lineWidth = S * 0.2
  c.strokeStyle = '#FFFFFF'
  bar()
  c.stroke()
  c.beginPath()
  c.arc(0, S * 0.62, S * 0.17, 0, TAU)
  c.stroke()
  c.fillStyle = '#F2503C'
  bar()
  c.fill()
  c.beginPath()
  c.arc(0, S * 0.62, S * 0.17, 0, TAU)
  c.fill()
}

const drawSweat: Draw = (c, S) => {
  const u = S * 0.5
  c.beginPath()
  c.moveTo(0, -u * 1.45)
  c.bezierCurveTo(u * 0.15, -u * 0.7, u * 0.95, -u * 0.3, u * 0.95, u * 0.35)
  c.bezierCurveTo(u * 0.95, u * 1.15, -u * 0.95, u * 1.15, -u * 0.95, u * 0.35)
  c.bezierCurveTo(-u * 0.95, -u * 0.3, -u * 0.15, -u * 0.7, 0, -u * 1.45)
  c.closePath()
  const g = c.createLinearGradient(0, -u, 0, u)
  g.addColorStop(0, '#B9E3FA')
  g.addColorStop(1, '#6DB8EE')
  c.fillStyle = g
  c.fill()
  c.lineWidth = S * 0.05
  c.strokeStyle = '#4C9AD8'
  c.stroke()
  c.fillStyle = 'rgba(255,255,255,0.85)'
  c.beginPath()
  c.ellipse(-u * 0.4, u * 0.25, u * 0.14, u * 0.28, 0.3, 0, TAU)
  c.fill()
}

const drawAnger: Draw = (c, S) => {
  // 💢: 네 개의 굽은 괄호가 가운데를 향한다
  c.lineCap = 'round'
  c.lineJoin = 'round'
  c.strokeStyle = '#E4463A'
  c.lineWidth = S * 0.2
  for (let q = 0; q < 4; q++) {
    const sx = q % 2 === 0 ? -1 : 1
    const sy = q < 2 ? -1 : 1
    c.beginPath()
    c.moveTo(sx * S * 0.8, sy * S * 0.2)
    c.quadraticCurveTo(sx * S * 0.2, sy * S * 0.2, sx * S * 0.2, sy * S * 0.8)
    c.stroke()
  }
}

const drawZ: Draw = (c, S) => {
  const path = () => {
    c.beginPath()
    c.moveTo(-S * 0.5, -S * 0.55)
    c.lineTo(S * 0.5, -S * 0.55)
    c.lineTo(-S * 0.5, S * 0.55)
    c.lineTo(S * 0.5, S * 0.55)
  }
  c.lineCap = 'round'
  c.lineJoin = 'round'
  c.lineWidth = S * 0.4
  c.strokeStyle = '#FFFFFF'
  path()
  c.stroke()
  c.lineWidth = S * 0.22
  c.strokeStyle = '#6F7FEF'
  path()
  c.stroke()
}

const drawPuff: Draw = (c, S) => {
  const g = c.createRadialGradient(0, 0, 0, 0, 0, S)
  g.addColorStop(0, 'rgba(242,246,250,0.95)')
  g.addColorStop(0.55, 'rgba(226,233,242,0.75)')
  g.addColorStop(1, 'rgba(210,220,232,0)')
  c.fillStyle = g
  c.beginPath()
  c.arc(0, 0, S, 0, TAU)
  c.fill()
}

const DRAWS: readonly Draw[] = [
  drawHeart,
  drawSparkle,
  flowerDraw('#9B78DE', '#C2A8F2', '#FFE066'),
  flowerDraw('#5FB0F2', '#A5D6FA', '#FFF3B0'),
  flowerDraw('#F2705A', '#FFA394', '#FFE066'),
  drawConfetti,
  drawExclaim,
  drawSweat,
  drawAnger,
  drawZ,
  drawPuff,
]

export function createFx(): Fx {
  const root = new THREE.Group()
  root.name = 'reactionFx'
  const textures: THREE.CanvasTexture[] = []
  for (let k = 0; k < KIND_COUNT; k++) textures.push(makeTex(DRAWS[k]))

  const parts: Particle[] = []
  const sprites: THREE.Sprite[] = []
  for (let i = 0; i < POOL; i++) {
    const mat = new THREE.SpriteMaterial({ map: textures[0], transparent: true, depthTest: false, depthWrite: false, toneMapped: false })
    const sp = new THREE.Sprite(mat)
    sp.visible = false
    sp.renderOrder = 20
    sp.position.z = FX_Z
    root.add(sp)
    sprites.push(sp)
    parts.push(new Particle())
  }

  const anchor: FxAnchor = { x: 0, y: 0.5 }
  let nAlive = 0
  let nextSlot = 0

  const fx: Fx = {
    root,
    anchor,
    now: 0,
    emit(kind, offX, offY) {
      // 빈 슬롯 찾기 (마지막 위치부터 순환)
      for (let n = 0; n < POOL; n++) {
        const i = (nextSlot + n) % POOL
        const p = parts[i]
        if (p.alive) continue
        nextSlot = (i + 1) % POOL
        p.alive = true
        p.kind = kind
        p.ox = anchor.x + offX
        p.oy = anchor.y + offY
        p.ax0 = anchor.x
        p.ay0 = anchor.y
        p.vx = 0; p.vy = 0; p.kx = 2; p.ky = 2; p.g = 0
        p.born = fx.now
        p.delay = 0
        p.life = 1.5
        p.size = 0.1
        p.aspect = 1
        p.shrink = 0
        p.pop = 0.18
        p.rot = 0; p.spin = 0
        p.swayAmp = 0; p.swayF = 0; p.swayPh = 0
        p.pulseAmp = 0; p.pulseF = 0
        p.grow = 0
        p.twinkle = 0
        p.flutter = 0; p.flutterF = 0; p.flutterPh = 0
        p.follow = 0
        p.color = 0xffffff
        p.alpha = 1
        p.fadeAt = 0.72
        sprites[i].material.map = textures[kind]
        nAlive++
        return p
      }
      return null
    },
    update(now) {
      fx.now = now
      if (nAlive === 0) return
      for (let i = 0; i < POOL; i++) {
        const p = parts[i]
        if (!p.alive) continue
        const sp = sprites[i]
        const age = now - p.born - p.delay
        if (age >= p.life) {
          p.alive = false
          sp.visible = false
          nAlive--
          continue
        }
        if (age < 0) {
          sp.visible = false
          continue
        }
        const ex = p.kx > 1e-4 ? (1 - Math.exp(-p.kx * age)) / p.kx : age
        const ey = p.ky > 1e-4 ? (1 - Math.exp(-p.ky * age)) / p.ky : age
        let x = p.ox + p.vx * ex
        let y = p.oy + p.vy * ey - 0.5 * p.g * age * age
        if (p.swayAmp !== 0) x += p.swayAmp * Math.sin(TAU * p.swayF * age + p.swayPh)
        if (p.follow !== 0) {
          x += p.follow * (anchor.x - p.ax0)
          y += p.follow * (anchor.y - p.ay0)
        }
        const u = age / p.life
        let s = p.size * (p.pop > 0 ? easeOutBack(age / p.pop) : 1)
        if (p.shrink > 0) s *= 1 - p.shrink * ss(0.4, 1, u)
        if (p.grow !== 0) s *= 1 + p.grow * age
        if (p.pulseAmp !== 0) s *= 1 + p.pulseAmp * Math.sin(TAU * p.pulseF * age)
        if (p.twinkle !== 0) s *= 1 - p.twinkle * (0.5 - 0.5 * Math.cos(TAU * 1.7 * age + p.swayPh))
        let sy = s * p.aspect
        if (p.flutter !== 0) sy *= 1 - p.flutter * (1 - Math.abs(Math.cos(p.flutterF * age + p.flutterPh)))
        sp.position.set(x, y, FX_Z)
        sp.scale.set(s, sy, 1)
        const m = sp.material
        m.rotation = p.rot + p.spin * age
        m.opacity = p.alpha * (1 - ss(p.fadeAt, 1, u))
        m.color.setHex(p.color)
        sp.visible = true
      }
    },
    fadeAll(now, sec) {
      for (let i = 0; i < POOL; i++) {
        const p = parts[i]
        if (!p.alive) continue
        const age = now - p.born - p.delay
        if (age < 0) {
          p.alive = false
          sprites[i].visible = false
          nAlive--
          continue
        }
        // 남은 수명을 sec 로 줄이고 페이드 시작점을 바로 앞으로 당긴다
        const newLife = Math.min(p.life, age + sec)
        p.fadeAt = Math.max(0, Math.min(p.fadeAt, age / newLife))
        p.life = newLife
      }
    },
    alive: () => nAlive,
    dispose() {
      for (const sp of sprites) sp.material.dispose()
      for (const t of textures) t.dispose()
      root.clear()
    },
  }
  return fx
}
