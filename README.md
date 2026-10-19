# Navy Blender VTuber

아바타 영상(`avatar-1791270641941691033-11.mp4`)의 캐릭터를 카메라로 움직이는 macOS 데스크톱 VTuber입니다.
검은 가르마 머리, 큰 눈, 남색 재킷과 흰 티셔츠를 입은 클레이 느낌의 상반신 캐릭터입니다.

손으로 짠 3D 모델은 부품을 끼운 장난감처럼 보여서 쓰지 않았습니다.
대신 이미지에서 3D를 만드는 모델(TRELLIS.2)로 캐릭터를 만들고, 뼈대와 얼굴 동작을 붙였습니다.
모든 생성은 이 Mac에서 무료로 돌렸습니다.

## 실행

```sh
npm ci
npm run app
```

처음 실행하면 macOS 카메라 권한을 묻습니다. 카메라 영상은 로컬 MediaPipe에서만 처리하고 저장하지 않습니다.
카메라가 없어도 대기 동작과 리액션은 됩니다.
`npm run app` 은 저장소의 코드를 불러오는 런처 번들을 만들어서, 코드를 고쳐도 카메라 권한을 다시 묻지 않습니다.

## 조작

| 조작 | 동작 |
|---|---|
| 캐릭터 드래그 | 위치 이동 |
| 우클릭 | 보기 옵션·리액션·종료 |
| Cmd+Shift+C | 카메라 켜기 / 끄기 |
| Cmd+Shift+M | 숨기기 / 보이기 (숨기면 카메라와 렌더가 멈춥니다) |
| Cmd+Shift+B | 투명 / 크로마키 / 단색 배경 |
| Cmd+Shift+X | 좌우 반전 |
| Cmd+Shift+D | 트래킹 디버그 |
| Cmd+Shift+- / = / 0 | 작게 / 크게 / 크기 리셋 |
| Ctrl+Option+1~9 | 웃음 / 사랑 / 인사 / 놀람 / 감동 / 뽀뽀 / 화남 / 졸림 / 축하 |
| Ctrl+Option+0 | 일하는 척 (헤드폰을 쓰고 노트북을 두드립니다) |
| Ctrl+Option+Esc | 리액션 취소 |

창에 포커스가 있으면 숫자 1~0으로 리액션, Esc로 취소합니다.

## 모델을 만든 과정

1. 레퍼런스 프레임을 FLUX.2 klein(mflux, 로컬)으로 팔을 벌린 A자 자세 이미지로 바꿨습니다 (`trellis/apose-s1.png`).
2. TRELLIS.2 Apple Silicon 포트(trellis-mac, 로컬)로 몸 전체를 3D로 만들었습니다. 텍스처 굽기 버그를 고쳐 다시 구웠습니다 (`trellis/rebake.py`).
3. 얼굴은 레퍼런스 프레임에서 바로 만든 모델이 더 닮아서 그 머리를 몸에 이식했습니다 (`rig/headswap.py`).
4. `rig/rig.py` 가 뼈대(45개: 손가락 15개씩, 턱·윗입술 포함)와 절차 가중치를 넣고 `public/navy.glb` 로 내보냅니다.
   생성된 손은 손가락이 붙어 있어서 따로 만든 손(`rig/hand/`)으로 바꿨습니다.
   재킷·셔츠는 생성 텍스처의 노이즈 때문에 단색 재질로 바꿨습니다.
5. 입은 구운 미소 선을 따라 메시를 갈라 턱 뼈로 엽니다 (`rig/mouth.py`). 깜빡임은 `src/model/faceOverlay.ts` 가 덧그립니다.

처음부터 따라 만드는 전체 명령과 잘 안 됐던 것들은 [docs/HOW-TO-BUILD.md](docs/HOW-TO-BUILD.md) 에 있습니다.

모델 다시 만들기 (리깅만):

```sh
/Applications/Blender.app/Contents/MacOS/Blender --background --python rig/rig.py -- trellis/body-swap.glb public/navy.glb --baked-face
```

`trellis/body-swap.glb` 만 저장소에 들어 있습니다. 그 앞 단계의 생성물(TRELLIS 결과 등)은 크기 때문에 빼 두었습니다.

## 알려진 한계

- 생성 모델이라 가까이 보면 표면이 조금 울퉁불퉁합니다.
- 머리카락과 피부가 한 텍스처라 옆머리 모양을 바꾸려면 이미지 단계부터 다시 만들어야 합니다.
- 팔을 크게 들면 겨드랑이가 조금 거칠어집니다.

## 출처

- 시각 참조: 사용자가 제공한 MP4 프레임 (`reference/`).
- 생성 모델: TRELLIS.2 (MIT), DINOv3 (Meta 라이선스), FLUX.2 klein 9B (Black Forest Labs 모델 라이선스), 배경 제거 BiRefNet (MIT). 생성물에는 각 모델의 라이선스 조건이 따릅니다.
- 트래킹·오버레이 코드는 `smiley-vtuber`, `animal-hood-girl-vtuber` 를 바탕으로 했습니다.
