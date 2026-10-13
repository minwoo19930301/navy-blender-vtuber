/**
 * 리액션 소품 — '일하는 척'(10)의 헤드폰과 노트북 (public/props.glb, blender/props_export.py 가 만든다).
 *
 * - 헤드폰은 모델 앵커 headTop(머리 뼈 프레임, 월드 축 정렬)의 자식이라 고개를 그대로 따른다. glb 노드 원점이 headTop 자리다.
 * - 노트북은 씬(fxRoot 의 부모)에 얹는다. fxRoot 는 공 캐릭터용 배율·높이가 걸려 있어서 자식으로 두지 않는다.
 * - 헤드폰·노트북은 평소(idle)에 보이지 않는다. 리액션 레이어 10 이 살아 있는 동안만 보이고, 등장·퇴장은 tl 만의 순수 함수라 시각을 건너뛰어도 같은 모습이다.
 * - 책상('desk')은 idle 에 깊이만 쓰는 투명 가림판이다: 밑단·바지를 가리지만 투명 오버레이에서는 안 보인다.
 *   일하는 척 동안만 나무 책상이 서서히 나타난다. 키보드('keyboard')는 idle 에 보이고, 일하는 척 동안 노트북에 자리를 내주고 줄어 사라진다.
 * - 모델·씬은 엔진이 모른다: 처음 update 때 fxRoot.parent 에서 'anchor_headTop' 을 이름으로 찾아 붙인다 (아직 없으면 다음 프레임에 다시).
 */
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { DESK_WORK_COLOR, KEYBOARD_IDLE, PROP_CUES, PROP_WORK_LID_OPEN, POP_IN, POP_OUT, PropId, WORK_LAPTOP } from './propdefs'
import { easeOutBack, ss } from './util'

/** props.glb 에서 헤드폰 노드의 원점(머리 꼭대기)에서 머리 한가운데(귀 높이)까지 내려간 거리 — 팝이 머리 한가운데를 기준으로 커진다 */
const HEAD_PIVOT_DROP = 1.1
/** 헤드폰이 위에서 내려앉는 높이 */
const HEAD_DROP_FROM = 0.55

export interface WorkLayer {
  id: number
  tl: number
  w: number
}

export interface WorkProps {
  /** props.glb 로드가 끝나면(실패해도) resolve */
  ready: Promise<void>
  /** 레이어 10 의 상태로 소품 변환을 갱신한다 (id 가 10 이 아니면 숨긴다) */
  update(layers: readonly WorkLayer[]): void
  dispose(): void
}

const cue = (p: number) => PROP_CUES.find((c) => c.prop === p)!
const HEAD_CUE = cue(PropId.headphones)
const LAPTOP_CUE = cue(PropId.laptop)

/** 팝 들어옴(easeOutBack) × 줄어들며 사라짐(smoothstep). 0..~1.1 */
function popScale(tl: number, c: { in: number; out: number }): number {
  const a = easeOutBack((tl - c.in) / POP_IN)
  const b = 1 - ss(c.out, c.out + POP_OUT, tl)
  return Math.max(0, a * b)
}

