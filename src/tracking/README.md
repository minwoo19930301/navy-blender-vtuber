# src/tracking — 웹캠 → RigFrame 트래킹 (계약 v2: ArmPose/BodyPose)

MediaPipe Tasks(JS/WASM, 로컬 에셋)로 얼굴 변환행렬·52 블렌드셰이프·양손 21관절·
포즈 33관절(worldLandmarks, 미터)을 뽑아 `RigFrame`(src/contract.ts)으로 매핑한다.
모든 수학은 `math.ts` 순수 함수에 있고, 필터는 `oneEuro.ts`의 One Euro 구현을 쓴다.
검출·매핑·필터링은 기본적으로 **모듈 워커**에서 돈다 (아래 "실행 구조").

## 파일

| 파일 | 역할 |
|---|---|
| `index.ts` | `createTracker()`. 메인 스레드 쪽 전부: 워커 생성·초기화·종료, rVFC 프레임 펌프(백프레셔), 메인 스레드 폴백, 디버그 훅 |
| `core.ts` | 프레임 한 장 → RigFrame. 케이던스, 부재 백오프, 필터/기준선 상태, 히스테리시스, present 감쇠, 더블버퍼. window/Worker/MediaPipe 런타임 import 없음 — 워커와 폴백이 같은 코어를 쓴다 |
| `landmarkers.ts` | Face/Hand/Pose Landmarker 생성(GPU→CPU 폴백). tasks-vision 런타임을 import 하는 유일한 파일. 모듈 워커용 wasm 로더 훅 |
| `worker.ts` | 모듈 워커 진입점. `init` → 검출기 생성 → `frame`마다 `core.step` → `result` |
| `protocol.ts` | 메인 ↔ 워커 메시지 타입 (타입만) |
| `math.ts` | 행렬 분해, 블렌드셰이프 매핑, 몸통 기저(그람-슈미트)+거울 매핑, 손 기저/외적 부호, 손가락 관절각, BodyPose 기하 — 순수 함수 |
| `oneEuro.ts` | One Euro 필터 (Casiez et al., CHI 2012) 순수 클래스 |

## 실행 구조 (워커)

```
메인 스레드                                      트래킹 워커 (worker.ts)
rVFC ─ 워커가 놀면 ─ createImageBitmap(video) ──▶ frame{bitmap, nowMs}
        (바쁘면 드롭)        transfer              core.step: face → pose → hand → 필터/매핑
latest() ◀── result{RigFrame, 디버그} ◀──────────  bitmap.close()
```

- **측정 이유**: MacBook 메인 스레드에서 face ≈8ms, pose ≈13ms, hand ≈12ms. 렌더와 한 스레드라
  포즈·손이 격프레임(≈15Hz)으로 밀렸고 팔이 느리게 느껴졌다. 이제 메인은 프레임을 넘기고 렌더만 한다.
- **백프레셔**: 비행 중인 프레임은 최대 1개. 워커가 바쁜 동안의 rVFC는 드롭한다. 단, 처리 중에
  새 프레임이 지나갔으면 result를 받는 즉시 그 시점의 최신 프레임을 보낸다 (다음 rVFC를 기다리면
  검출이 프레임 간격(33ms)을 조금만 넘어도 처리율이 15Hz로 뚝 떨어진다). 같은 프레임은 rVFC의
  `presentedFrames`로 중복 전송을 막는다.
- **시계**: `nowMs`는 항상 메인의 `performance.now` 단일 시간축이다 (rVFC 시각, 캐치업 전송은
  `performance.now`, 단조 보정 +1ms). dt, MediaPipe 타임스탬프, 모든 lastSeen 타이머가 이 값만 쓴다.
  워커 안의 `performance.now()`는 검출 비용 차이 측정에만 쓴다 (시간 원점이 달라서 섞으면 타이머가 깨진다).
- **프레임당 할당**: 메인은 비트맵과 postMessage 객체뿐이다. 블렌드셰이프·행렬 같은 큰 디버그 필드는
  ≈4Hz로만 싣는다. 워커 안의 core도 블렌드셰이프/행렬/포즈 visibility 객체를 재사용한다.
  (math.ts의 벡터 연산은 여전히 작은 객체를 만든다 — 워커 안이라 메인 GC와 무관.)
