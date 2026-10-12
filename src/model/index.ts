import * as T from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import type { ArmPose, MingoModel, RigFrame } from '../contract'
import { neutralFrame } from '../contract'
import { createFace, decalUVs } from './face'
import { upgradeMaterial } from './materials'

/**
 * Blender 에서 만든 GLB(public/navy.glb, blender/build.py)를 불러와 노드 이름으로 움직인다. 스키닝 없이 부위별 강체다.
 * 치수는 blender/common.py 의 DIMS 와 같아야 한다.
 */
export const DIMS = {
  NECK_PIVOT: new T.Vector3(0, 1.30, 0),
  SHOULDER: new T.Vector3(0.86, 0.92, -0.05),
  UPPER_LEN: 0.62,
  LOWER_LEN: 0.60,
  REST_UPPER: new T.Vector3(0.25, -0.95, 0.15),
  REST_LOWER: new T.Vector3(-0.75, -0.15, 0.62),
  REST_HAND: new T.Vector3(-0.25, -0.08, 1.0),
  REST_PALM: new T.Vector3(0, -1, 0),
  HEIGHT: 3.05,
}
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, Number.isFinite(v) ? v : 0))
const UP = new T.Vector3(0, 1, 0)
const AXIS_X = new T.Vector3(1, 0, 0)
const AXIS_Z = new T.Vector3(0, 0, 1)

function glbUrl() {
  const q = new URLSearchParams(location.search).get('glb')
  return new URL(q ?? './navy.glb', document.baseURI).href
}

export function createNavy(): MingoModel {
  const root = new T.Group()
  root.name = 'navy'
  root.add(new T.HemisphereLight(0xfff6ee, 0xcbbfb8, 1.4))
  const key = new T.DirectionalLight(0xfff1e4, 2.0); key.position.set(-3, 5, 5); root.add(key)
  const fill = new T.DirectionalLight(0xdde8ff, 0.8); fill.position.set(4, 2, 3); root.add(fill)
  const rim = new T.DirectionalLight(0xeef2ff, 1.6); rim.position.set(1.5, 4, -4); root.add(rim)

  const face = createFace()
  const hitMeshes: T.Object3D[] = []
  let rig: ReturnType<typeof bindRig> | null = null

  const model: MingoModel = {
    root,
    height: DIMS.HEIGHT,
    hitMeshes,
    ready: new GLTFLoader().loadAsync(glbUrl()).then(gltf => {
      const scene = gltf.scene
      scene.traverse(o => {
        const m = o as T.Mesh
        if (!m.isMesh) return
        if (m.name === 'face_decal' || (m.material as T.Material).name === 'face_decal') {
          decalUVs(m.geometry)
          m.material = face.material
          m.renderOrder = 1
          return
        }
        m.material = upgradeMaterial(m.material as T.Material)
        hitMeshes.push(m)
      })
      root.add(scene)
      rig = bindRig(scene)
      model.apply(neutralFrame(), 1, 0)
    }),
    apply(f: RigFrame, dt: number, t: number) {
      if (!rig) return
      rig.apply(f, dt, t)
      face.update(f)
      root.updateMatrixWorld(true)
    },
  }
  return model
}

