import * as T from 'three'

/**
 * GLB 머티리얼을 이름으로 찾아 three.js 쪽 질감으로 바꿔 끼운다.
 * Blender(blender/materials.py)는 색·거칠기·구운 텍스처를 넘기고, 클레이 느낌(시앤·클리어코트)은 여기서 준다.
 * GLB 에 실려 온 텍스처(map·normalMap·roughnessMap)는 그대로 옮긴다.
 */
type Tune = Partial<T.MeshPhysicalMaterialParameters>
const TUNE: Record<string, Tune> = {
  skin: { roughness: 0.55, sheen: 0.35, sheenColor: new T.Color('#ffd9cc'), sheenRoughness: 0.6, clearcoat: 0.05 },
  skin_shade: { roughness: 0.6, sheen: 0.3, sheenColor: new T.Color('#ffc9b8'), sheenRoughness: 0.6 },
  hair: { roughness: 0.42, clearcoat: 0.25, clearcoatRoughness: 0.45, sheen: 0.4, sheenColor: new T.Color('#5a6070'), sheenRoughness: 0.5 },
  jacket: { roughness: 0.92, sheen: 1.0, sheenColor: new T.Color('#4a5a8c'), sheenRoughness: 0.75 },
  shirt: { roughness: 0.85, sheen: 0.5, sheenColor: new T.Color('#ffffff'), sheenRoughness: 0.7 },
}

export function upgradeMaterial(src: T.Material): T.Material {
  const s = src as T.MeshStandardMaterial
  const key = Object.keys(TUNE).find(k => s.name === k || s.name.startsWith(k + '.')) ?? s.name
  const m = new T.MeshPhysicalMaterial({
    name: s.name,
    color: s.color?.clone() ?? new T.Color(1, 1, 1),
    map: s.map ?? null,
    normalMap: s.normalMap ?? null,
    roughnessMap: s.roughnessMap ?? null,
    roughness: s.roughness ?? 0.7,
    metalness: s.metalness ?? 0,
    ...(TUNE[key] ?? {}),
  })
  if (s.normalScale) m.normalScale.copy(s.normalScale)
  return m
}
