# 이 캐릭터를 만든 방법

영상 속 캐릭터를 카메라로 움직이는 3D 버튜버로 만든 전 과정입니다.
명령은 저장소 루트에서 실행합니다. 모든 생성은 Apple Silicon Mac 한 대에서 무료로 돌렸습니다.

전체 흐름은 이렇습니다.

```
레퍼런스 영상 프레임
 ├─ (FLUX.2) 팔 벌린 A자 이미지 ─ (TRELLIS.2 로컬) 몸 3D ─ 텍스처 다시 굽기·정리 ─┐
 ├─ (TRELLIS.2 Space) 프레임 그대로 3D = "상자 모델" (얼굴이 가장 닮음) ──────────┤ 머리 이식
 └─ (FLUX.2 → TRELLIS.2) 손가락이 떨어진 손 ─────────────────────────────────────┤
                                                       리깅 (뼈·가중치·3D 입) ─ public/navy.glb ─ three.js 앱
```

## 0. 준비물

- Apple Silicon Mac, 메모리 24GB 이상 (TRELLIS 생성 중 최대 약 18GB를 씁니다).
- 디스크 약 60GB (모델 가중치: TRELLIS 15GB, FLUX.2 klein 9B 8bit 18GB, 그 밖).
- Node.js, `uv`, `ffmpeg`, `7z`(`brew install p7zip`).
- Hugging Face 계정. `facebook/dinov3-vitl16-pretrain-lvd1689m` 사용 신청이 승인돼야 합니다 (Meta가 직접 검토해서 몇 시간 걸릴 수 있습니다).

## 1. 도구 설치

Blender 5.2: `brew install --cask blender` 가 DMG 마운트에서 실패하는 환경이 있습니다. 그때는 받은 DMG를 7z로 풀어서 옮깁니다.

```sh
brew install --cask blender || true
7z x -y -o/tmp/bl ~/Library/Caches/Homebrew/downloads/*blender-*.dmg
ditto /tmp/bl/Blender/Blender.app /Applications/Blender.app
```

TRELLIS.2 Apple Silicon 포트(trellis-mac)와 이 저장소의 로컬 수정:

```sh
git clone https://github.com/shivampkumar/trellis-mac.git ~/Documents/GitHub/trellis-mac
cd ~/Documents/GitHub/trellis-mac && bash setup.sh && cd -
python3 trellis/patch_trellis_mac.py ~/Documents/GitHub/trellis-mac
~/Documents/GitHub/trellis-mac/.venv/bin/hf auth login
```

Xcode가 없으면 Metal 확장이 빌드되지 않고 CPU 굽기로 넘어갑니다. 그 CPU 굽기에 버그가 있어서(텍스처가 위아래로 뒤집혀 노이즈처럼 보임, 감마가 두 번 걸림) `patch_trellis_mac.py` 가 고칩니다.
게이트된 배경 제거 모델(briaai/RMBG-2.0) 대신 공개 BiRefNet을 쓰게 하는 수정도 같이 들어갑니다.

이미지 편집(FLUX.2 klein):

```sh
uv tool install --upgrade mflux
```

편의를 위해 아래에서 쓰는 변수입니다.

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
PY=~/Documents/GitHub/trellis-mac/.venv/bin/python
TM=~/Documents/GitHub/trellis-mac
```

## 2. 레퍼런스 프레임

```sh
for t in 0 2 4 6; do ffmpeg -v error -y -ss $t -i ~/Downloads/avatar-1791270641941691033-11.mp4 -frames:v 1 reference/idle-$t.png; done
```

`trellis/input-idle.png` 는 `reference/idle-0.png` 에서 오른쪽 아래 계산기를 배경색 다각형으로 지운 이미지입니다.
계산기가 남아 있으면 몸에 붙은 덩어리로 생성됩니다.

## 3. 팔 벌린 A자 이미지 (FLUX.2, 로컬, 약 2분)

레퍼런스는 손을 책상에 올린 채 화면 아래에서 잘려 있습니다. 그대로 3D로 만들면 몸이 상자에 들어간 모양이 되고 팔이 굳습니다.
같은 캐릭터를 팔을 벌리고 선 자세로 다시 그립니다.

```sh
mflux-generate-flux2-edit --model mlx-community/flux2-klein-9b-8bit --base-model flux2-klein-9b \
  --image-paths trellis/input-idle.png --prompt-file trellis/apose-prompt.txt \
  --width 1024 --height 1024 --seed 1 --low-ram --output trellis/apose-s1.png
