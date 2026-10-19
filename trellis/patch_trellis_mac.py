"""trellis-mac(TRELLIS.2 Apple Silicon 포트)에 이 저장소가 쓴 로컬 수정을 입힌다. 여러 번 실행해도 된다.

  python3 trellis/patch_trellis_mac.py ~/Documents/GitHub/trellis-mac

1. backends/texture_baker.py·generate.py: trellis/trellis-mac.patch (텍스처 굽기 v방향·텍셀 중심·감마 버그, UV 여백, --bake-faces, 다시 굽기용 *_bake.npz 저장)
2. TRELLIS.2/.../rembg/BiRefNet.py: 배경 제거 모델을 환경변수 TRELLIS_REMBG 로 바꿀 수 있게 (게이트된 briaai/RMBG-2.0 대신 공개 ZhengPeng7/BiRefNet), float32 로 맞춤
3. venv 에 einops(BiRefNet), gradio_client(Space 호출), mediapipe(관절 찾기) 설치
setup.sh 를 먼저 실행해 둔 trellis-mac 에 쓴다 (기준 커밋 trellis-mac d58628f, TRELLIS.2 75fbf01).
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
tm = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.home() / 'Documents/GitHub/trellis-mac'

# 1) git 패치
gen = (tm / 'generate.py').read_text()
if '--bake-faces' in gen:
    print('[patch] generate.py·texture_baker.py: already patched')
else:
    subprocess.run(['git', 'apply', str(HERE / 'trellis-mac.patch')], cwd=tm, check=True)
    print('[patch] applied trellis-mac.patch')

# 2) BiRefNet
p = tm / 'TRELLIS.2/trellis2/pipelines/rembg/BiRefNet.py'
s = p.read_text()
if 'TRELLIS_REMBG' not in s:
    a = '''    def __init__(self, model_name: str = "ZhengPeng7/BiRefNet"):
        self.model = AutoModelForImageSegmentation.from_pretrained('''
    b = '''    def __init__(self, model_name: str = "ZhengPeng7/BiRefNet"):
        # 로컬 수정: 게이트된 briaai/RMBG-2.0 대신 같은 구조의 공개 BiRefNet(MIT)을 쓸 수 있게 환경변수로 바꾼다
        import os
        model_name = os.environ.get("TRELLIS_REMBG", model_name)
        self.model = AutoModelForImageSegmentation.from_pretrained('''
    assert a in s, 'BiRefNet.py 모양이 예상과 다르다'
    s = s.replace(a, b, 1)
if 'self.model.float()' not in s:
    s = s.replace('''        self.model.eval()''', '''        # 로컬 수정: 공개 BiRefNet 가중치는 half 로 실려 와 float 입력과 안 맞는다 → float32 로 맞춘다
        self.model.float()
        self.model.eval()''', 1)
p.write_text(s)
print('[patch] BiRefNet.py ok')

# 3) 추가 패키지
py = tm / '.venv/bin/python'
subprocess.run(['uv', 'pip', 'install', '--python', str(py), '-q', 'einops', 'gradio_client', 'mediapipe'], check=True)
print('[patch] extra packages ok')
