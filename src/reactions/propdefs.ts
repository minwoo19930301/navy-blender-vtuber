/**
 * 리액션 소품 정의 — 어떤 리액션이 언제 어떤 소품을 쓰는지(큐)와, 타임라인(팔 제스처·표정)과 소품 애니메이션이 같이 쓰는 시각 상수.
 * 타임라인(timelines.ts)과 소품(props.ts)이 둘 다 이 파일을 읽어서, 뿔피리를 부는 순간에 입 모양과 종이 말림이 같은 시각에 움직인다.
 */

export const PropId = {
  horn: 0,
  heart: 1,
  clock: 2,
  cloth: 3,
  bouquet: 4,
  nightcap: 5,
  hat: 6,
  gift: 7,
  headphones: 8,
  laptop: 9,
} as const
export type PropIdValue = (typeof PropId)[keyof typeof PropId]
export const PROP_COUNT = 10

/** 리액션 시각 `in`..`out`(초) 동안 소품이 보인다. 앞뒤로 팝(overshoot)과 줄어들며 사라지는 구간이 있다 */
export interface PropCue {
  prop: PropIdValue
  /** 소품이 속한 리액션 번호 (1..10) */
  reaction: number
  in: number
  out: number
}

/** 팝 들어오는 시간(easeOutBack)과 나가는 시간(smoothstep 축소), 초 */
export const POP_IN = 0.3
export const POP_OUT = 0.22

export const PROP_CUES: readonly PropCue[] = [
  { prop: PropId.horn, reaction: 1, in: 0.42, out: 2.25 },
  { prop: PropId.heart, reaction: 2, in: 0.22, out: 2.5 },
  { prop: PropId.clock, reaction: 4, in: 0.3, out: 2.0 },
  { prop: PropId.cloth, reaction: 5, in: 0.45, out: 2.55 },
  { prop: PropId.bouquet, reaction: 6, in: 0.32, out: 2.15 },
  { prop: PropId.nightcap, reaction: 8, in: 0.12, out: 2.7 },
  { prop: PropId.hat, reaction: 9, in: 0.08, out: 2.7 },
  { prop: PropId.gift, reaction: 9, in: 1.0, out: 2.7 },
  // 일하는 척 (dur 5.0): 헤드폰을 먼저 쓰고 노트북이 따라 펼쳐진다. 퇴장은 엔진의 마지막 0.35초 페이드보다 먼저 끝난다
  { prop: PropId.headphones, reaction: 10, in: 0.1, out: 4.35 },
  { prop: PropId.laptop, reaction: 10, in: 0.3, out: 4.45 },
]

/* ---------------- 시각 상수 (타임라인과 소품이 같이 쓴다) ---------------- */

/** 뿔피리를 부는 시각(초)과 한 번 부는 길이: 종이 말림이 펴졌다가 튕겨 돌아온다 */
export const HORN_BLOWS: readonly number[] = [0.78, 1.32, 1.86]
export const HORN_BLOW_LEN = 0.42

/** 파티 모자가 점프 착지로 출렁이는 시각들(축하 타임라인의 hop 착지: 0.2+0.7, 1.3+0.3) */
export const HAT_LANDS: readonly number[] = [0.9, 1.6]
/** 선물 상자 뚜껑이 팡 열리는 시각 (색종이 세 번째 터짐과 같다) */
export const GIFT_POP = 1.2

/* ---------------- 일하는 척 (노트북 자리·뚜껑) ---------------- */

/** 노트북 밑판 바닥 가운데의 월드 위치, 배율, y 회전(rad). 앞(+Z, 키보드쪽)이 캐릭터를 향하게 π 에서 시작한다. y 는 책상 윗면(blender/props_export.py DESK_TOP) */
export const WORK_LAPTOP = { x: 0.55, y: 0.28, z: 0.85, yaw: Math.PI + 0.8, scale: 0.82 }
/** 노트북이 등장한 뒤 뚜껑이 다 열리기까지(초) */
export const PROP_WORK_LID_OPEN = 0.65

/** idle 키보드 자리 (책상 윗면 위, 오른쪽 앞, yaw -15°) */
export const KEYBOARD_IDLE = { x: 0.95, y: 0.28, z: 0.95, yaw: -Math.PI / 12 }
/** 책상 색: idle 은 배경에 가까운 밝은 색, 일하는 척 동안은 나무색 (레퍼런스 working-2) */
export const DESK_IDLE_COLOR = 0xf3f1ef
export const DESK_WORK_COLOR = 0x907358