```

## 4. 몸 3D (TRELLIS.2, 로컬)

```sh
cd $TM && source .venv/bin/activate
TRELLIS_REMBG=ZhengPeng7/BiRefNet python generate.py ~/Documents/GitHub/navy-blender-vtuber/trellis/apose-s1.png \
  --seed 42 --pipeline-type 512 --texture-size 2048 --output ~/Documents/GitHub/navy-blender-vtuber/trellis/apose-s1-t42b
cd -
```

생성은 약 5분이고, 20만 면 UV 펼치기에 약 40분이 더 걸립니다. 결과와 함께 `*_bake.npz`(복셀 색·메시)가 남아서 다음 단계부터는 생성 없이 다시 구울 수 있습니다.
`--pipeline-type 1024_cascade` 는 24GB 메모리에서 스왑이 40GB까지 차서 멈췄습니다. 512로 충분했습니다.

텍스처 다시 굽기와 정리:

```sh
$PY trellis/rebake.py trellis/apose-s1-t42b_bake.npz trellis/body-tex.glb      # 면 방향 통일·UV 밀도·색 정리 (약 1분)
$PY trellis/clean_tex3d.py trellis/body-tex.glb trellis/body-tex-clean.glb --cell 0.008   # 3D 칸 다수결로 튀는 점 정리
```

## 5. 얼굴용 "상자 모델" (TRELLIS.2 공식 Space)

로컬 결과는 FLUX가 다시 그린 얼굴이라 레퍼런스와 조금 다르고, 눈 가장자리가 번집니다.
레퍼런스 프레임을 그대로 넣은 공식 Space 결과가 얼굴·머리카락이 가장 닮았습니다 (몸은 상자에 들어간 모양이라 머리만 씁니다).

```sh
$PY trellis/space_gen.py trellis/input-idle.png trellis/out-idle-s0.glb 0 1024
```

이 단계는 이미지를 Hugging Face 서버에 올립니다. 무료 GPU 할당량이 하루 몇 분이라 두세 번 돌리면 다음 날까지 막힙니다.

## 6. 머리 이식

두 모델의 정면을 직교로 렌더하고 MediaPipe로 눈·입·턱 위치를 찾은 뒤, 상자 모델 머리를 몸에 맞춰 붙입니다.
크기는 레퍼런스 비율(머리 : 몸통 = 1.44)로 정하고, 목 띠는 텍스처 색으로 갈라 이음매를 셔츠 깃에 둡니다. 코끝도 여기서 살짝 뾰족하게 다듬습니다.

```sh
$B --background --python rig/front_ortho.py -- trellis/body-tex-clean.glb rig/body-front.png 1024
$PY rig/detect.py rig/body-front.png
ROTX=0 $B --background --python rig/front_ortho.py -- trellis/out-idle-s0.glb rig/box-front.png 1024
$PY rig/detect.py rig/box-front.png
$B --background --python rig/headswap.py -- trellis/body-tex-clean.glb trellis/out-idle-s0.glb trellis/body-swap.glb
```

`ROTX=0` 은 Space 결과가 이미 서 있어서 세우는 회전을 빼는 옵션입니다 (로컬 결과는 누워서 나옵니다).

## 7. 손 (손가락이 떨어진 손)

생성된 몸의 손은 네 손가락이 붙은 벙어리장갑 모양이라 손가락 트래킹이 안 됩니다. 손만 따로 만들어 소매에 끼웁니다.

```sh
mflux-generate-flux2-edit --model mlx-community/flux2-klein-9b-8bit --base-model flux2-klein-9b \
  --image-paths trellis/apose-s1.png --prompt-file trellis/hand-prompt.txt \
  --width 1024 --height 1024 --seed 11 --low-ram --output trellis/hand-s11.png
cd $TM && source .venv/bin/activate
TRELLIS_REMBG=ZhengPeng7/BiRefNet python generate.py ~/Documents/GitHub/navy-blender-vtuber/trellis/hand-s11.png \
  --seed 42 --pipeline-type 512 --texture-size 1024 --bake-faces 30000 --output ~/Documents/GitHub/navy-blender-vtuber/trellis/hand-s11-t42
