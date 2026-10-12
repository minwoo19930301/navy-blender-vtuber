"""
이름 붙은 머티리얼을 만든다. 부위 스크립트는 common.get_mat(이름) 으로만 가져다 쓴다.

glTF 로 나가는 건 Principled BSDF 의 기본값·연결된 이미지 텍스처(베이스컬러·거칠기·노멀)와
KHR 확장(sheen·clearcoat·specular)뿐이다. 절차적 노드는 그대로는 안 나가므로 질감은 이미지로 구워야 한다.
three.js 쪽(src/model/materials.ts)이 이름으로 재질을 다듬는다.
"""
import bpy

from common import srgb

PALETTE = {
    'skin': ('f6d3c2', 0.55),
    'skin_shade': ('e8ab96', 0.6),
    'hair': ('17181e', 0.45),
    'jacket': ('1f2a4b', 0.9),
    'shirt': ('f4f2ef', 0.85),
    'face_decal': ('ffffff', 1.0),
}


def build(ctx):
    for name, (hexcol, rough) in PALETTE.items():
        m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get('Principled BSDF')
        rgb = srgb(hexcol)
        bsdf.inputs['Base Color'].default_value = (*rgb, 1)
        bsdf.inputs['Roughness'].default_value = rough
        m.diffuse_color = (*rgb, 1)
