"""손. hand_L/R 노드(원점 = 손목) 아래 손바닥과 손가락 마디 노드 f{i}_{j}_{L|R}.
손 로컬(three): 손가락 = +Y, 손바닥이 보는 쪽 = +Z, 엄지 = -side 쪽 (side: L=+1, R=-1).
마디 노드는 회전 없이 만든다 (엄지 첫 마디만 벌어진 각도로 돌아가 있다). three 리그가 마디 rotation.x 로 손가락을 굽힌다.
"""
import bpy

from common import empty, get_mat, mesh_obj, sphere_bm

HK = 1.45
FINGER_LEN = [tuple(v * HK for v in t) for t in [(0.075, 0.05, 0.04), (0.085, 0.06, 0.045), (0.09, 0.065, 0.05), (0.085, 0.06, 0.045), (0.07, 0.048, 0.04)]]
FINGER_R = [v * HK for v in [0.036, 0.031, 0.032, 0.031, 0.028]]


def build(ctx):
    SKIN = get_mat('skin')
    for side, tag in ((1, 'L'), (-1, 'R')):
        hand = empty(f'hand_{tag}', (0, 0, 0), ctx['root'])
        mesh_obj(f'palm_{tag}', sphere_bm((0, 0.115 * HK, -0.005), (0.125 * HK, 0.13 * HK, 0.058 * HK), 32, 20,
                                          lambda x, y, z: (x, y, z * (0.8 if z > 0 else 1.0))), SKIN, hand)
        for i in range(5):
            if i == 0:
                base = (-side * 0.105 * HK, 0.07 * HK, 0.03 * HK)
            else:
                base = (side * (i - 2.5) * 0.058 * HK, (0.225 - (0.018 if i == 4 else 0)) * HK, 0.0)
            parent, pos = hand, base
            for j in range(3):
                jn = empty(f'f{i}_{j}_{tag}', pos, parent)
                L = FINGER_LEN[i][j]
                r = FINGER_R[i] * (1 - 0.1 * j)
                mesh_obj(f'f{i}_{j}_{tag}_mesh', sphere_bm((pos[0], pos[1] + L * 0.5, pos[2]), (r, L * 0.5 + r * 0.9, r * 0.92), 16, 12),
                         SKIN, jn, origin=pos)
                parent, pos = jn, (pos[0], pos[1] + L, pos[2])
            if i == 0:
                # 엄지는 안쪽(-side)으로 벌어져 있다: three z 축 회전 θ = Blender 오일러 y 회전 -θ
                first = bpy.data.objects[f'f0_0_{tag}']
                first.rotation_mode = 'XYZ'
                first.rotation_euler = (0, -side * 0.95, 0)
