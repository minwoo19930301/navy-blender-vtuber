# 리그 계약 (TRELLIS 메시 + 뼈대)

여러 사람이 동시에 만드는 부분이 맞물리는 약속이다. 바꾸려면 이 문서부터 고친다.

## 파일

| 파일 | 만드는 곳 | 내용 |
|---|---|---|
| `trellis/apose-s1.png` | FLUX.2 (로컬) | 캐릭터 A자 자세 이미지 (생성 입력) |
| `trellis/apose-s1-t42d.glb` | TRELLIS.2 + `trellis/rebake.py` | 몸 전체 텍스처 메시 (눕혀 나옴, 높이 1) |
| `trellis/body-tex.glb` | 텍스처 다듬기 담당 (있으면 rig.py 가 이걸 쓴다) | 같은 메시, 텍스처만 개선 |
| `rig/hand/hand_R.glb`, `rig/hand/hand_R.json` | 손 생성 담당 | 오른손 메시(텍스처) + 관절 점 21개 (MediaPipe 순서) |
| `rig/rig.py` | 리깅 담당 | 위 파일들 → `public/navy.glb` + `public/navy-rig.json` |
| `src/model/index.ts` | 드라이버 담당 | GLB 로드, RigFrame → 뼈 회전 |
| `src/model/faceOverlay.ts` | 얼굴 담당 | 눈 깜빡임·입 벌림 오버레이 |

## 좌표

- three.js 기준: Y 위, 정면(얼굴) = +Z, 캐릭터 왼쪽 = +x (화면 오른쪽). Blender 에서는 Z 위, 정면 = -Y.
- 책상 = 재킷 밑단 = y 0. 머리 끝 ≈ y 3.05 (`MingoModel.height`). 밑단 아래(바지)는 잘려 있다.
- 쉼 자세(bind pose)는 A자: 팔이 몸 옆으로 비스듬히 내려와 있다. 앱의 기본 자세(트래킹 없을 때)는 이게 아니라
  "팔꿈치를 옆에 두고 아래팔을 앞으로 뻗어 책상 위에 손을 올린" 레퍼런스 자세다 (드라이버가 만든다).

## 뼈 이름 (glTF 노드 이름 그대로)

```
hips ─ spine ─ chest ─ neck ─ head
               chest ─ shoulder_L ─ upper_arm_L ─ forearm_L ─ hand_L ─ (손가락)
               chest ─ shoulder_R ─ upper_arm_R ─ forearm_R ─ hand_R ─ (손가락)
손가락 (손 교체 후): thumb1..3_{L,R}, index1..3_{L,R}, middle1..3_{L,R}, ring1..3_{L,R}, pinky1..3_{L,R}
손 교체 전 임시: fingers1_{L,R}, fingers2_{L,R}, thumb1_{L,R}, thumb2_{L,R}
```

- 뼈는 head → tail 이 로컬 +Y (Blender 규칙, glTF 로 그대로 나감). roll 은 뼈의 로컬 Z 가 대략 정면(+Z three)을 보게 맞춘다.
- 드라이버는 roll 을 가정하지 말고 bind 시점의 월드 회전을 읽어 쓴다.
- 메시: `navy_body` (SkinnedMesh), 손 교체 후 `navy_hand_L`, `navy_hand_R` (같은 skin). 재질은 양면(DoubleSide)으로 그린다.

## `public/navy-rig.json`

```json
{ "height": 3.05,
  "joints": { "head": [x,y,z], "shoulder_L": [...], ... },           // three 월드 좌표 (bind 자세)
  "face": { "eyeL": {"center": [x,y,z], "width": w, "height": h},     // 캐릭터 왼눈 (화면 오른쪽)
            "eyeR": {...},
            "mouth": {"center": [x,y,z], "width": w, "upper": [...], "lower": [...]} } }
```

얼굴 점은 bind 자세의 월드 좌표다. 오버레이는 bind 시점에 head 뼈 로컬로 바꿔 head 뼈에 붙인다.

## 오버레이 인터페이스 (`src/model/faceOverlay.ts`)

```ts
export function createFaceOverlay(head: THREE.Bone, rig: NavyRig): { root: THREE.Object3D; update(f: RigFrame, dt: number): void }
```

- 평소엔 아무것도 안 보인다 (구운 눈·입이 그대로 보이게). 깜빡일 때 눈꺼풀, 입 벌릴 때 입 모양만 덧그린다.
