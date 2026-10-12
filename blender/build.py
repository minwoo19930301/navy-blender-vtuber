"""
Navy 아바타 모델을 Blender에서 스크립트로 만들어 GLB로 내보낸다.

  Blender --background --python blender/build.py -- public/navy.glb [--only body,head] [--stats] [--no-export]

부위는 blender/parts/*.py 의 build(ctx) 가 만든다. 한 부위가 예외를 내도 나머지는 계속 만든다
(여러 사람이 부위를 동시에 고칠 때 서로 막지 않게). 실패한 부위는 [navy] FAIL 줄로 알린다.

노드 트리 (three.js 리그 src/model/rig.ts 가 이 이름으로 찾는다):
  navy
  ├ body ─ torso·shirt·lapel_*·collar·neck·arm_upper_*·arm_lower_*
  │   └ head_pivot (목) ─ head (두개골 중심) ─ head_skin·ear_*·nose·hair_*·face_decal·headphones
  ├ hand_L / hand_R ─ palm_*, f{i}_{j}_{L|R} (손가락 마디)
  └ props ─ desk·calculator·laptop
"""
import importlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'parts'))

import bpy  # noqa: E402

import common  # noqa: E402
from common import DIMS, empty  # noqa: E402

PARTS = ['body', 'head', 'hair', 'arms', 'hands', 'props']


def parse_args(argv):
    args = argv[argv.index('--') + 1:] if '--' in argv else []
    out = next((a for a in args if not a.startswith('--') and a.endswith('.glb')), None)
    only = None
    if '--only' in args:
        only = args[args.index('--only') + 1].split(',')
    return out, only, '--stats' in args, '--no-export' in args


def build_scene(only=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for mod in ['common', 'materials', *PARTS]:
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    import materials
    root = empty('navy')
    body = empty('body', (0, 0, 0), root)
    head_pivot = empty('head_pivot', DIMS['NECK_PIVOT'], body)
    head = empty('head', DIMS['HEAD_C'], head_pivot)
    props = empty('props', (0, 0, 0), root)
    ctx = {'root': root, 'body': body, 'head_pivot': head_pivot, 'head': head, 'props': props}
    materials.build(ctx)
    failed = []
    for name in PARTS:
        if only and name not in only:
            continue
        try:
            mod = importlib.import_module(name)
            mod.build(ctx)
            print(f'[navy] ok {name}')
        except Exception:
            failed.append(name)
            print(f'[navy] FAIL {name}')
            traceback.print_exc()
    # 마무리 단계 (materials.finish): 모든 부위가 만들어진 뒤 굽기 등. 무거운 일은 NAVY_BAKE=1 일 때만 한다
    if hasattr(materials, 'finish'):
        try:
            materials.finish(ctx)
            print('[navy] ok materials.finish')
        except Exception:
            failed.append('materials.finish')
            print('[navy] FAIL materials.finish')
            traceback.print_exc()
    common.deselect_all()
    common.update()
    return ctx, failed


def stats():
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    total = sum(len(o.data.polygons) for o in meshes)
    print(f'[stat] meshes={len(meshes)} polygons={total}')
    for o in sorted(meshes, key=lambda o: -len(o.data.polygons))[:15]:
        print('[stat]', o.name, len(o.data.polygons))


def export(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format='GLB',
        export_apply=True,
        export_yup=True,
        export_extras=False,
        export_materials='EXPORT',
    )
    print('[navy] exported', path)


if __name__ == '__main__':
    out, only, want_stats, no_export = parse_args(sys.argv)
    ctx, failed = build_scene(only)
    if want_stats:
        stats()
    if out and not no_export:
        export(out)
    if failed:
        sys.exit(1)