- **`latest()`**: 가장 최근 result의 RigFrame. 시작 직후엔 neutral 프레임. 워커 모드의 더블버퍼는
  워커 안 core에 있고, 메인은 구조화 복제본 하나를 들고 있을 뿐이라 쓰다 만 프레임이 보일 수 없다.
- **라이프사이클**: `stop()`은 rVFC 취소 + 워커 `terminate()`. `start()`는 매번 새 워커를 만든다 (앱 hide/show).
  그래서 워커 모드에서는 hide 때 필터·shrug/hip 기준선이 초기화된다 (메인 폴백은 코어를 유지한다).
  초기화 도중의 `stop()`은 무시한다 — `start()`는 끝까지 가고, 호출측(main.ts)이 resolve 뒤에
  `camWanted`를 보고 다시 `stop()`한다.

### 폴백 (메인 스레드)

아래 중 하나면 같은 `core`를 메인 스레드 rVFC 안에서 돌린다 (`mode: 'main'`, 이유는 콘솔에 남는다):
Worker/OffscreenCanvas/createImageBitmap 미지원, 워커 생성 예외, 스크립트 로드 실패(`error` 이벤트),
`alive`가 10초 안에 안 옴, 초기화 실패(`init-error`: wasm 로더 import 실패 등), 초기화 60초 초과,
URL `?trackworker=0`. 실행 중에도 워커 런타임 오류나 8초 무응답이면 같은 비디오로 갈아탄다.
폴백 코드(core, tasks-vision)는 지연 로드라 워커가 정상이면 내려받지 않는다.
메인 폴백은 렌더와 CPU를 나눠 쓰므로 매 프레임 예산을 24ms로 더 보수적으로 잡는다.

### 번들·file:// (Electron은 dist를 `file://`로 연다)

- `vite.config.ts`의 `worker: { format: 'es' }` — 모듈 워커 번들. `new Worker(new URL('./worker.ts',
  import.meta.url), { type: 'module' })` 리터럴 형태를 유지해야 Vite가 인식한다.
- 빌드 결과: `dist/assets/worker-*.js`(정적 import 없는 단일 파일, tasks-vision 포함). main 청크의
  `new URL('worker-*.js', import.meta.url)`은 main 청크 자신의 `file://` URL 기준이라 `dist/assets/` 옆에서
  풀린다. `npm run pack`은 dist 전체를 `Resources/app/dist`에 그대로 복사한다 (asar 아님).
- wasm·모델은 메인에서 `new URL('./wasm', document.baseURI)`로 **절대 URL**을 만들어 `init`에 실어
  보낸다 (워커 안에는 document가 없고 상대 경로는 워커 스크립트 위치 기준이 된다). 모듈 워커엔
  `importScripts`가 없어서 tasks-vision이 동적 `import()`로 `vision_wasm_module_internal.js`를 불러온다 →
  `FilesetResolver.forVisionTasks(base, true)`.
- **`ModuleFactory not set.` 함정**: tasks-vision은 인스턴스를 만들 때마다 로더를 다시 실행해
  `self.ModuleFactory`를 얻고 끝나면 지운다. `import()`는 모듈을 캐시해서 두 번째 landmarker(손)부터
  죽는다. `self.import` 훅(tasks-vision이 있으면 호출)에서 default export를 다시 꽂아 해결 (landmarkers.ts).
- **file:// 에서 모듈 워커가 되는가**: Chrome 단독은 file:// 모듈 스크립트 자체를 막지만 Electron은 현재 앱이
  이미 file://에서 모듈 청크를 로드한다 (같은 부류의 권한). `npm run smoke`에 `FILE_URL=1`을 주면
  `--allow-file-access-from-files`로 dist를 file://(공백 포함 경로도)로 열어 워커 모드를 확인한다 — Electron
  실기기 검증은 아니다. 실제로 막혀 있으면 `error`/`alive` 타임아웃/`init-error`로 잡혀 메인 폴백으로
  내려가며 앱은 이전과 똑같이 동작한다. 그 경우의 근본 해결은 Electron 쪽에서 `file://` 대신
  `protocol.handle`로 만든 표준·secure 커스텀 스킴(`app://`)으로 dist를 서빙하는 것이다.

