"""소매(위팔·아래팔). body 노드 자식. 원점 = 몸쪽 관절, +Y 로 뻗는다 (three 리그가 방향을 돌린다)."""
from common import DIMS, get_mat, loft_bm, mesh_obj, subsurf


def build(ctx):
    JACKET = get_mat('jacket')
    for tag in ('L', 'R'):
        up = mesh_obj(f'arm_upper_{tag}', loft_bm([
            (-0.10, 0.17, 0.17, 0, 0), (0.0, 0.21, 0.21, 0, 0), (0.25, 0.225, 0.22, 0, 0),
            (0.50, 0.21, 0.20, 0, 0), (DIMS['UPPER_LEN'] + 0.04, 0.19, 0.185, 0, 0),
        ], seg=28), JACKET, ctx['body'])
        subsurf(up, 2)
        lo = mesh_obj(f'arm_lower_{tag}', loft_bm([
            (-0.08, 0.17, 0.17, 0, 0), (0.05, 0.195, 0.19, 0, 0), (0.35, 0.18, 0.175, 0, 0),
            (0.58, 0.165, 0.16, 0, 0), (0.64, 0.17, 0.165, 0, 0), (0.66, 0.12, 0.12, 0, 0),
        ], seg=28), JACKET, ctx['body'])
        subsurf(lo, 2)
