import * as T from 'three'
import type { RigFrame } from '../contract'

/**
 * 얼굴(눈·눈썹·입·볼터치)을 캔버스에 그려 Blender 의 face_decal 판에 입힌다.
 * 좌표는 머리 로컬(three, 두개골 중심 원점) 그대로다. 판 범위는 blender/build.py 의 데칼 격자와 같다.
 * 위치·크기는 reference/idle.png 를 머리 폭(0.68×2)에 맞춰 잰 값이다.
 */
export const DECAL = { x0: -0.56, x1: 0.56, y0: -0.68, y1: 0.52 }
const W = 1024, H = 1024
const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, Number.isFinite(v) ? v : 0))
const X = (x: number) => (x - DECAL.x0) / (DECAL.x1 - DECAL.x0) * W
const Y = (y: number) => (DECAL.y1 - y) / (DECAL.y1 - DECAL.y0) * H
const S = (d: number) => d / (DECAL.x1 - DECAL.x0) * W

const EYE_X = 0.30, EYE_Y = -0.17, EYE_RX = 0.098, EYE_RY = 0.112
const BROW_Y = 0.06
const MOUTH_Y = -0.55

/** 판 정점 위치(머리 로컬)로 UV 를 다시 계산한다 */
export function decalUVs(g: T.BufferGeometry) {
  const p = g.attributes.position, uv = new Float32Array(p.count * 2)
  for (let i = 0; i < p.count; i++) {
    uv[i * 2] = (p.getX(i) - DECAL.x0) / (DECAL.x1 - DECAL.x0)
    uv[i * 2 + 1] = (p.getY(i) - DECAL.y0) / (DECAL.y1 - DECAL.y0)
  }
  g.setAttribute('uv', new T.BufferAttribute(uv, 2))
}

export function createFace() {
  const canvas = document.createElement('canvas'); canvas.width = W; canvas.height = H
  const c = canvas.getContext('2d')!
  const texture = new T.CanvasTexture(canvas)
  texture.colorSpace = T.SRGBColorSpace; texture.anisotropy = 4
  const material = new T.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, toneMapped: false })

  const ellipse = (x: number, y: number, rx: number, ry: number, color: string, rot = 0) => {
    c.fillStyle = color; c.beginPath(); c.ellipse(X(x), Y(y), S(rx), S(ry), rot, 0, Math.PI * 2); c.fill()
  }
  const curve = (pts: number[], color: string, width: number) => {
    c.strokeStyle = color; c.lineWidth = S(width); c.lineCap = 'round'; c.beginPath()
    c.moveTo(X(pts[0]), Y(pts[1])); c.quadraticCurveTo(X(pts[2]), Y(pts[3]), X(pts[4]), Y(pts[5])); c.stroke()
  }

  let signature = ''
  function update(f: RigFrame) {
    const blush = clamp(f.fx.blush ?? 0)
    const values = [f.blinkL, f.blinkR, f.gaze.x, f.gaze.y, f.browL, f.browR, f.mouthOpen, f.mouthSmile, blush]
    const sig = values.map(v => Math.round(v * 40)).join(',') + JSON.stringify(f.fx)
    if (sig === signature) return
    signature = sig
    c.clearRect(0, 0, W, H)

    for (const side of [-1, 1]) {
      // 볼터치: 아주 옅게 (레퍼런스는 거의 안 보일 만큼)
      const bx = side * 0.40, by = -0.43
      const g = c.createRadialGradient(X(bx), Y(by), 1, X(bx), Y(by), S(0.13))
      g.addColorStop(0, `rgba(236,128,118,${0.20 + blush * 0.35})`); g.addColorStop(1, 'rgba(236,128,118,0)')
      c.fillStyle = g; c.fillRect(X(bx) - S(0.14), Y(by) - S(0.14), S(0.28), S(0.28))

      const x = side * EYE_X, y = EYE_Y
      const blink = clamp(((side === 1 ? f.blinkL : f.blinkR) - 0.08) / 0.78)
      const open = f.fx.sleepy ? 0 : 1 - blink
      if (f.fx.happy || open < 0.1) {
        // 감은 눈 / 웃는 눈: 아래로 볼록한 선
        curve([x - 0.09, y - 0.01, x, y + (f.fx.happy ? 0.06 : -0.03), x + 0.09, y - 0.01], '#2a1d18', 0.022)
      } else {
        c.save()
        c.translate(X(x), Y(y)); c.scale(1, Math.max(0.06, open)); c.translate(-X(x), -Y(y))
        const gx = x + clamp(f.gaze.x, -1, 1) * 0.02, gy = y + clamp(f.gaze.y, -1, 1) * 0.015
        if (f.fx.heart) {
          c.fillStyle = '#d85872'; c.font = `bold ${S(0.24)}px sans-serif`; c.textAlign = 'center'; c.textBaseline = 'middle'
          c.fillText('♥', X(x), Y(y))
        } else {
          // 레퍼런스 눈: 흰자 없이 짙은 갈색 타원 + 아래쪽 밝은 갈색 + 큰 흰 하이라이트
          ellipse(gx, gy, EYE_RX, EYE_RY, '#1f1612')
          ellipse(gx, gy - 0.03, EYE_RX * 0.78, EYE_RY * 0.6, '#3d2a20')
          ellipse(gx + side * 0.0 - 0.035, gy + 0.045, 0.034, 0.038, '#ffffff')
          ellipse(gx + 0.035, gy - 0.05, 0.013, 0.013, 'rgba(255,255,255,.85)')
        }
        c.restore()
        // 윗눈꺼풀 선
        curve([x - EYE_RX * 1.05, y + EYE_RY * 0.35 * open, x, y + EYE_RY * 1.1 * open, x + EYE_RX * 1.05, y + EYE_RY * 0.35 * open], '#1a120f', 0.016)
      }
      // 눈썹: 짧고 굵은 일자에 가까운 아치. 바깥쪽이 살짝 내려간다
      const brow = side === 1 ? f.browL : f.browR
      const ang = f.fx.angry ? -0.04 : 0
      const byy = BROW_Y + brow * 0.04
      curve([x - side * 0.10, byy - 0.005 - side * ang, x, byy + 0.03, x + side * 0.11, byy - 0.02 + side * ang], '#17120f', 0.05)
    }

    // 입: 작은 미소. 벌리면 짙은 입 안 + 혀
    const smile = clamp(f.mouthSmile, -1, 1), open = clamp((f.mouthOpen - 0.03) / 0.65)
    const w = 0.10 + Math.max(0, smile) * 0.02, my = MOUTH_Y
    if (f.fx.kiss) {
      curve([-0.02, my + 0.03, 0.04, my + 0.01, -0.01, my], '#9c5447', 0.012)
      curve([-0.01, my, 0.04, my - 0.02, -0.02, my - 0.035], '#9c5447', 0.012)
    } else if (open > 0.06) {
      c.fillStyle = '#5a2f2b'; c.beginPath()
      c.moveTo(X(-w), Y(my + 0.02)); c.quadraticCurveTo(X(0), Y(my - 0.005), X(w), Y(my + 0.02))
      c.bezierCurveTo(X(w * 0.85), Y(my - 0.12 * open - 0.02), X(-w * 0.85), Y(my - 0.12 * open - 0.02), X(-w), Y(my + 0.02)); c.fill()
      if (open > 0.3) ellipse(0, my - 0.075 * open, 0.045, 0.016, '#d0807a')
    } else {
      curve([-w, my + 0.02, 0, my - (0.035 + smile * 0.03), w, my + 0.02], '#9a5546', 0.016)
    }
    texture.needsUpdate = true
  }
  return { material, update }
}