## 케이던스 (BRIEF §2)

- 얼굴: 매 프레임. 부재 백오프 외에는 건너뛰지 않는다.
- 포즈·손: 세 태스크 비용 EMA 합이 예산 안이면 **매 프레임**, 넘으면 포즈 짝수/손 홀수 프레임 교차
  (≈15Hz@30fps). 워커 예산 40ms, 메인 폴백 24ms. 경계에서 깜빡이지 않게
  ±2ms 히스테리시스(진입 합<예산-2, 이탈 합>예산+2). `?trackbudget=<ms>`로 덮어쓸 수 있다 (벤치용).
  워커 예산을 카메라 프레임 간격(33ms)보다 크게 잡은 이유: 워커에서는 예산을 넘겨도 메인 스레드가 안 막히고
  처리율만 ≈1000/합 Hz로 내려간다. 합 40ms면 세 태스크가 모두 ≈25Hz라 얼굴 30Hz + 포즈·손 15Hz보다 팔이
  낫다. 실제로 매 프레임 모드가 켜졌는지는 `__mingoTracking.everyFrame`으로 본다.
- mediapipe 타임스탬프는 `max(last+1, floor(now))`로 단조 증가 보장 (세 태스크 공유 가능).
- 부재 백오프: 10s+ 얼굴 미검출 시 얼굴 1/4 케이던스, 포즈/손 완전 스킵
  (팔/몸은 present 감쇠로 idle 복귀, 재획득은 얼굴부터).

## 좌표계와 거울 매핑 (핵심 — math.ts 주석에 전체 유도)

- mp world: +x=이미지 오른쪽(=사용자 왼쪽), +y=아래, +z=카메라에서 멂
  (d.ts: "smaller z = closer to camera"). pose 원점=엉덩이 중점, hand 원점=손 중심 —
  방향벡터(차분)만 쓰므로 원점 차이는 소거.
- 몸통 기저(그람-슈미트): bx=어깨 12→11(사용자 왼쪽), by=월드 위(0,-1,0)를 bx에
  직교화, bz=bx×by(카메라 쪽). 퇴화 시 `CAMERA_BASIS` 폴백.
- 거울 매핑: `char = (-d·bx, d·by, d·bz)` — 좌우 성분만 반전하는 반사(행렬식 -1).
  검산 3종: 차렷 (-0.17,0.98,0)→(0.17,-0.98,0), T자 (-1,0,0)→(1,0,0),
  앞으로 (0,0,-1)→(0,0,1). 모두 계약 주석 예시와 일치.

## ArmPose

| 채널 | 소스 | 계산 |
|---|---|---|
| `upperDir/lowerDir` | pose world (팔 체인은 pose 기준 — BRIEF §4) | 어깨→팔꿈치 / 팔꿈치→손목을 기저 변환+거울. armL=사용자 오른팔(12,14,16) |
| `handDir/palmNormal` | hand world (손 자세는 hand 기준) | handDir=손목0→중지MCP9, palmRef=검지5→새끼17, palmNormal=오른손 `handDir×palmRef` / 왼손 `palmRef×handDir` (외적 부호 유도는 math.ts — 왼/오른손은 카이랄리티가 반대) |
| `fingers[5]` | hand world 3D 관절각 | 손가락=∠MCP+∠PIP+∠DIP 합 [0.6..4.0rad], 엄지=BRIEF식 2관절 [0.25..1.5] |
| `spread` | hand world | 검지 기절골(5→6) vs 새끼 기절골(17→18) 방향각 [0.3..0.95rad] |
| `present` | pose visibility | min(어깨,팔꿈치,손목 vis) 히스테리시스(0.6/0.45) + 등장 0.12s/소실 0.4s. **포즈 실패 시 0** (BRIEF §8) |
| `wave` | — | 항상 0 (계약: aliveness 전용) |

손↔팔 매칭: 1순위 포즈 손목(이미지 좌표) 최근접(반경 0.2), 2순위 handedness 라벨
이중반전(셀피 가정 스왑 × 거울 = 라벨 'Left'→armL). 필터 후 palmNormal은
handDir에 그람-슈미트로 재직교화.

## BodyPose

