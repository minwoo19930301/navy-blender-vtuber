"""microsoft/TRELLIS.2 Hugging Face Space 로 이미지 → GLB 를 뽑는다 (로컬 DINOv3 승인 전 임시 경로).

  ~/Documents/GitHub/trellis-mac/.venv/bin/python trellis/space_gen.py trellis/input-idle.png trellis/out-idle-s0.glb [seed] [resolution]
"""
import shutil
import sys
import time

from gradio_client import Client, handle_file
from huggingface_hub import get_token

src, out = sys.argv[1], sys.argv[2]
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
res = sys.argv[4] if len(sys.argv) > 4 else '1024'

t0 = time.time()
c = Client('microsoft/TRELLIS.2', token=get_token(), verbose=False, httpx_kwargs={'timeout': 600})
c.predict(api_name='/start_session')
img = c.predict(handle_file(src), api_name='/preprocess_image')
print('[space] preprocessed', img, f'{time.time() - t0:.0f}s', flush=True)
shutil.copy(img['path'] if isinstance(img, dict) else img, out.replace('.glb', '-prompt.png'))
c.predict(handle_file(img['path'] if isinstance(img, dict) else img), seed, res, api_name='/image_to_3d')
print('[space] generated', f'{time.time() - t0:.0f}s', flush=True)
glb, dl = c.predict(500000, 2048, api_name='/extract_glb')
shutil.copy(dl or glb, out)
print('[space] wrote', out, f'{time.time() - t0:.0f}s', flush=True)
