"""
TRELLIS 메시를 깨끗한 한 덩어리로 다시 짜고, 원래 색을 새 표면에 다시 굽는다.

  Blender --background --python rig/clean_bake.py -- IN.glb OUT.glb [--voxel 0.003] [--faces 150000] [--tex 4096] [--preview OUT.png]

왜: Mac 용 TRELLIS 는 구멍 메우기가 빠져 있고(작은 구멍 수십 개), 재킷·셔츠 경계가 얇은 조각(흰 실밥)으로 나온다.
머리 이식 모델은 목에서 두 껍질이 겹친다. 리깅 전에 표면을 한 번 정리한다.

1. 작은 구멍 메우기 (경계 고리 HOLE_EDGES 이하)
2. 복셀 리메시 → 닫힌 한 덩어리 (얇은 조각·실밥은 사라지고 목 이음매는 붙는다)
3. 데시메이트 + 살짝 매끈하게
4. 스마트 UV → Cycles 로 원래 메시의 색을 굽는다 (selected → active, 가까운 거리만)
IN/OUT 은 rig.py 입력과 같은 틀(가져오면 눕혀 나오는 GLB)이다. 좌표는 건드리지 않는다.
"""
import math
import sys
from pathlib import Path

import bmesh
import bpy

argv = sys.argv[sys.argv.index('--') + 1:]
SRC, OUT = argv[0], Path(argv[1]).resolve()


def opt(name, default, cast=float):
    return cast(argv[argv.index(name) + 1]) if name in argv else default


VOXEL = opt('--voxel', 0.003)
FACES = opt('--faces', 150000, int)
TEX = opt('--tex', 4096, int)
PREVIEW = argv[argv.index('--preview') + 1] if '--preview' in argv else None
HOLE_EDGES = 120  # 이보다 큰 고리(밑단·소매 끝)는 그대로 둔다 — 밑단은 책상 가림판이 가리고 소매 끝은 rig.py 가 손으로 바꾼다


def log(*a):
    print('[clean]', *a, flush=True)


def activate(o):
    for ob in bpy.context.selected_objects:
        ob.select_set(False)
    bpy.context.view_layer.objects.active = o
    o.select_set(True)


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
src = [o for o in bpy.context.scene.objects if o.type == 'MESH'][0]
src.data.transform(src.matrix_world)
src.parent = None
src.matrix_world.identity()
for o in list(bpy.context.scene.objects):
    if o is not src:
        bpy.data.objects.remove(o)
src.name = 'source'
log('source faces', len(src.data.polygons), 'materials', len(src.data.materials))

# ───────── 1. 사본에 작은 구멍 메우기
dst = src.copy()
dst.data = src.data.copy()
dst.name = 'clean'
bpy.context.scene.collection.objects.link(dst)
bm = bmesh.new()
bm.from_mesh(dst.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
before = sum(1 for e in bm.edges if e.is_boundary)
bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=HOLE_EDGES)
after = sum(1 for e in bm.edges if e.is_boundary)
bm.to_mesh(dst.data)
bm.free()
log(f'boundary edges {before} -> {after}')

# ───────── 2. 복셀 리메시
rm = dst.modifiers.new('remesh', 'REMESH')
rm.mode = 'VOXEL'
rm.voxel_size = VOXEL
rm.use_smooth_shade = True
activate(dst)
bpy.ops.object.modifier_apply(modifier=rm.name)
log('remeshed faces', len(dst.data.polygons))

# 떠돌이 작은 조각 제거 (리메시가 실밥 끝을 작은 덩어리로 남기기도 한다)
bm = bmesh.new()
bm.from_mesh(dst.data)
bm.verts.ensure_lookup_table()
seen, islands = set(), []
for v in bm.verts:
    if v.index in seen:
        continue
    stack, isl = [v], []
    seen.add(v.index)
    while stack:
        u = stack.pop()
        isl.append(u)
        for e in u.link_edges:
            w = e.other_vert(u)
            if w.index not in seen:
                seen.add(w.index)
                stack.append(w)
    islands.append(isl)
islands.sort(key=len, reverse=True)
small = [v for isl in islands[1:] if len(isl) < 0.002 * len(bm.verts) for v in isl]
bmesh.ops.delete(bm, geom=small, context='VERTS')
bm.to_mesh(dst.data)
bm.free()
log(f'islands {len(islands)}, removed small verts {len(small)}')

# ───────── 3. 데시메이트 + 매끈하게
if len(dst.data.polygons) > FACES:
    dm = dst.modifiers.new('dec', 'DECIMATE')
    dm.ratio = FACES / len(dst.data.polygons)
    activate(dst)
    bpy.ops.object.modifier_apply(modifier=dm.name)
sm = dst.modifiers.new('smooth', 'CORRECTIVE_SMOOTH')
sm.iterations = 3
sm.scale = 1.0
activate(dst)
bpy.ops.object.modifier_apply(modifier=sm.name)
for p in dst.data.polygons:
    p.use_smooth = True
log('final faces', len(dst.data.polygons))

# ───────── 4. UV + 굽기
dst.data.materials.clear()
mat = bpy.data.materials.new('navy_baked')
mat.use_nodes = True
nt = mat.node_tree
bsdf = nt.nodes.get('Principled BSDF')
img = bpy.data.images.new('navy_baked', TEX, TEX, alpha=False)
img.colorspace_settings.name = 'sRGB'
tex = nt.nodes.new('ShaderNodeTexImage')
tex.image = img
nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
bsdf.inputs['Roughness'].default_value = 0.85
nt.nodes.active = tex
dst.data.materials.append(mat)

activate(dst)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.002, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
bpy.ops.object.mode_set(mode='OBJECT')
log('uv done')

sc = bpy.context.scene
sc.render.engine = 'CYCLES'
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'METAL'
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    sc.cycles.device = 'GPU'
except Exception as e:  # GPU 가 안 되면 CPU
    log('gpu setup failed, cpu bake', e)
sc.cycles.samples = 1
bk = sc.render.bake
bk.use_selected_to_active = True
bk.use_cage = False
bk.cage_extrusion = 0.006
bk.max_ray_distance = 0.02
bk.margin = 8
bk.use_pass_direct = False
bk.use_pass_indirect = False
bk.use_pass_color = True

for ob in bpy.context.selected_objects:
    ob.select_set(False)
src.select_set(True)
dst.select_set(True)
bpy.context.view_layer.objects.active = dst
bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, use_selected_to_active=True, cage_extrusion=0.006, max_ray_distance=0.02, margin=8)
log('baked')
img.filepath_raw = str(OUT.with_suffix('.png'))
img.file_format = 'PNG'
img.save()
img.pack()

# ───────── 내보내기 (source 는 지운다)
bpy.data.objects.remove(src)
activate(dst)
bpy.ops.export_scene.gltf(filepath=str(OUT), export_format='GLB', use_selection=True, export_yup=True, export_apply=True,
                          export_image_format='JPEG', export_jpeg_quality=92)
log('wrote', OUT)