| 채널 | 계산 (모두 pose world, 부호 유도는 math.ts `bodyRawFromPose`) |
|---|---|
| `shrugL/R` | 귀↔어깨 거리(몸통 up 사영)의 기준선 대비 감소 / (0.2×기준선). 기준선=비대칭 엔벨로프 EMA(이완 3s / 으쓱 25s) — BRIEF §6 캘리브레이션 |
| `lean.x` | 어깨라인 vs 수평면 각. 사용자 오른쪽 기울임 → + (거울) |
| `lean.z` | 어깨중심 vs 엉덩이중심 z차 각. 앞(카메라)으로 숙임 → + |
| `twist` | 어깨라인 vs 엉덩이라인 y회전차. 사용자 오른쪽 돌기 → + |
| `hipShift` | (엉덩이중심-발목중심)·bx / 0.09m, 부호 반전(+캐릭터 왼발). world 원점이 엉덩이라 절대이동이 없어 **발목 기준 필수**. 발목 비가시 시 이미지 엉덩이 x 기준선(EMA 8s) 폴백 |
| `legsPresent` | min(무릎25,26 vis) 히스테리시스(0.55/0.45) + 등장/소실 감쇠 (BRIEF §6 ">0.5") |
| `kneeL/R` | ∠(엉덩이→무릎, 무릎→발목) / 2.2rad. kneeL=사용자 오른다리(24,26,28) |

## 필터·타이밍

| 항목 | 값 | 근거 |
|---|---|---|
| 머리 pitch/yaw/roll | 1.0 / 0.05 | beta↑: 빠른 끄덕임에 지연 없이 |
| blink | 3.0 / 0.05 | 0.1s급 고속 신호 — 과평활 시 눈이 안 감김 |
| 방향벡터 (upper/lower/palm/hand) | 성분별 1.2 / 0.04 → **재정규화** | BRIEF §7. 퇴화 시 이전 값 유지 |
| fingers/spread | 0.8 / 0.015 | BRIEF §7 "살짝 느리게" |
| shrug | 1.5 / 0.05 | 빠른 제스처 |
| lean/twist/hipShift | 0.8 / 0.02, knee 1.0 / 0.03 | 저속 자세 — 지터 억제 우선 |
| tracked | 상승 0.15s / 감쇠 0.5s | BRIEF |
| present (팔/몸/다리) | 상승 0.12s / 감쇠 0.4s | BRIEF §7 "0.4s 감쇠, 스냅 금지" |
| 필터 리셋 | 소실 1s 초과 후 재획득 | One Euro 미분 스파이크 방지. shrug/hip 기준선은 유지 |

## 머리 포즈 / 표정 (기존과 동일)

행렬 분해 `R=Ry·Rx·Rz`, column-major 자동 판별, 거울 부호(pitch=-φ, yaw=-θ, roll=+ψ),
블렌드셰이프 좌우 스왑 — `math.ts` §1~2 주석 참조. 검증:
`window.__mingoTracking.lastMatrix`의 data[12..14]에 cm 평행이동(z≈-30)이 있어야 한다.

## 디버그

`window.__mingoTracking` — 메인 스레드에서 워커 메시지로 갱신한다 (스모크와 디버그 오버레이가 읽는다).

| 필드 | 뜻 |
|---|---|
| `mode` | `'worker'` / `'main'` (폴백) |
| `delegates` | 검출기별 `GPU`/`CPU` |
| `fps` | 트래커가 실제로 처리한 프레임 속도 EMA (카메라 fps가 아님) |
| `everyFrame` | 포즈·손을 매 프레임 돌리는 중인가 |
| `costMs` | 태스크별 검출 비용 EMA (워커 안에서 잰 값) |
| `mainMs` | 메인 스레드가 프레임 하나에 쓴 시간 EMA — 워커 모드는 펌프+수신, 메인 모드는 검출 전체 |
| `latencyMs` | 워커 모드: 캡처 → 결과 수신까지 |
| `lastPoseVis` | 팔/몸/다리 visibility 게이팅 상태 |
| `lastBlendshapes`, `lastMatrix` | 얼굴 디버그 (워커 모드는 ≈4Hz) |

