import * as T from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import type { ArmPose, Dir3, ModelAnchors, MingoModel, RigFrame } from '../contract'
import { neutralFrame, neutralArm } from '../contract'
import { createFaceOverlay, type NavyRig } from './faceOverlay'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { createBodyMaterial } from './materials'

/**
 * TRELLIS 메시 + Blender 뼈대(public/navy.glb, rig/rig.py)를 불러와 RigFrame 으로 뼈를 돌린다. 규약은 rig/CONTRACT.md.
 * 뼈마다 "월드(장면) 방향"을 직접 겨눈다: 뼈의 +Y 가 팔 방향이고, 뼈 roll 은 가정하지 않고 bind 시점 회전에서 읽는다.
 */
export const HEIGHT = 3.05
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, Number.isFinite(v) ? v : 0))
const UP = new T.Vector3(0, 1, 0)
const smoothstep = (a: number, b: number, x: number) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t) }

/**
 * 트래킹이 없을 때(arm.present=0)의 쉼 자세 (레퍼런스 idle-0): 팔꿈치는 몸 옆 아래, 하완은 앞·안쪽으로 뻗어 책상 위에 손바닥을 내려놓는다.
 * 방향은 왼팔 기준(x +) 이고 오른팔은 x 를 뒤집는다.
 */
const IDLE = {
  upper: new T.Vector3(0.45, -0.86, 0.25).normalize(),
  lower: new T.Vector3(-0.76, -0.02, 0.65).normalize(),
  hand: new T.Vector3(-0.72, -0.1, 0.68).normalize(),
  palm: new T.Vector3(0.0, -1, 0.0),
  /** 책상 위에 편 손: 손가락 말림 [엄지, 검지, 중지, 약지, 새끼] 과 벌림 */
  fingers: [0.2, 0.25, 0.26, 0.3, 0.34],
  spread: 0.05,
  /** TRELLIS 몸은 팔이 레퍼런스보다 짧아서(상완 0.63, 하완 0.31) 쉼 자세에서는 뼈를 늘려 손이 책상까지 닿게 한다 */
  stretchUpper: 1.2,
  stretchFore: 1.55,
  /** 몸을 앞으로 살짝 숙임 (body.lean.z 단위, 0.45 rad 이 1) */
  leanZ: 0.16,
}
const NEUTRAL = { L: neutralArm(1), R: neutralArm(-1) }

const FINGER_NAMES = ['thumb', 'index', 'middle', 'ring', 'pinky'] as const

/**
 * 앱(main.ts)과 하네스가 같은 환경광을 쓰도록 한 곳에 둔다. 은은한 방 환경광만 깔고 (반사 없이 부드럽게), 직접광은 createNavy 안에 있다.
 * 톤매핑은 Neutral — 피부와 어두운 재킷이 눌리지 않는다.
 */
export function applyEnvironment(renderer: T.WebGLRenderer, scene: T.Scene) {
  renderer.toneMapping = T.NeutralToneMapping
  scene.environment = new T.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture
  scene.environmentIntensity = 0.6
}

function glbUrl() {
  const q = new URLSearchParams(location.search).get('glb')
  return new URL(q ?? './navy.glb', document.baseURI).href
}

async function loadRigJson(glb: string): Promise<NavyRig | null> {
  const tries = [glb.replace(/\.glb(\?.*)?$/, '-rig.json'), new URL('./navy-rig.json', document.baseURI).href]
  for (const u of tries) {
    try {
      const r = await fetch(u)
      if (r.ok) return (await r.json()) as NavyRig
    } catch { /* 다음 후보 */ }
  }
  return null
}

