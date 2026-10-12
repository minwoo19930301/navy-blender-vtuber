// "가짜 사람" 배우 — 휴머노이드 VRM을 웹캠 화각으로 렌더해 트래킹 E2E 입력 영상을 만든다.
// 포즈는 해부학적 좌우로 지정한다 (rightUpperArm = 배우 본인의 오른팔 = 카메라 영상의 왼쪽).
// 부호(ARM_SIGN/YAW_SIGN)는 Sendagaya Shino(VRM0) + VRMUtils.rotateVRM0 기준으로 스틸 확인을 거쳐 정했다.
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm'

const W = 640
const H = 480
const canvas = document.getElementById('c')
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true })
renderer.setPixelRatio(1)
renderer.setSize(W, H, false)
renderer.setClearColor(0xcfcac2, 1)
const scene = new THREE.Scene()
scene.add(new THREE.AmbientLight(0xffffff, 1.2))
const sun = new THREE.DirectionalLight(0xffffff, 1.6)
sun.position.set(0.5, 1.5, 2)
scene.add(sun)
const cam = new THREE.PerspectiveCamera(50, W / H, 0.05, 20)

const ARM_SIGN = -1 // 오른팔을 T포즈에서 내리는 z회전 부호
const YAW_SIGN = -1 // 배우 본인 오른쪽으로 고개

const loader = new GLTFLoader()
loader.register((p) => new VRMLoaderPlugin(p))
const gltf = await loader.loadAsync('./actor.vrm')
const vrm = gltf.userData.vrm
if (vrm.meta?.metaVersion === '0') VRMUtils.rotateVRM0(vrm)
scene.add(vrm.scene)
vrm.update(0)

const bone = (n) => vrm.humanoid.getNormalizedBoneNode(n)
const head = bone('head').getWorldPosition(new THREE.Vector3())
const hips = bone('hips').getWorldPosition(new THREE.Vector3())
const top = head.y + 0.28
const bottom = hips.y - 0.02
const midY = (top + bottom) / 2
const visH = (top - bottom) * 1.3
cam.position.set(0, midY + 0.05, visH / 2 / Math.tan(THREE.MathUtils.degToRad(25)))
cam.lookAt(0, midY, 0)

const smooth = (a, b, t) => { const x = Math.min(1, Math.max(0, (t - a) / (b - a))); return x * x * (3 - 2 * x) }
const pulse = (t, t0, t1) => smooth(t0, t0 + 0.5, t) * (1 - smooth(t1 - 0.5, t1, t))

// [이름, 시작, 끝] — run.mjs의 단언과 같은 표를 공유한다 (window.TIMELINE)
const TIMELINE = [
  ['neutral', 0, 2], ['rightArmSide', 2, 4.5], ['leftArmSide', 4.5, 7], ['rightWave', 7, 9.5],
  ['headRight', 9.5, 12], ['mouthOpen', 12, 14], ['blink', 14, 16], ['rightFist', 16, 18.5],
]
const DURATION = 18.5
const FINGERS = ['Index', 'Middle', 'Ring', 'Little']

function apply(t) {
  const p = {}
  for (const [name, a, b] of TIMELINE) p[name] = pulse(t, a, b)
  const DOWN = 1.25
  const rUp = Math.max(p.rightArmSide, (p.rightWave + p.rightFist) * 0.85)
  bone('rightUpperArm').rotation.set(0, 0, ARM_SIGN * DOWN * (1 - rUp))
  bone('rightLowerArm').rotation.set(0, 0, ARM_SIGN * -1.5 * (p.rightWave + p.rightFist))
  bone('leftUpperArm').rotation.set(0, 0, -ARM_SIGN * DOWN * (1 - p.leftArmSide))
  bone('leftLowerArm').rotation.set(0, 0, 0)
  for (const f of FINGERS) for (const seg of ['Proximal', 'Intermediate', 'Distal']) {
    const n = bone(`right${f}${seg}`)
    if (n) n.rotation.set(0, 0, ARM_SIGN * 1.45 * p.rightFist)
  }
  bone('head').rotation.set(0, YAW_SIGN * 0.6 * p.headRight, 0)
  vrm.expressionManager.setValue('aa', p.mouthOpen)
  vrm.expressionManager.setValue('blink', p.blink)
  vrm.update(0)
}

// RGB → YUV420(BT.601 full range, y4m C420jpeg) — ffmpeg 없이 Chrome 가짜 카메라용 영상을 만든다
const c2d = document.createElement('canvas')
c2d.width = W
c2d.height = H
const ctx = c2d.getContext('2d', { willReadFrequently: true })
function yuvBase64() {
  ctx.drawImage(canvas, 0, 0)
  const px = ctx.getImageData(0, 0, W, H).data
  const out = new Uint8Array(W * H * 1.5)
  const U0 = W * H
  const V0 = U0 + (W / 2) * (H / 2)
  for (let i = 0, j = 0; i < W * H; i++, j += 4) {
    out[i] = Math.round(0.299 * px[j] + 0.587 * px[j + 1] + 0.114 * px[j + 2])
  }
  for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) {
    let r = 0, g = 0, b = 0
    for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
      const j = ((y + dy) * W + x + dx) * 4
      r += px[j]; g += px[j + 1]; b += px[j + 2]
    }
    r /= 4; g /= 4; b /= 4
    const k = (y / 2) * (W / 2) + x / 2
    out[U0 + k] = Math.max(0, Math.min(255, Math.round(-0.168736 * r - 0.331264 * g + 0.5 * b + 128)))
    out[V0 + k] = Math.max(0, Math.min(255, Math.round(0.5 * r - 0.418688 * g - 0.081312 * b + 128)))
  }
  let s = ''
  for (let i = 0; i < out.length; i += 0x8000) s += String.fromCharCode.apply(null, out.subarray(i, i + 0x8000))
  return btoa(s)
}

window.ACTOR = { W, H, DURATION, TIMELINE }
window.frameYuvAt = (t) => { apply(t); renderer.render(scene, cam); return yuvBase64() }
window.framePngAt = (t) => { apply(t); renderer.render(scene, cam); return canvas.toDataURL('image/png') }
apply(0)
renderer.render(scene, cam)
document.title = 'READY'