`node scripts/bench-tracking.mjs`가 headless Chrome에서 메인 스레드 점유율(CDP TaskDuration), rVFC 콜백
소요, longtask를 잰다 (`QUERY=trackworker=0`이 이전 구조, `QUERY=nocam=1`이 렌더 바닥값).
`npm run smoke`는 모드가 기대값('worker', `QUERY=trackworker=0`이면 'main')인지까지 확인한다.

실측 (headless Chrome + SwiftShader, 가짜 카메라 30fps, 15초 구간, 3회 중앙값 — 절대치보다 차이를 볼 것):

| | 메인 점유율 | rVFC 콜백 평균 | 처리 프레임/초 | 포즈·손 |
|---|---|---|---|---|
| 워커 이전 (HEAD) | 72% | 27.8ms | 26.0 | 격프레임 |
| 메인 폴백(`trackworker=0`) | 81% | 27.6ms | 28.7 | 격프레임 |
| 워커 | 3.4% | 0.08ms | 30.1 | 격프레임 |
| 워커, 예산 70ms | 3.3% | 0.02ms | 24.3 | 매 프레임 |
| 메인 폴백, 예산 70ms | 100% | 42.3ms | 23.3 | 매 프레임 |

처리 프레임/초: 메인 스레드 행은 rVFC 콜백 수 ÷ 15초(콜백마다 검출), 워커 행은 `fps`(result 속도).
이 환경은 소프트웨어 GL이라 검출 합이 ≈48ms로 예산(워커 40ms)을 넘어 기본 설정에선 격프레임이다.
예산을 70ms로 올리면 워커는 메인 점유율 3%를 유지한 채 세 태스크를 매 프레임 돌리고, 같은 설정의
메인 폴백은 메인 스레드를 100%로 포화시키고 longtask 12개가 난다.

## 알려진 한계

1. **부호 검증 범위**: 유도·수치검증(순수 함수에 합성 랜드마크 주입, 27케이스)에 더해
   smiley-vtuber의 `npm run e2e`(VRM 배우 영상을 가짜 카메라로 주입)로 팔 방향(배우 오른팔 → armL +x),
   고개 yaw, 깜빡임, 입, 손가락 말림 부호를 확인했다. 손바닥 앞/뒤(palmNormal)는 애니 렌더 손에
   단서가 없어 미검증. 실기기에서 반대로 보이면 앱의 좌우 반전 토글(Cmd+Shift+X)을 먼저 쓰고, 코드로는:
   팔/손 좌우 전체 → `charDirFromWorld`의 `-u` 한 곳, 손바닥 앞뒤 →
   `handOrientFromWorld`의 외적 순서, 몸통 채널 → `bodyRawFromPose` 해당 식.
2. **handedness 라벨**: 포즈 손목 최근접 매칭이 1순위라 라벨 오분류에는 강건하지만,
   포즈 비가시 상태에서는 라벨 이중반전 가정('Left'→armL)에 의존.
3. **pose 관절 정체성**: 무반전 피드에서 인덱스 11=사용자 왼어깨로 신뢰. 실기기에서
   좌우가 반대면 `ARM_POSE_IDX`/`bodyRawFromPose`의 L/R 인덱스만 스왑.
4. **정규화 상수는 휴리스틱**: `FINGER_TUNING`/`BODY_TUNING`에 집약 — 체형·카메라에
   따라 재튜닝 여지.
5. **shrug 기준선 크리프**: 으쓱을 ~25s 이상 유지하면 기준선이 따라와 값이 준다
   (비대칭 τ로 완화).
6. **격프레임 포즈/손**: 검출 합이 예산(워커 40ms)을 넘는 기기에서만 해당. 이때 빠른 팔 휘두름에서
   ~66ms 지연이고 손 프레임의 몸통 기저는 ≤2프레임 이전 포즈 것을 쓴다. 매 프레임 모드에서도
   워커 처리 지연(캡처 → result)이 `latencyMs`만큼(≈검출 합) 더해진다.
7. **워커 모드 hide/show**: `stop()`이 워커를 종료하므로 shrug/hip 기준선과 필터가 재시작 때 초기화된다
   (몇 초 안에 재캘리브레이션).
8. **Electron file:// 모듈 워커는 실기기에서 검증하지 못했다**: 위 "번들·file://" 참조.
   headless Chrome(`--allow-file-access-from-files`)에서만 확인했고, 막혀 있으면 자동으로 메인 폴백.
