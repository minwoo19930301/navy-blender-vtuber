# Navy VTuber

영상 `avatar-1791270641941691033-11.mp4`를 참고해 만든 **별도 macOS VTuber 앱의 1차 버전**.
검은 가르마 머리, 큰 갈색 눈, 남색 재킷과 흰 티셔츠를 입은 상반신 캐릭터다.
원본 MP4의 메시를 추출한 것이 아니라 Three.js로 새로 구성한 스타일화 모델이다.

## 모델 먼저 보기

- `shots/model-preview.gif` / `.mp4`: 실제 모델의 6초 동작 미리보기 (합성 포즈; 실시간 웹캠 녹화 아님)
- `shots/front.png`: 정면
- `shots/three-quarter.png`: 35° 시점
- `shots/expressions.png`: 기본, 말하기, 윙크, 손인사, 브이, 만세
- `npm run web` 후 `http://localhost:5187/harness.html?orbit=35`: 카메라 없이 모델 보기

이 앱의 모델은 코드와 분리된 VRM/Live2D 파일이 아니다. 얼굴은 곡면 위 동적 텍스처,
머리·몸·팔·다섯 손가락은 3D 지오메트리와 관절 노드로 움직인다. Blender 원본이나
범용 VRM 내보내기는 포함하지 않는다. 영상에서 보이지 않는 등·뒷머리는 추정한 형태다.

## 실행

`release/Navy VTuber.app`을 연다. **단독 실행 번들**이라 Node.js나 소스 폴더가 필요 없다.
처음 실행하면 macOS 카메라 권한을 요청한다. 카메라 영상은 로컬 MediaPipe에서만 처리하며 저장하지 않는다.
카메라가 없어도 대기 모션과 리액션은 동작한다.

소스에서 실행할 때:

```sh
npm ci
npm run app
```

처음 생성한 번들은 개발용 ad-hoc 서명이다. App Store / Developer ID 공증 배포본은 아니다.

## 조작

| 조작 | 동작 |
|---|---|
| 캐릭터 드래그 | 위치 이동 |
| 우클릭 | 옵션·리액션·종료 |
| 오른쪽 아래 카메라 버튼 | 카메라 켜기 / 끄기 / 다시 연결 |
| Cmd+Shift+M | 숨기기 / 보이기; 숨기면 카메라와 렌더 정지 |
| Cmd+Shift+B | 투명 / 크로마키 / 단색 배경 |
| Cmd+Shift+X | 좌우 반전 모드 |
| Cmd+Shift+D | 트래킹 디버그 |
| Cmd+Shift+- / = / 0 | 작게 / 크게 / 크기 리셋 |
| Ctrl+Option+1~9 | 웃음 / 사랑 / 인사 / 놀람 / 감동 / 뽀뽀 / 화남 / 졸림 / 축하 |
| Ctrl+Option+0 | 리액션 취소 |

창에 포커스가 있으면 숫자 1~9로 리액션, 0·Esc로 취소.
브라우저에서는 B·X·D·-·=·R로 보기 옵션을 조작한다.
다른 VTuber 앱과 동시에 실행하면 같은 전역 단축키가 충돌할 수 있다.
OBS에서는 macOS 창 캡처로 선택하고, 필요하면 녹색 배경에 크로마 키를 적용한다.

## 성능 구조와 확인 범위

`smiley-vtuber`의 로컬 MediaPipe 워커, 신호 필터, idle 모션, Electron 오버레이를 재사용했다.
카메라 수명 관리는 `animal-hood-girl-vtuber`의 중단·재시작·재연결 처리를 재사용했다.
기존 두 프로젝트의 파일은 변경하지 않는다.

- 추적: 카메라 640×480, 요청 30fps. 비용 예산에 따라 포즈·손을 격프레임 처리.
- 화면: 추적/리액션 시 최대 60fps, 대기 시 최대 30fps. 실제 fps는 기기에 따라 달라진다.
- 픽셀 비율 상한 1.5; 얼굴 텍스처 512×512, 변한 경우만 업데이트.
- 머리 메시와 관절 메시를 미리 생성하고 매 프레임 재사용.
- 네이비 전용 이름·설정 키·번들 ID·개발 포트 5187.

2026-10-08 동일 Mac에서 headless Chrome + 같은 VRM 배우 영상으로 10초씩 측정한 1회 결과:

| 지표 | Smiley | Navy |
|---|---:|---:|
| 메인 스레드 busy 비율 | 3.8% | 3.3% |
| 종료 시점 추적 fps EMA | 30.2 | 27.0 |
| 메인 스레드 50ms 이상 작업 | 0 | 0 |
| 결과 전달 지연 EMA | 31.65ms | 32.49ms |

원시 결과는 `reports/*-benchmark.json`. 총 CPU/GPU 사용률이나 실제 웹캠 실사용 수치가 아니다.
단일 짧은 측정이므로 동일 성능 보장이나 우열의 근거로 사용하지 않는다.
실제 사용자 얼굴·손, macOS 카메라 권한 창, OBS 캡처는 사용자 환경에서 추가 확인해야 한다.

자동 검증 결과: 타입·빌드 성공, 카메라 수명 관리 8/8, 배우 영상 E2E 8/8 통과.
단독 앱에 포함된 `dist`를 file URL로 로드한 가짜 카메라 스모크도 워커 모드·예외 0으로 통과했다.
앱 번들 서명 검증은 통과했으며, 실제 앱 UI와 웹캠은 아직 실행하지 않았다.

## 개발·검증

```sh
npm run typecheck
npm test                  # 카메라 수명 관리 8개 시나리오
npm run build
npm run smoke             # 가짜 카메라 → 로컬 모델 → 워커 → 렌더
npm run e2e               # VRM 배우: 좌우 팔, 고개, 입, 눈, 손가락 8종
npm run pack              # 소스를 포함하는 standalone .app
```

E2E 배우는 옆 `animal-hood-girl-vtuber/public/models/placeholder.vrm`을 기본으로 쓴다.
다른 환경에서는 `ACTOR_VRM=/path/to/actor.vrm npm run e2e`로 지정한다.
이는 테스트 입력에만 필요하며 배포 앱에는 포함되지 않는다.

## 출처

- 시각 참조: 사용자가 제공한 MP4의 정면·회전 프레임 (`reference/`).
- 런타임 참조: 사용자의 `smiley-vtuber`, `animal-hood-girl-vtuber` 로컬 프로젝트.
- Three.js와 MediaPipe의 라이선스는 각 의존 패키지를 따른다.
- 기존 Gmarket 캐릭터 모델, 텍스처, 리액션 소품은 사용하지 않는다.
