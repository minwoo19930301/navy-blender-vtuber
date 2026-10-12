/**
 * RigFrame 좌우 반사 — 실기기에서 좌우가 반대로 보일 때 런타임 토글용.
 *
 * 트래킹은 "거울" 규약(사용자 오른손 = 캐릭터 왼팔)으로 매핑한다(src/tracking/README.md).
 * 그 부호는 웹캠 없이 유도·수치검증만 됐으므로, 실기기에서 반대로 보이면 코드 수정 없이
 * 아래 반사를 켜서 맞춘다.
 *
 *  - reflectArms: 팔/손/어깨만 시상면 반사 (팔 체인 부호만 틀렸을 때)
 *  - reflectFrame: 머리·시선·표정·몸통까지 전부 반사 (거울 ↔ 인형 모드 전환)
 *
 * 반사 = 캐릭터 공간 x 성분 부호 반전 + L/R 슬롯 교환. 두 번 적용하면 원래대로 돌아온다.
 * 입력은 변형하지 않고 새 객체를 반환한다.
 */
import type { ArmPose, Dir3, RigFrame } from './contract'

const rx = (d: Dir3): Dir3 => ({ x: -d.x, y: d.y, z: d.z })

function reflectArm(a: ArmPose): ArmPose {
  return {
    present: a.present,
    upperDir: rx(a.upperDir),
    lowerDir: rx(a.lowerDir),
    palmNormal: rx(a.palmNormal),
    handDir: rx(a.handDir),
    fingers: [a.fingers[0], a.fingers[1], a.fingers[2], a.fingers[3], a.fingers[4]],
    spread: a.spread,
    wave: a.wave,
  }
}

export function reflectArms(f: RigFrame): RigFrame {
  return {
    ...f,
    armL: reflectArm(f.armR),
    armR: reflectArm(f.armL),
    body: { ...f.body, lean: { ...f.body.lean }, shrugL: f.body.shrugR, shrugR: f.body.shrugL },
  }
}

export function reflectFrame(f: RigFrame): RigFrame {
  const a = reflectArms(f)
  return {
    ...a,
    head: { pitch: f.head.pitch, yaw: -f.head.yaw, roll: -f.head.roll },
    gaze: { x: -f.gaze.x, y: f.gaze.y },
    blinkL: f.blinkR,
    blinkR: f.blinkL,
    browL: f.browR,
    browR: f.browL,
    body: {
      ...a.body,
      lean: { x: -f.body.lean.x, z: f.body.lean.z },
      twist: -f.body.twist,
      hipShift: -f.body.hipShift,
      kneeL: f.body.kneeR,
      kneeR: f.body.kneeL,
    },
    fx: { ...f.fx },
  }
}
