import * as T from 'three'

/**
 * TRELLIS 가 구운 텍스처를 그대로 알베도로 쓴다. 금속·반사 없이 거칠게 — 플라스틱처럼 번들거리면 레퍼런스(점토 느낌)에서 멀어진다.
 * GLB 의 metallicRoughness 텍스처는 구운 값이 아니라 의미가 없어서 버리고 상수로 둔다.
 */
export function createBodyMaterial(src: T.Material): T.Material {
  const s = src as T.MeshStandardMaterial
  // 확인용: ?side=front|double (면 방향 실험)
  const sideQ = new URLSearchParams(location.search).get('side')
  const side = sideQ === 'front' ? T.FrontSide : T.DoubleSide
  // 확인용: ?unlit=1 이면 구운 색 그대로 (조명 영향 없이 텍스처 색을 본다)
  if (new URLSearchParams(location.search).get('unlit') === '1') {
    const u = new T.MeshBasicMaterial({ map: s.map ?? null, side: T.DoubleSide })
    if (u.map) u.map.colorSpace = T.SRGBColorSpace
    return u
  }
  const m = new T.MeshStandardMaterial({
    name: s.name || 'navy_body',
    map: s.map ?? null,
    // 텍스처 없는 재질(소매 단 등)은 GLB 의 기본색을 그대로 쓴다
    color: s.map ? 0xffffff : (s.color?.clone() ?? new T.Color(0xffffff)),
    roughness: 0.82,
    metalness: 0,
    side,
  })
  if (m.map) {
    m.map.colorSpace = T.SRGBColorSpace
    m.map.anisotropy = 4
  }
  return m
}
