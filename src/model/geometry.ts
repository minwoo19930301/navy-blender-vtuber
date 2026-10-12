import * as T from 'three'
export const sphere = new T.SphereGeometry(1, 28, 20)
export function ellipsoid(parent: T.Object3D, mat: T.Material, pos: number[], scale: number[], name = '') {
  const m = new T.Mesh(sphere, mat)
  m.position.set(pos[0], pos[1], pos[2]); m.scale.set(scale[0], scale[1], scale[2]); m.name = name
  parent.add(m); return m
}
/** Closed, tapered sculpted lock. Width runs across the curve; depth faces the camera. */
export function lock(points: number[][], width: number, depth: number) {
  const curve = new T.CatmullRomCurve3(points.map(p => new T.Vector3(...p)))
  const pos: number[] = [], uv: number[] = [], idx: number[] = []
  const n = 26, ring = 10
  for (let i = 0; i <= n; i++) {
    const t = i / n, p = curve.getPoint(t), tangent = curve.getTangent(t)
    const across = new T.Vector3(-tangent.y, tangent.x, 0).normalize()
    const front = new T.Vector3().crossVectors(across, tangent).normalize()
    const taper = Math.max(.025, Math.pow(Math.sin(Math.PI * t), .55))
    for (let j = 0; j <= ring; j++) {
      const a = j / ring * Math.PI * 2
      const v = p.clone().addScaledVector(across, Math.cos(a) * width * taper).addScaledVector(front, Math.sin(a) * depth * taper)
      pos.push(v.x, v.y, v.z); uv.push(j / ring, t)
      if (i < n && j < ring) { const k = i * (ring + 1) + j; idx.push(k,k+ring+1,k+1,k+1,k+ring+1,k+ring+2) }
    }
  }
  const g = new T.BufferGeometry(); g.setAttribute('position',new T.Float32BufferAttribute(pos,3));g.setAttribute('uv',new T.Float32BufferAttribute(uv,2));g.setIndex(idx);g.computeVertexNormals();return g
}
export function patch(parent: T.Object3D, mat: T.Material, points: number[][], depth = .02) {
  const shape = new T.Shape(); shape.moveTo(points[0][0], points[0][1]); points.slice(1).forEach(p=>shape.lineTo(p[0],p[1]));shape.closePath()
  const g = new T.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelSegments: 2, steps: 1, bevelSize: .01, bevelThickness: .008 })
  const m = new T.Mesh(g,mat); parent.add(m);return m
}
export function faceZ(x: number, y: number) {
  const taper = 1 - .13 * Math.max(0, -y / .59)
  return .43 * Math.sqrt(Math.max(.002, 1 - (x / (.52 * taper)) ** 2 - (y / .59) ** 2))
}