cd -
$PY rig/hand/recolor.py trellis/hand-s11-t42.glb rig/hand/hand_R.glb 225 120 114   # 손 텍스처가 단색 빨강으로 구워져서 피부색으로
for v in front side top; do $B --background --python rig/hand/ortho.py -- rig/hand/hand_R.glb rig/hand/ortho-$v.png 1024 $v; done
$PY rig/hand/landmarks.py rig/hand/hand_R.glb    # MediaPipe 21점을 3D로 → rig/hand/hand_R.json
```

왼손은 리깅 때 오른손을 거울로 뒤집어 만듭니다.

## 8. 리깅

```sh
$B --background --python rig/front_ortho.py -- trellis/body-swap.glb rig/front.png 1024
$PY rig/detect.py rig/front.png
python3 rig/merge_landmarks.py       # 몸 관절은 이식 전 렌더 값, 얼굴은 이식 뒤 값
$B --background --python rig/rig.py -- trellis/body-swap.glb public/navy.glb --baked-face
```

`rig/rig.py` 가 하는 일 (몇 초):

- 세워서 앱 크기(재킷 밑단 y=0 ~ 머리 끝 3.05)로 맞추고, 바지를 잘라 냅니다.
- MediaPipe 관절을 소매 단면의 가운데로 옮겨 뼈를 세웁니다. 손가락 15개씩, 턱(`jaw`), 윗입술(`lip_up`)까지 45개입니다.
- 가중치는 Blender 자동 가중치가 이 메시에서 실패해서, 뼈까지 거리와 관절 사이 섞임 띠로 직접 계산합니다 (`rig/weights.py`).
- 생성 손을 소매 끝에서 잘라 내고 새 손을 끼웁니다 (`rig/handattach.py`). 소매 끝에는 남색 말린 단을 덧댑니다.
- 재킷·셔츠는 생성 텍스처의 흰 얼룩 때문에 단색 재질로 바꾸고, 라펠 가장자리 가시를 셔츠 경계선으로 밀어 정리합니다.
- 3D 입 (`rig/mouth.py`): 텍스처에서 구운 미소 선을 찾아 그 곡선으로 메시를 가르고, 입 뒤의 숨은 안쪽 껍질을 지우고, 입 속·혀를 넣습니다. 입 가운데만 크게 열리고 입꼬리는 거의 닫히게 가중치를 줍니다.
- 끝이 파여 보이던 오른눈은 왼눈을 좌우로 뒤집어 텍셀 단위로 옮깁니다 (`rig/hairtrim.py` 의 `mirror_eye`).
- 겨드랑이 다리, 얼굴 점 위치(`public/navy-rig.json`)를 만들어 함께 내보냅니다.

## 9. 앱에서 확인

카메라 없이 하네스로 렌더해 봅니다.

```sh
SIZE=720x720 npm run shot -- harness.html shots/front.png "preset=idle&ty=1.4&zoom=0.956&elev=4"
SIZE=480x480 SKIP_BUILD=1 npm run shot -- harness.html shots/talk.png "preset=mouth&ty=1.85&zoom=3.0"
SIZE=1500x1200 SKIP_BUILD=1 npm run shot -- harness.html shots/sheet.png "sheet=1&cols=5"
npm run app
```

`ty=1.4&zoom=0.956&elev=4` 는 `reference/idle-0.png` 와 같은 구도입니다. 프리셋은 `src/harness/presets.ts` 에 있습니다.

## 잘 안 됐던 것

- 코드로 부위를 만들어 조립한 모델(브랜치 `wip/procedural-parts`)은 부품을 끼운 장난감처럼 보였습니다. 공·국수 팔 같은 기하 캐릭터가 아니면 이미지→3D가 낫습니다.
- 레퍼런스 프레임을 그대로 넣으면 몸이 상자에 들어간 모양으로 나옵니다. 몸은 A자 이미지로, 얼굴은 레퍼런스로 따로 만들어 붙였습니다.
- 생성 텍스처의 옷은 가까이 보면 누더기처럼 얼룩져서 결국 단색 재질로 바꿨습니다.
- 옆머리 가닥을 지우면 머리카락 아래에 피부가 없어서 얼룩이 남습니다. 머리 모양을 바꾸려면 3단계 이미지부터 다시 만들어야 합니다.
- 카메라 깜빡임 값은 사람마다 범위가 다릅니다 (뜬 눈 0.05~0.5, 감은 눈 0.5~1.0). 눈꺼풀은 눈마다 그 범위를 배워서 그립니다 (`src/model/faceOverlay.ts`).
- 웃는 입 전체가 같이 벌어지면 무서워 보입니다. 가운데만 열리게 하고, 윗입술 뼈로 윗선을 폅니다.