function bindRig(scene: T.Object3D) {
  const need = (name: string) => {
    const o = scene.getObjectByName(name)
    if (!o) throw new Error(`navy.glb 에 노드가 없다: ${name}`)
    return o
  }
  const body = need('body')
  const headPivot = need('head_pivot')
  const headQ = new T.Quaternion(), headE = new T.Euler(0, 0, 0, 'YXZ'), invBody = new T.Quaternion()

  function makeArm(side: 1 | -1) {
    const tag = side === 1 ? 'L' : 'R'
    const upper = need(`arm_upper_${tag}`), lower = need(`arm_lower_${tag}`), hand = need(`hand_${tag}`)
    body.attach(hand)
    const joints: { node: T.Object3D; rest: T.Quaternion }[][] = []
    for (let i = 0; i < 5; i++) {
      const chain = []
      for (let j = 0; j < 3; j++) {
        const node = scene.getObjectByName(`f${i}_${j}_${tag}`)
        if (node) chain.push({ node, rest: node.quaternion.clone() })
      }
      joints.push(chain)
    }
    const restUpper = DIMS.REST_UPPER.clone().multiply(new T.Vector3(side, 1, 1)).normalize()
    const restLower = DIMS.REST_LOWER.clone().multiply(new T.Vector3(side, 1, 1)).normalize()
    const restHand = DIMS.REST_HAND.clone().multiply(new T.Vector3(side, 1, 1)).normalize()
    const shoulder = new T.Vector3(), elbow = new T.Vector3(), wrist = new T.Vector3(), dir = new T.Vector3()
    const fy = new T.Vector3(), fz = new T.Vector3(), fx = new T.Vector3(), basis = new T.Matrix4(), q = new T.Quaternion(), qc = new T.Quaternion()
    let first = true
    return (a: ArmPose, shrug: number, dt: number) => {
      const blend = clamp(a.present, 0, 1)
      shoulder.set(side * DIMS.SHOULDER.x, DIMS.SHOULDER.y + shrug * 0.05, DIMS.SHOULDER.z)
      dir.set(a.upperDir.x, a.upperDir.y, a.upperDir.z).normalize().lerp(restUpper, 1 - blend).normalize()
      upper.position.copy(shoulder); upper.quaternion.setFromUnitVectors(UP, dir)
      elbow.copy(shoulder).addScaledVector(dir, DIMS.UPPER_LEN)
      dir.set(a.lowerDir.x, a.lowerDir.y, a.lowerDir.z).normalize().lerp(restLower, 1 - blend).normalize()
      lower.position.copy(elbow); lower.quaternion.setFromUnitVectors(UP, dir)
      wrist.copy(elbow).addScaledVector(dir, DIMS.LOWER_LEN)
      hand.position.copy(wrist)
      fy.set(a.handDir.x, a.handDir.y, a.handDir.z).lerp(restHand, 1 - blend).normalize()
      fz.set(a.palmNormal.x, a.palmNormal.y, a.palmNormal.z).lerp(DIMS.REST_PALM, 1 - blend)
      fz.addScaledVector(fy, -fz.dot(fy)).normalize()
      fx.crossVectors(fy, fz).normalize()
      basis.makeBasis(fx, fy, fz); q.setFromRotationMatrix(basis)
      if (first) { hand.quaternion.copy(q); first = false } else hand.quaternion.slerp(q, 1 - Math.exp(-dt * 25))
      for (let i = 0; i < 5; i++) {
        const curl = clamp(a.fingers[i], 0, 1)
        joints[i].forEach(({ node, rest }, k) => {
          node.quaternion.copy(rest).multiply(qc.setFromAxisAngle(AXIS_X, curl * (i === 0 ? (k === 0 ? 0.5 : 0.8) : k === 0 ? 1.0 : 1.25)))
          if (i > 0 && k === 0) node.quaternion.multiply(qc.setFromAxisAngle(AXIS_Z, -side * (i - 2.5) * clamp(a.spread, -1, 1) * 0.17))
        })
      }
    }
  }
  const armL = makeArm(1), armR = makeArm(-1)

  return {
    apply(f: RigFrame, dt: number, _t: number) {
      body.position.set(clamp(f.body.hipShift, -1, 1) * 0.035 + (f.motion?.shiftX ?? 0) * 0.3, (f.motion?.bounce ?? 0) * 0.25, 0)
      body.rotation.set(f.body.lean.z * 0.45, f.body.twist * 0.45 + (f.motion?.spin ?? 0), -f.body.lean.x * 0.45, 'YXZ')
      body.scale.y = 1 + Math.sin(f.breath * Math.PI * 2) * 0.004 + (f.motion?.squash ?? 0) * 0.06
      headE.set(-clamp(f.head.pitch, -0.65, 0.65), clamp(f.head.yaw, -0.9, 0.9) + (f.motion?.spin ?? 0), -clamp(f.head.roll, -0.5, 0.5), 'YXZ')
      headQ.setFromEuler(headE)
      invBody.copy(body.quaternion).invert()
      headPivot.quaternion.copy(invBody).multiply(headQ)
      armL(f.armL, f.body.shrugL, dt)
      armR(f.armR, f.body.shrugR, dt)
    },
  }
}