export function createNavy(): MingoModel {
  const root = new T.Group()
  root.name = 'navy'
  // 레퍼런스처럼 밝고 부드럽게: 하늘색 반구광을 넓게 깔고 키/필은 약하게
  root.add(new T.HemisphereLight(0xffffff, 0xf3e6dc, 1.0))
  const key = new T.DirectionalLight(0xfff4ea, 0.7); key.position.set(-3, 5, 6); root.add(key)
  const fill = new T.DirectionalLight(0xe6eeff, 0.2); fill.position.set(4, 2, 4); root.add(fill)
  // 어깨와 머리카락 가장자리에 부드러운 윤곽광
  const rim = new T.DirectionalLight(0xdfe8ff, 0.35); rim.position.set(0, 3, -5); root.add(rim)

  const hitMeshes: T.Object3D[] = []
  let rig: ReturnType<typeof bindRig> | null = null
  const anchors: ModelAnchors = {
    handL: new T.Group(), handR: new T.Group(), headTop: new T.Group(), mouth: new T.Group(), body: new T.Group(),
  }
  for (const [k, a] of Object.entries(anchors)) { a.name = `anchor_${k}`; root.add(a) }

  const applyFrame = (f: RigFrame, dt: number, t: number) => {
    if (!rig) return
    rig.apply(f, dt, t)
    root.updateMatrixWorld(true)
    rig.updateAnchors()
  }
  const model: MingoModel = {
    root,
    height: HEIGHT,
    hitMeshes,
    anchors,
    ready: (async () => {
      const url = glbUrl()
      const [gltf, rigJson] = await Promise.all([new GLTFLoader().loadAsync(url), loadRigJson(url)])
      const scene = gltf.scene
      scene.traverse(o => {
        const m = o as T.Mesh
        if (!m.isMesh) return
        m.material = Array.isArray(m.material) ? m.material.map(createBodyMaterial) : createBodyMaterial(m.material)
        m.frustumCulled = false // 스킨드 메시는 bind 포즈 바운딩이라 팔을 들면 잘린다
      })
      root.add(scene)
      scene.updateMatrixWorld(true)
      rig = bindRig(root, scene, rigJson, hitMeshes, anchors)
      applyFrame(neutralFrame(), 1, 0)
    })(),
    apply: (f, dt, t) => applyFrame(f, dt, t),
  }
  return model
}

/* ------------------------------------------------------------------ */

const _q1 = new T.Quaternion(), _q2 = new T.Quaternion(), _q3 = new T.Quaternion()
const _v1 = new T.Vector3(), _v2 = new T.Vector3()
const _m1 = new T.Matrix4(), _m2 = new T.Matrix4()

