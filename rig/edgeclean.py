"""열린 가장자리(재킷 앞섶·깃·소매 끝) 다듬기.

TRELLIS 메시는 열린 가장자리가 톱니처럼 들쭉날쭉하고, 한 변만 붙은 가는 조각(실밥)이 삐져나와 있다.
1. 가시 깎기: 열린 변이 2개 이상인 면(한쪽만 붙은 삼각형 조각)을 몇 번 반복해 지운다.
2. 가장자리 펴기: 열린 가장자리 정점을 고리 이웃의 평균 쪽으로 여러 번 당겨 톱니를 매끈한 선으로 편다.
"""
import bmesh


def erode_spikes(bm, iters=4):
    removed = 0
    for _ in range(iters):
        dead = [f for f in bm.faces if sum(1 for e in f.edges if e.is_boundary) >= 2]
        if not dead:
            break
        bmesh.ops.delete(bm, geom=dead, context='FACES')
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context='VERTS')
        removed += len(dead)
    return removed


def relax_boundary(bm, iters=6, factor=0.5):
    """열린 가장자리 정점만 고리 위 이웃 두 점의 중점 쪽으로 당긴다 (안쪽 정점은 그대로)"""
    for _ in range(iters):
        moves = []
        for v in bm.verts:
            nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
            if len(nb) != 2:
                continue
            mid = (nb[0].co + nb[1].co) / 2
            moves.append((v, v.co + (mid - v.co) * factor))
        for v, co in moves:
            v.co = co
    return len(moves) if iters else 0


def clean_edges(bm, spike_iters=4, relax_iters=6):
    n = erode_spikes(bm, spike_iters)
    m = relax_boundary(bm, relax_iters)
    return n, m
