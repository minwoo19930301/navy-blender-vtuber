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
 * 구운 눈·입 위에 깜빡임과 입 벌림만 덧그린다. 평소엔 아무것도 안 보인다.
 * (임시 스텁 — 얼굴 담당이 채운다. 인터페이스는 rig/CONTRACT.md)
 */
export function createFaceOverlay(head: T.Bone, _rig: NavyRig): { root: T.Object3D; update(f: RigFrame, dt: number): void } {
  const root = new T.Group()
  root.name = 'face_overlay'
  head.add(root)
  return { root, update() {} }
}