function bindRig(root: T.Group, scene: T.Object3D, rigJson: NavyRig | null, hitMeshes: T.Object3D[], anchors: ModelAnchors) {
  const bones = new Map<string, T.Bone>()
  scene.traverse(o => { if ((o as T.Bone).isBone) bones.set(o.name, o as T.Bone) })
  const get = (n: string) => bones.get(n) ?? null
  const need = (n: string) => {
    const b = get(n)
    if (!b) throw new Error(`navy.glb 에 뼈가 없다: ${n}`)
    return b
  }

  /** scene 기준(scene 자신의 변환은 뺀) 회전 */
  const sceneQ = (o: T.Object3D | null, out: T.Quaternion) => {
    out.identity()
    for (let n = o; n && n !== scene; n = n.parent) out.premultiply(n.quaternion)
    return out
  }
  const scenePos = (o: T.Object3D, out: T.Vector3) => {
    // bind 시점 scene 은 단위 변환이라 월드 = scene 기준
    return out.setFromMatrixPosition(o.matrixWorld)
  }

  /* ---- bind 기록 ---- */
  interface Rec {
    bone: T.Bone
    restQ: T.Quaternion       // 로컬 rest
    restPos: T.Vector3
    restWQ: T.Quaternion      // scene 기준 월드 rest
    restWPos: T.Vector3
    rel: T.Quaternion         // parentRestWQ^-1 * restWQ — 부모를 그대로 따라갈 때의 로컬
    restDir: T.Vector3        // 뼈 +Y 의 scene 기준 방향
  }
  const recs = new Map<string, Rec>()
  for (const [name, bone] of bones) {
    const restWQ = sceneQ(bone, new T.Quaternion())
    const parentWQ = sceneQ(bone.parent, new T.Quaternion())
    recs.set(name, {
      bone,
      restQ: bone.quaternion.clone(),
      restPos: bone.position.clone(),
      restWQ,
      restWPos: scenePos(bone, new T.Vector3()),
      rel: parentWQ.clone().invert().multiply(restWQ),
      restDir: UP.clone().applyQuaternion(restWQ),
    })
  }
  const R = (n: string) => recs.get(n)!
  const hips = need('hips'), spine = need('spine'), chest = need('chest'), neck = need('neck'), head = need('head')
  const chestRestInv = R('chest').restWQ.clone().invert()

  /* ---- 손: 손바닥 법선과 말림 축을 bind 에서 읽는다 ---- */
  /** 손가락 한 줄(마디들). curlIdx 손가락들의 말림 평균으로 굽힌다 (벙어리장갑은 네 손가락이 한 줄) */
  interface Chain {
    thumb: boolean
    curlIdx: number[]
    lateral: number           // 벌림 방향 부호 (중지 0)
    /** 엄지 대립: 손 뼈 로컬에서 손목→중지 축 둘레로 엄지를 손바닥 쪽으로 돌리는 부호 (엄지만) */
    oppose: number
    joints: { rec: Rec; axis: T.Vector3; restBend: number }[]
  }
  interface Hand {
    side: 1 | -1
    tag: 'L' | 'R'
    shoulder: Rec; upper: Rec; fore: Rec; hand: Rec
    nWorld: T.Vector3       // rest 손바닥 법선(scene)
    nLocal: T.Vector3       // 손 뼈 로컬 기준
    perFinger: boolean
    chains: Chain[]
    prevQ: T.Quaternion
    primed: boolean
    /** 부드럽게 따라가는 present (손을 놓치면 0.3초에 걸쳐 쉼 자세로 돌아간다) */
    pS: number
  }

  function perp(v: T.Vector3, axis: T.Vector3) {
    return v.clone().addScaledVector(axis, -v.dot(axis))
  }

  function makeHand(side: 1 | -1): Hand {
    const tag = side === 1 ? 'L' : 'R'
    const hand = R(`hand_${tag}`)
    const Y = hand.restDir
    // (1) 말림 방향: 마디마다 다음 마디가 어느 쪽으로 꺾이는지 (손가락이 손바닥 쪽으로 굽어 있다)
    const curlSum = new T.Vector3()
    const pairs: [string, string][] = []
    for (const f of FINGER_NAMES) for (const j of [1, 2]) if (recs.has(`${f}${j}_${tag}`) && recs.has(`${f}${j + 1}_${tag}`)) pairs.push([`${f}${j}_${tag}`, `${f}${j + 1}_${tag}`])
    if (recs.has(`fingers1_${tag}`) && recs.has(`fingers2_${tag}`)) pairs.push([`fingers1_${tag}`, `fingers2_${tag}`])
    for (const [a, b] of pairs) curlSum.add(R(b).restDir.clone().sub(R(a).restDir))
    const nCurl = perp(curlSum, Y)
    // (2) 엄지 위치: 왼손은 N = Y×T, 오른손은 N = T×Y
    const thumbRec = recs.get(`thumb2_${tag}`) ?? recs.get(`thumb1_${tag}`)
    let nThumb: T.Vector3 | null = null
    if (thumbRec) {
      const T_ = thumbRec.restWPos.clone().sub(hand.restWPos)
      const c = side === 1 ? Y.clone().cross(T_) : T_.clone().cross(Y)
      nThumb = perp(c, Y)
      if (nThumb.lengthSq() < 1e-8) nThumb = null
    }
    let n: T.Vector3
    const override = (rigJsonPalm())?.[tag]
    if (override) n = perp(new T.Vector3(...override), Y)
    else if (nCurl.length() > 0.12) n = nCurl
    else if (nThumb) n = nThumb
    else n = new T.Vector3(-side, 0, 0)
    n.normalize()
    const nLocal = n.clone().applyQuaternion(hand.restWQ.clone().invert())

    const chains: Chain[] = []
    const perFinger = recs.has(`index1_${tag}`) && recs.has(`middle1_${tag}`)
    const N = n
    const mid = recs.get(`middle1_${tag}`)
    /** 마디 하나: 말림 축(뼈 로컬)과, bind 에서 이미 구부러져 있는 각 */
    const joint = (rec: Rec, prevDir: T.Vector3): Chain['joints'][number] => {
      let ax = rec.restDir.clone().cross(N)
      if (ax.length() < 0.2) ax = Y.clone().cross(N)
      ax.normalize()
      const restBend = Math.atan2(prevDir.clone().cross(rec.restDir).dot(ax), prevDir.dot(rec.restDir))
      return { rec, axis: ax.applyQuaternion(rec.restWQ.clone().invert()), restBend }
    }
    const build = (names: string[], thumb: boolean, curlIdx: number[], lateral: number) => {
      const joints: Chain['joints'] = []
      let prev = Y
      for (const nm of names) {
        const rec = recs.get(`${nm}_${tag}`)
        if (!rec) continue
        joints.push(joint(rec, prev))
        prev = rec.restDir
      }
      let oppose = 0
      if (thumb && joints.length) {
        // 엄지 뿌리가 손 축에서 어느 쪽에 있는지: 그 방향에서 손바닥 법선 쪽으로 돌려 주는 부호
        const tv = joints[0].rec.restWPos.clone().sub(hand.restWPos)
        oppose = Math.sign(Y.clone().cross(perp(tv, Y)).dot(N)) || side
      }
      if (joints.length) chains.push({ thumb, curlIdx, lateral, oppose, joints })
    }
    if (perFinger) {
      FINGER_NAMES.forEach((f, fi) => {
        let lateral = 0
        const r1 = recs.get(`${f}1_${tag}`)
        if (mid && r1 && f !== 'middle' && f !== 'thumb') lateral = Math.sign(r1.restWPos.clone().sub(mid.restWPos).dot(N.clone().cross(Y))) || 0
        build([`${f}1`, `${f}2`, `${f}3`], f === 'thumb', [fi], lateral)
      })
    } else {
      build(['fingers1', 'fingers2'], false, [1, 2, 3, 4], 0)
      build(['thumb1', 'thumb2'], true, [0], 0)
    }
    return {
      side, tag, shoulder: R(`shoulder_${tag}`), upper: R(`upper_arm_${tag}`), fore: R(`forearm_${tag}`), hand,
      nWorld: n, nLocal, perFinger, chains, prevQ: new T.Quaternion(), primed: false, pS: -1,
    }
  }
  function rigJsonPalm(): { L?: number[]; R?: number[] } | undefined {
    return (rigJson as unknown as { palm?: { L?: number[]; R?: number[] } } | null)?.palm
  }
  const handL = makeHand(1), handR = makeHand(-1)

  /* ---- 히트 프록시: 스킨드 130K 삼각형 대신 뼈에 붙인 투명 캡슐 ---- */
  const hitMat = new T.MeshBasicMaterial({ visible: false })
  const addProxy = (boneName: string, geom: T.BufferGeometry, pos: T.Vector3Like, scale?: [number, number, number]) => {
    const b = get(boneName)
    if (!b) return
    const m = new T.Mesh(geom, hitMat)
    m.position.copy(pos as T.Vector3)
    if (scale) m.scale.set(...scale)
    m.name = `hit_${boneName}`
    b.add(m)
    hitMeshes.push(m)
  }
  const len = (a: string, b: string) => R(a).restWPos.distanceTo(R(b).restWPos)
  const capsule = (boneName: string, childName: string, radius: number) => {
    const L = Math.max(0.05, len(boneName, childName))
    addProxy(boneName, new T.CapsuleGeometry(radius, L, 4, 8), new T.Vector3(0, L / 2, 0))
  }
  // 몸통: 엉덩이~가슴을 감싸는 납작한 원기둥, 머리: 구
  const torsoH = R('neck').restWPos.y - R('hips').restWPos.y + 0.1
  addProxy('hips', new T.CylinderGeometry(0.68, 0.68, torsoH, 20), new T.Vector3(0, torsoH / 2, 0), [1, 1, 0.62])
  const headBase = R('head').restWPos, topY = (rigJson?.joints.head_top?.[1]) ?? HEIGHT
  const headR = (topY - headBase.y) / 2
  addProxy('head', new T.SphereGeometry(headR * 1.02, 20, 14), new T.Vector3(0, headR, 0.05), [1, 1, 0.95])
  for (const tag of ['L', 'R']) {
    capsule(`upper_arm_${tag}`, `forearm_${tag}`, 0.2)
    capsule(`forearm_${tag}`, `hand_${tag}`, 0.19)
    addProxy(`hand_${tag}`, new T.SphereGeometry(0.28, 12, 10), new T.Vector3(0, 0.2, 0))
  }

  /* ---- 앵커: 뼈 로컬 오프셋 + 축 ---- */
  interface AnchorDef { bone: T.Bone; pos: T.Vector3; q: T.Quaternion; target: T.Object3D }
  const anchorDefs: AnchorDef[] = []
  function defAnchor(target: T.Object3D, rec: Rec, worldPos: T.Vector3, basisQ: T.Quaternion) {
    const inv = rec.restWQ.clone().invert()
    anchorDefs.push({
      bone: rec.bone,
      pos: worldPos.clone().sub(rec.restWPos).applyQuaternion(inv),
      q: inv.clone().multiply(basisQ),
      target,
    })
  }
  const basisQuat = (x: T.Vector3, y: T.Vector3, z: T.Vector3) => new T.Quaternion().setFromRotationMatrix(new T.Matrix4().makeBasis(x, y, z))
  for (const h of [handL, handR]) {
    const Y = h.hand.restDir, Z = h.nWorld
    const X = Y.clone().cross(Z).normalize()
    const kn = recs.get(`middle1_${h.tag}`) ?? recs.get(`fingers1_${h.tag}`)
    const palmLen = kn ? kn.restWPos.distanceTo(h.hand.restWPos) : 0.22
    const p = h.hand.restWPos.clone().addScaledVector(Y, palmLen * 0.5).addScaledVector(Z, 0.04)
    defAnchor(h.side === 1 ? anchors.handL : anchors.handR, h.hand, p, basisQuat(X, Y, Z))
  }
  {
    const hr = R('head')
    const top = rigJson?.joints.head_top ? new T.Vector3(...rigJson.joints.head_top) : hr.restWPos.clone().add(new T.Vector3(0, 1.6, 0))
    defAnchor(anchors.headTop, hr, top, hr.restWQ.clone())
    const m = rigJson?.face?.mouth?.center ? new T.Vector3(...rigJson.face.mouth.center) : hr.restWPos.clone().add(new T.Vector3(0, 0.1, 0.5))
    defAnchor(anchors.mouth, hr, m, hr.restWQ.clone())
    const cr = R('chest')
    defAnchor(anchors.body, cr, cr.restWPos.clone().add(new T.Vector3(0, 0.1, 0)), cr.restWQ.clone())
  }

  /* ---- 얼굴 오버레이 ---- */
  const overlay = rigJson ? createFaceOverlay(head, rigJson) : null

  /* ---- 턱 (3D 입): mouthOpen 만큼 장면 기준 +X 축(오른쪽) 둘레로 아래로 돌린다 ---- */
  // 최대 벌림 (rad). 경첩이 귀 쪽이라 각은 작다 — rig.py 가 입술이 0.06 벌어지는 각을 jawMax 로 넘긴다
  const JAW_MAX = rigJson?.jawMax ?? 0.1
  const jawRec = recs.get('jaw') ?? null
  const jawAxis = jawRec ? new T.Vector3(1, 0, 0).applyQuaternion(jawRec.restWQ.clone().invert()).normalize() : null
  const _qj = new T.Quaternion()
  let jawS = 0
  /* ---- 윗입술: 입을 벌린 만큼 head 위쪽으로 올려 U 자 윗선을 편다 (rig.json lipLift) ---- */
  const lipRec = recs.get('lip_up') ?? null
  const LIP_LIFT = rigJson?.lipLift ?? 0
  const lipUpLocal = lipRec ? new T.Vector3(0, 1, 0).applyQuaternion(R('head').restWQ.clone().invert().multiply(new T.Quaternion())).normalize() : null
  if (overlay) overlay.root.name = overlay.root.name || 'face_overlay'

  /* ---- 설정 ---- */
  const setWorldQ = (rec: Rec, qw: T.Quaternion, parentQ: T.Quaternion) => {
    rec.bone.quaternion.copy(parentQ).invert().multiply(qw)
  }
  const dirOf = (d: Dir3, out: T.Vector3) => out.set(d.x, d.y, d.z).normalize()

  /**
   * 프레임 방향에 "쉼 자세와의 차이" 를 (1-present) 만큼 더한다. 앱 파이프라인(aliveness 융합·리액션 블렌드)은 present 가 낮을 때
   * 방향을 이미 neutralArm(차렷) 쪽으로 섞어 보내므로, 그 차렷 몫을 쉼 자세로 바꿔 끼우면 두 끝(0: 쉼, 1: 트래킹)이 정확하고 호흡 sway 도 남는다.
   */
  const idleMix = (frame: Dir3, idle: T.Vector3, neutral: Dir3, side: number, p: number, out: T.Vector3) => {
    const k = 1 - p
    return out.set(
      frame.x + k * (idle.x * side - neutral.x),
      frame.y + k * (idle.y - neutral.y),
      frame.z + k * (idle.z - neutral.z),
    ).normalize()
  }

  // 상태 (토르소 변환·임시)
  const RT = new T.Quaternion(), RTinv = new T.Quaternion()
  const chestQ = new T.Quaternion(), upQ = new T.Quaternion(), foQ = new T.Quaternion()
  const pq = new T.Quaternion(), tq = new T.Quaternion()
  const a1 = new T.Vector3(), a2 = new T.Vector3(), a3 = new T.Vector3(), a4 = new T.Vector3()
  const handM = new T.Matrix4(), locM = new T.Matrix4()
  const cc = new T.Vector3(0, 1, 0)
  const MU = new T.Matrix4(), MF = new T.Matrix4(), MH = new T.Matrix4(), MI = new T.Matrix4()
  const sc = new T.Vector3(), one = new T.Vector3(1, 1, 1)

  /** 캐릭터 축 기준 회전(rot) 을 토르소가 돈 만큼 감싸 scene 기준으로 */
  const wrapTorso = (rot: T.Quaternion, out: T.Quaternion) => out.copy(rot).premultiply(RT).multiply(RTinv)

  function aim(rec: Rec, parentWQ: T.Quaternion, dir: T.Vector3, out: T.Quaternion) {
    // 부모를 그대로 따라갔을 때의 회전에서 뼈 +Y 를 dir 로 최소 회전
    _q1.copy(parentWQ).multiply(rec.rel)
    _v1.copy(UP).applyQuaternion(_q1)
    _q2.setFromUnitVectors(_v1, dir)
    out.copy(_q2).multiply(_q1)
    return out
  }

  /** scene 기준 행렬 (scene 자신의 변환은 뺀다). 부모부터 로컬 행렬을 곱해 올라간다 */
  function sceneMatrix(o: T.Object3D, out: T.Matrix4) {
    out.identity()
    const chain: T.Object3D[] = []
    for (let n: T.Object3D | null = o; n && n !== scene; n = n.parent) chain.push(n)
    for (let i = chain.length - 1; i >= 0; i--) {
      const n = chain[i]
      if (n.matrixAutoUpdate) n.updateMatrix()
      out.multiply(n.matrix)
    }
    return out
  }

  // 하완·손 뼈는 로컬 행렬을 직접 쓴다: 상완/하완을 Y 로 늘려도 자식이 비틀리지(shear) 않게, 월드 기준 (회전 + 자기 뼈 방향 늘림)만 갖게 한다
  for (const h of [handL, handR]) { h.fore.bone.matrixAutoUpdate = false; h.hand.bone.matrixAutoUpdate = false }

  function driveArm(h: Hand, a: ArmPose, shrug: number, dt: number, stretch: number) {
    const side = h.side
    const nu = h.tag === 'L' ? NEUTRAL.L : NEUTRAL.R
    // 트래킹을 놓쳤거나 팔이 차렷으로 내려와 있으면(손목이 화면 밖) 쉼 자세(책상)로: 올라올 땐 빠르게, 내려갈 땐 0.3초
    const down = smoothstep(-0.8, -0.93, clamp(a.lowerDir.y, -1, 1))
    const pT = clamp(a.present, 0, 1) * (1 - down)
    if (h.pS < 0) h.pS = pT
    h.pS += (pT - h.pS) * (1 - Math.exp(-dt / (pT > h.pS ? 0.08 : 0.3)))
    const p = h.pS
    // 어깨 으쓱: 캐릭터 Z 축 회전(왼쪽 +, 오른쪽 −), 토르소를 따라 돈다
    tq.setFromAxisAngle(a1.set(0, 0, 1), side * shrug * 0.3)
    wrapTorso(tq, pq)
    const shoulderWQ = _q3.copy(pq).multiply(chestQ).multiply(h.shoulder.rel)
    setWorldQ(h.shoulder, shoulderWQ, chestQ)

    // 방향 (몸통 따라 돌림)
    const dU = idleMix(a.upperDir, IDLE.upper, nu.upperDir, side, p, a2).applyQuaternion(RT)
    aim(h.upper, shoulderWQ, dU, upQ)
    setWorldQ(h.upper, upQ, shoulderWQ)
    const dL = idleMix(a.lowerDir, IDLE.lower, nu.lowerDir, side, p, a2).applyQuaternion(RT)
    aim(h.fore, upQ, dL, foQ)

    // 팔 늘리기 (러버호스): 상완 뼈 Y 배율은 뼈에, 하완은 아래 행렬에
    const s = clamp(stretch, 1, 1.6)
    const su = s * (1 + (IDLE.stretchUpper - 1) * (1 - p))
    const sf = s * (1 + (IDLE.stretchFore - 1) * (1 - p))
    h.upper.bone.scale.set(1, su, 1)

    // 손: 방향(Y)과 손바닥 법선(N) 을 맞춘다
    const hd = idleMix(a.handDir, IDLE.hand, nu.handDir, side, p, a2).applyQuaternion(RT)
    const pn = idleMix(a.palmNormal, IDLE.palm, nu.palmNormal, side, p, a4).applyQuaternion(RT)
    pn.addScaledVector(hd, -pn.dot(hd))
    if (pn.lengthSq() < 1e-6) pn.copy(h.nWorld).applyQuaternion(RT)
    pn.normalize()
    const hx = a1.copy(hd).cross(pn).normalize()
    handM.makeBasis(hd, pn, hx)
    // 로컬 기저: (Y, nLocal, Y×nLocal)
    cc.set(0, 1, 0)
    const lx = _v1.copy(cc).cross(h.nLocal).normalize()
    locM.makeBasis(cc, h.nLocal, lx)
    _m1.copy(handM).multiply(_m2.copy(locM).transpose())
    tq.setFromRotationMatrix(_m1)
    if (!h.primed) { h.prevQ.copy(tq); h.primed = true }
    else h.prevQ.slerp(tq, 1 - Math.exp(-dt * 30))

    // 하완·손 행렬: 위치는 부모(늘어난) 행렬로 옮기고, 회전은 위에서 정한 월드 회전, 하완만 자기 Y 로 늘린다
    sceneMatrix(h.upper.bone, MU)
    MF.compose(_v1.copy(h.fore.restPos).applyMatrix4(MU), foQ, sc.set(1, sf, 1))
    h.fore.bone.matrix.copy(MI.copy(MU).invert()).multiply(MF)
    MH.compose(_v2.copy(h.hand.restPos).applyMatrix4(MF), h.prevQ, one)
    h.hand.bone.matrix.copy(MI.copy(MF).invert()).multiply(MH)
    h.fore.bone.matrixWorldNeedsUpdate = true
    h.hand.bone.matrixWorldNeedsUpdate = true

    // 손가락
    const curls = a.fingers
    const spread = clamp(a.spread + (1 - p) * (IDLE.spread - nu.spread), 0, 1)
    // 손가락: 일반 마디는 "말림 → 목표 굽힘 각"에서 bind 에 이미 있는 굽힘을 빼서 돌린다 (0 이면 펴짐). 엄지는 bind 가 자연 자세라 상대값
    const MAXB = [1.4, 1.6, 1.1], THUMB_K = [0.6, 0.8, 0.9], THUMB_F = [0.5, 0.9, 1.0]
    for (const ch of h.chains) {
      let c = 0
      for (const i of ch.curlIdx) c += clamp((curls[i] ?? 0) + (1 - p) * (IDLE.fingers[i] - nu.fingers[i]), 0, 1)
      c /= ch.curlIdx.length
      // 엄지: c 가 높아지면 손바닥 쪽으로 대립(돌려 넣기)한 뒤 세 마디를 모두 굽혀 다른 손가락 위를 덮는다
      const w = smoothstep(0.5, 1, c)
      const wb = smoothstep(0.4, 0.6, c)
      ch.joints.forEach((j, ji) => {
        const jj = Math.min(ji, 2)
        const ang = ch.thumb ? c * THUMB_F[jj] - 0.3 * (1 - wb) * THUMB_K[jj] : c * MAXB[jj] - j.restBend
        tq.setFromAxisAngle(j.axis, ang)
        if (ji === 0 && ch.thumb && ch.oppose !== 0) {
          _q2.setFromAxisAngle(UP, ch.oppose * 0.9 * w)
          j.rec.bone.quaternion.copy(_q2).multiply(j.rec.restQ).multiply(tq)
        } else if (ji === 0 && ch.lateral !== 0) {
          // 벌림: 손 뼈 로컬의 손바닥 법선 둘레 (첫 마디의 부모가 손)
          const rs_ = _q2.setFromAxisAngle(h.nLocal, ch.lateral * (spread - 0.5) * 0.5)
          j.rec.bone.quaternion.copy(rs_).multiply(j.rec.restQ).multiply(tq)
        } else j.rec.bone.quaternion.copy(j.rec.restQ).multiply(tq)
      })
    }
  }

  const headE = new T.Euler(0, 0, 0, 'YXZ'), hq = new T.Quaternion(), hq2 = new T.Quaternion()
  const bodyE = new T.Euler(0, 0, 0, 'YXZ'), bq = new T.Quaternion()
  const neckQ = new T.Quaternion(), headQ = new T.Quaternion()

  /** 고개 좌우 돌림 중 몸통이 따라 도는 비율 (나머지는 목 35% · 머리 65%) */
  const BODY_FOLLOW = 0.2

  function apply(f: RigFrame, dt: number, t: number) {
    void t
    const body = f.body
    const mo = f.motion
    const k = 0.45
    // 고개를 돌리면 몸통도 조금(고개의 BODY_FOLLOW 만큼) 따라 돈다. 목이 혼자 다 비틀면 목·깃 사이가 떠 보인다.
    // 가슴의 비틀기 = tw × k × (spine 0.4 + chest 0.6) = tw × k 이므로 tw 에 yaw × BODY_FOLLOW / k 를 더한다
    const yawIn = clamp(f.head.yaw, -0.9, 0.9)
    const bodyYaw = yawIn * BODY_FOLLOW
    const leanX = clamp(body.lean.x, -1, 1), leanZ = clamp(body.lean.z + (1 - clamp(body.present, 0, 1)) * IDLE.leanZ, -1, 1), tw = clamp(body.twist + bodyYaw / k, -1.5, 1.5)

    // 전체: 점프·옆이동·자전·스쿼시·호흡은 scene 자체 변환 (밑단=y0 이 기준점이라 납작해져도 바닥에 붙어 있다)
    const sq = clamp(mo?.squash ?? 0, -1, 1), push = clamp(mo?.push ?? 0, 0, 1)
    const breath = Math.sin(f.breath * Math.PI * 2) * 0.004
    scene.position.set((mo?.shiftX ?? 0) * 0.3, (mo?.bounce ?? 0) * 0.25, 0)
    scene.rotation.set(0, mo?.spin ?? 0, 0)
    const sxz = 1 - sq * 0.03 + push * 0.06
    scene.scale.set(sxz, 1 + breath + sq * 0.06 + push * 0.06, sxz)

    // 몸통: hips / spine / chest 에 나눠 준다 (모두 rest 가 단위 회전이라 로컬 = 장면 축)
    const part = (lean: number, twist: number, out: T.Quaternion) => {
      bodyE.set(leanZ * k * lean, tw * k * twist, -leanX * k * lean, 'YXZ')
      return out.setFromEuler(bodyE)
    }
    const rh = R('hips'), rs = R('spine'), rc = R('chest')
    hips.position.copy(rh.restPos); hips.position.x += clamp(body.hipShift, -1, 1) * 0.035
    hips.quaternion.copy(part(0.3, 0, bq)).multiply(rh.restQ)
    spine.quaternion.copy(part(0.35, 0.4, bq)).multiply(rs.restQ)
    chest.quaternion.copy(part(0.35, 0.6, bq)).multiply(rc.restQ)
    hips.updateMatrixWorld(true)
    sceneQ(chest, chestQ)
    RT.copy(chestQ).multiply(chestRestInv)
    RTinv.copy(RT).invert()

    // 고개: 35% 목 / 65% 머리. 캐릭터 축 기준 회전을 토르소 변환으로 감싼다
    // 쉼 자세의 앞숙임은 고개를 살짝 들어 상쇄 (시선은 정면)
    const py = -clamp(f.head.pitch + (1 - clamp(body.present, 0, 1)) * IDLE.leanZ * k * 0.9, -0.65, 0.65), yw = yawIn - bodyYaw, rl = -clamp(f.head.roll, -0.5, 0.5)
    headE.set(py * 0.35, yw * 0.35, rl * 0.35, 'YXZ'); hq.setFromEuler(headE)
    headE.set(py * 0.65, yw * 0.65, rl * 0.65, 'YXZ'); hq2.setFromEuler(headE)
    wrapTorso(hq, hq)
    wrapTorso(hq2, hq2)
    const rn = R('neck'), rhd = R('head')
    _q1.copy(chestQ).multiply(rn.rel)
    neckQ.copy(hq).multiply(_q1)
    setWorldQ(rn, neckQ, chestQ)
    _q1.copy(neckQ).multiply(rhd.rel)
    headQ.copy(hq2).multiply(_q1)
    setWorldQ(rhd, headQ, neckQ)

    if (jawRec && jawAxis) {
      // 놀람은 조금 더 벌린다. 빠르게 따라가되 떨리지 않게 지수 평활
      const target = clamp(Math.max(f.mouthOpen, f.fx?.surprised ? 0.5 : 0), 0, 1) * JAW_MAX
      jawS += (target - jawS) * (1 - Math.exp(-dt * 22))
      jawRec.bone.quaternion.copy(jawRec.restQ).multiply(_qj.setFromAxisAngle(jawAxis, jawS))
      if (lipRec && lipUpLocal) {
        // 벌림 비율(0..1)만큼 윗입술 가운데를 올린다. 위치는 부모(head) 기준이라 head 의 위쪽 축으로 옮긴다
        const k = JAW_MAX > 0 ? jawS / JAW_MAX : 0
        lipRec.bone.position.copy(lipRec.restPos).addScaledVector(lipUpLocal, LIP_LIFT * k)
      }
    }

    driveArm(handL, f.armL, body.shrugL, dt, f.armL.stretch ?? 1)
    driveArm(handR, f.armR, body.shrugR, dt, f.armR.stretch ?? 1)
    overlay?.update(f, dt)
  }

  /** 소품이 따라갈 부착 프레임 갱신 (root 기준, 배율 1) */
  function updateAnchors() {
    const rootInv = _m2.copy(root.matrixWorld).invert()
    for (const d of anchorDefs) {
      d.bone.updateWorldMatrix(true, false)
      _m1.copy(rootInv).multiply(d.bone.matrixWorld)
      _m1.decompose(_v1, _q1, _v2) // _v2 = 배율 (버림)
      d.target.position.copy(d.pos).applyMatrix4(_m1)
      d.target.quaternion.copy(_q1).multiply(d.q)
      d.target.scale.set(1, 1, 1)
      d.target.updateMatrix()
    }
  }

  return { apply, updateAnchors }
}