export function createWorkProps(fxRoot: THREE.Object3D): WorkProps {
  let loaded = false
  let failed = false
  let headSrc: THREE.Object3D | null = null
  let lapSrc: THREE.Object3D | null = null
  const headPivot = new THREE.Group()
  headPivot.name = 'work_headphones'
  headPivot.visible = false
  const lapRoot = new THREE.Group()
  lapRoot.name = 'work_laptop'
  lapRoot.visible = false
  let lid: THREE.Object3D | null = null
  // 항상 보이는 책상·키보드 (씬에 직접 얹는다)
  const deskRoot = new THREE.Group()
  deskRoot.name = 'work_desk'
  deskRoot.visible = false
  const kbRoot = new THREE.Group()
  kbRoot.name = 'work_keyboard'
  kbRoot.visible = false
  let deskMat: THREE.MeshStandardMaterial | null = null
  const colWork = new THREE.Color(DESK_WORK_COLOR)
  let attachedDesk = false
  const lidOpenQ = new THREE.Quaternion()
  const lidQ = new THREE.Quaternion()
  const identity = new THREE.Quaternion()
  let attachedHead = false
  let attachedLap = false

  let resolveReady: () => void = () => {}
  const ready = new Promise<void>((r) => { resolveReady = r })

  const load = (): void => {
    const url = new URL('./props.glb', document.baseURI).href
    new GLTFLoader().loadAsync(url).then((gltf) => {
      // 재질은 단순 Standard 로 바꾼다 (sheen·clearcoat 확장 변형이 늘면 처음 등장 때 셰이더 컴파일이 끊긴다)
      gltf.scene.traverse((o) => {
        const m = o as THREE.Mesh
        if (!m.isMesh) return
        const s = m.material as THREE.MeshStandardMaterial
        m.material = new THREE.MeshStandardMaterial({ name: s.name, color: s.color.clone(), roughness: Math.max(0.85, s.roughness), metalness: 0, side: THREE.DoubleSide })
        s.dispose()
        m.frustumCulled = false
      })
      const deskSrc = gltf.scene.getObjectByName('desk') ?? null
      const kbSrc = gltf.scene.getObjectByName('keyboard') ?? null
      if (deskSrc) {
        deskSrc.removeFromParent()
        deskRoot.add(deskSrc)
        deskSrc.traverse((o) => {
          const m = o as THREE.Mesh
          if (m.isMesh) deskMat = m.material as THREE.MeshStandardMaterial
        })
        deskMat?.color.copy(colWork)
        if (deskMat) { deskMat.transparent = true; deskMat.opacity = 0; deskMat.depthWrite = false }
        // 가림판: 같은 모양, 색은 안 쓰고 깊이만 쓴다 → 아래 몸(밑단·바지)이 가려지되 배경은 투명하게 남는다
        const occ = deskSrc.clone(true)
        occ.name = 'desk_occluder'
        occ.traverse((o) => {
          const m = o as THREE.Mesh
          if (m.isMesh) { m.material = new THREE.MeshBasicMaterial({ colorWrite: false }); m.renderOrder = -1 }
        })
        deskRoot.add(occ)
      }
      if (kbSrc) {
        kbSrc.removeFromParent()
        kbSrc.position.set(0, 0, 0)
        kbSrc.rotation.set(0, 0, 0)
        kbRoot.add(kbSrc)
      }
      headSrc = gltf.scene.getObjectByName('headphones') ?? null
      lapSrc = gltf.scene.getObjectByName('laptop') ?? null
      if (headSrc) {
        headSrc.removeFromParent()
        headSrc.position.set(0, HEAD_PIVOT_DROP, 0)
        headPivot.add(headSrc)
      }
      if (lapSrc) {
        lapSrc.removeFromParent()
        lapSrc.position.set(0, 0, 0)
        lapSrc.rotation.set(0, 0, 0)
        lapSrc.scale.set(1, 1, 1)
        lapRoot.add(lapSrc)
        lid = lapSrc.getObjectByName('laptop_lid') ?? null
        if (lid) lidOpenQ.copy(lid.quaternion)
      }
      loaded = true
      resolveReady()
    }).catch((e) => {
      failed = true
      console.warn('[navy] props.glb 로드 실패', e)
      resolveReady()
    })
  }

  const tryAttach = (): void => {
    const scene = fxRoot.parent
    if (!scene) return
    if (!attachedDesk) {
      scene.add(deskRoot)
      scene.add(kbRoot)
      kbRoot.position.set(KEYBOARD_IDLE.x, KEYBOARD_IDLE.y, KEYBOARD_IDLE.z)
      kbRoot.rotation.set(0, KEYBOARD_IDLE.yaw, 0)
      attachedDesk = true
    }
    if (!attachedLap) {
      scene.add(lapRoot)
      lapRoot.position.set(WORK_LAPTOP.x, WORK_LAPTOP.y, WORK_LAPTOP.z)
      lapRoot.rotation.set(0, WORK_LAPTOP.yaw, 0)
      attachedLap = true
    }
    if (!attachedHead) {
      const anchor = scene.getObjectByName('anchor_headTop')
      if (anchor) {
        anchor.add(headPivot)
        headPivot.position.set(0, -HEAD_PIVOT_DROP, 0)
        attachedHead = true
      }
    }
  }

  // 처음 키를 누를 때 로드가 끊기지 않게 만들자마자 읽어 둔다
  if (typeof document !== 'undefined') load()

  return {
    ready,
    update(layers) {
      let v: WorkLayer | null = null
      for (let i = 0; i < layers.length; i++) if (layers[i].id === 10) v = layers[i]
      if (!loaded) return
      tryAttach()
      deskRoot.visible = attachedDesk
      // 노트북 팝(0..1 로 자른 값)에 맞춰 책상은 나무색으로, 키보드는 줄어든다
      let work = 0
      if (!v) {
        headPivot.visible = false
        lapRoot.visible = false
      } else {
        // 취소·교체로 나가는 중에는 엔벨로프 w 가 줄어드는 것을 따라 같이 줄어든다
        const fade = ss(0, 0.5, v.w)
        const hs = popScale(v.tl, HEAD_CUE) * fade
        headPivot.visible = attachedHead && hs > 0.002
        if (headPivot.visible) {
          headPivot.scale.setScalar(hs)
          // 위에서 내려앉는 느낌: 등장 구간에서 머리 위로 떠 있다가 내려온다
          const drop = (1 - ss(HEAD_CUE.in, HEAD_CUE.in + POP_IN + 0.1, v.tl)) * HEAD_DROP_FROM
          headSrc!.position.y = HEAD_PIVOT_DROP + drop
        }
        const ls = popScale(v.tl, LAPTOP_CUE) * fade
        lapRoot.visible = attachedLap && ls > 0.002
        if (lapRoot.visible) {
          lapRoot.scale.setScalar(ls * WORK_LAPTOP.scale)
          if (lid) {
            const open = ss(LAPTOP_CUE.in + 0.12, LAPTOP_CUE.in + PROP_WORK_LID_OPEN, v.tl)
            lid.quaternion.copy(lidQ.copy(identity).slerp(lidOpenQ, open))
          }
        }
        work = Math.min(1, ls)
      }
      if (deskMat) {
        // 일하는 척 동안만 나무 책상이 보인다 (idle 은 투명 가림판만)
        deskMat.opacity = work
        deskMat.depthWrite = work > 0.98
      }
      const ks = 1 - ss(0, 0.8, work)
      kbRoot.visible = attachedDesk && ks > 0.002
      if (kbRoot.visible) kbRoot.scale.setScalar(ks)
    },
    dispose() {
      for (const g of [headPivot, lapRoot, deskRoot, kbRoot]) {
        g.removeFromParent()
        g.traverse((o) => {
          const m = o as THREE.Mesh
          if (!m.isMesh) return
          m.geometry.dispose()
          ;(m.material as THREE.Material).dispose()
        })
      }
    },
  }
}
