"""texclean 만 빠르게 돌려 보는 개발용 스크립트: body-tex_stage.npz (rebake.py --stage) → PNG
  python trellis/texclean_dev.py trellis/body-tex_stage.npz OUT.png"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from texclean import clean
d = np.load(sys.argv[1])
out = clean(d['rgb'].astype(np.float32), d['cid'], d['pos'], d['mask'], -0.02, print)
Image.fromarray((out + 0.5).astype(np.uint8)).save(sys.argv[2])
