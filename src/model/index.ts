import * as T from 'three'
import { mergeGeometries, mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js'
import type { MingoModel, RigFrame, ArmPose } from '../contract'
import { neutralFrame } from '../contract'
import { ellipsoid, sphere, lock, patch } from './geometry'
import { createFace } from './face'
import { createHand } from './hand'
const clamp=(v:number,a:number,b:number)=>Math.min(b,Math.max(a,Number.isFinite(v)?v:0))
const mat=(color:number,roughness=.75)=>new T.MeshStandardMaterial({color,roughness})
export function createNavy():MingoModel{
 const root=new T.Group();root.name='Navy — reference-inspired upper-body avatar'
 const skin=mat(0xf4c6a6,.66),earSkin=mat(0xd9977e),hairMat=mat(0x24252b,.52),navy=mat(0x222e4b,.88),lapelMat=mat(0x293753,.83),white=mat(0xf7f3ee,.92),seam=mat(0x152039)
 root.add(new T.HemisphereLight(0xfff5eb,0xc8b9af,2.2))
 const key=new T.DirectionalLight(0xfff1df,2.2);key.position.set(-3,5,5);root.add(key)
 const fill=new T.DirectionalLight(0xd9e7ff,1.2);fill.position.set(3,2,3);root.add(fill)
 const rim=new T.DirectionalLight(0xe2e7ff,2.2);rim.position.set(1,4,-3);root.add(rim)
 const body=new T.Group();body.position.y=.23;root.add(body)
 // A softly rounded jacket with a white crew-neck shirt and folded lapels.
 const torsoPositions:number[]=[],torsoIndices:number[]=[]
 const sections=[[.045,.30,.15],[.065,.36,.19],[.15,.40,.22],[.45,.425,.233],[.70,.43,.223],[.84,.365,.194],[.96,.168,.132]]
 for(let i=0;i<sections.length;i++)for(let j=0;j<=48;j++){
  const [y,w,d]=sections[i],a=j/48*Math.PI*2;torsoPositions.push(Math.cos(a)*w,y,Math.sin(a)*d)
  if(i<sections.length-1&&j<48){const k=i*49+j;torsoIndices.push(k,k+49,k+1,k+1,k+49,k+50)}
 }
 const tg=new T.BufferGeometry();tg.setAttribute('position',new T.Float32BufferAttribute(torsoPositions,3));tg.setIndex(torsoIndices);tg.computeVertexNormals();body.add(new T.Mesh(tg,navy))
 const shirtShape=new T.Shape();shirtShape.moveTo(-.164,.958);shirtShape.quadraticCurveTo(0,.82,.164,.958);shirtShape.lineTo(.225,.75);shirtShape.lineTo(.21,.08);shirtShape.lineTo(-.21,.08);shirtShape.lineTo(-.225,.75);shirtShape.closePath()
 const shirt=new T.Mesh(new T.ShapeGeometry(shirtShape,24),white);shirt.position.z=.239;body.add(shirt)
 ellipsoid(body,skin,[0,1.00,0],[.157,.23,.148],'Neck')
 for(const side of [-1,1]){
  const front=patch(body,navy,[[side*.172,.91],[side*.36,.81],[side*.40,.65],[side*.375,.08],[side*.12,.08],[side*.16,.46]],.024);front.position.z=.24;front.name='Jacket front'
  const lapel=patch(body,lapelMat,[[side*.168,.952],[side*.31,.89],[side*.345,.74],[side*.267,.727],[side*.298,.66],[side*.118,.39],[side*.178,.68]],.022)
  lapel.position.z=.272;lapel.name='Notched blazer lapel'
  const pocket=patch(body,seam,[[side*.23,.29],[side*.34,.30],[side*.34,.29],[side*.23,.28]],.003);pocket.position.z=.276
  ellipsoid(body,seam,[side*.152,.25,.29],[.014,.014,.007],'Jacket button')
 }
 // Conform the shirt and lapels to the rounded torso, including three-quarter views.
 for(const child of body.children){
  if(!(child instanceof T.Mesh)||!(child.geometry instanceof T.ShapeGeometry||child.geometry instanceof T.ExtrudeGeometry))continue
  // Tessellate before bending: a single large triangle would cut through the curved jacket.
  const flat=child.geometry.toNonIndexed(),input=flat.attributes.position,verts:number[]=[]
  function split(a:T.Vector3,b:T.Vector3,c:T.Vector3,depth:number){
   if(depth<5&&Math.max(a.distanceTo(b),b.distanceTo(c),c.distanceTo(a))>.09){
    const ab=a.clone().add(b).multiplyScalar(.5),bc=b.clone().add(c).multiplyScalar(.5),ca=c.clone().add(a).multiplyScalar(.5)
    split(a,ab,ca,depth+1);split(ab,b,bc,depth+1);split(ca,bc,c,depth+1);split(ab,bc,ca,depth+1)
   }else verts.push(...a.toArray(),...b.toArray(),...c.toArray())
  }
  for(let i=0;i<input.count;i+=3)split(new T.Vector3().fromBufferAttribute(input,i),new T.Vector3().fromBufferAttribute(input,i+1),new T.Vector3().fromBufferAttribute(input,i+2),0)
  const curved=new T.BufferGeometry();curved.setAttribute('position',new T.Float32BufferAttribute(verts,3));child.geometry.dispose();child.geometry=curved
  const pos=curved.attributes.position, offset=child.name.includes('lapel')?.035:.017
  for(let i=0;i<pos.count;i++){
   const x=pos.getX(i),y=pos.getY(i);let k=0;while(k<sections.length-2&&sections[k+1][0]<y)k++
   const a=sections[k],b=sections[k+1],t=clamp((y-a[0])/(b[0]-a[0]),0,1),w=a[1]+(b[1]-a[1])*t,d=a[2]+(b[2]-a[2])*t
   pos.setZ(i,d*Math.sqrt(Math.max(.02,1-(x/w)**2))+pos.getZ(i)+offset)
  }
  child.position.z=0;child.geometry=mergeVertices(child.geometry);child.geometry.computeVertexNormals()
 }
 const headPivot=new T.Group();headPivot.position.set(0,1.15,0);body.add(headPivot)
 const head=new T.Group();head.position.set(0,.49,.01);headPivot.add(head)
 const hg=sphere.clone(),hp=hg.attributes.position
 for(let i=0;i<hp.count;i++){const y=hp.getY(i);hp.setXYZ(i,hp.getX(i)*.52*(1-.13*Math.max(0,-y)),y*.59,hp.getZ(i)*.43)}hg.computeVertexNormals()
 const skull=new T.Mesh(hg,skin);skull.name='Rounded head with tapered jaw';head.add(skull)
 for(const side of [-1,1]){
  ellipsoid(head,skin,[side*.495,-.055,-.012],[.098,.149,.069],'Ear')
  ellipsoid(head,earSkin,[side*.513,-.04,.043],[.056,.091,.016],'Ear concha')
  ellipsoid(head,skin,[side*.491,-.08,.06],[.033,.064,.018],'Ear fold')
 }
 ellipsoid(head,skin,[0,-.156,.419],[.060,.052,.071],'Button nose')
 ellipsoid(head,earSkin,[0,-.183,.456],[.021,.007,.009],'Nose underside')
 const face=createFace();head.add(face.mesh)
 // Hair cap uses a higher hairline at the forehead and wraps fully around the back.
 const capPos:number[]=[],capIdx:number[]=[];const rings=24,segments=64
 for(let i=0;i<=rings;i++)for(let j=0;j<=segments;j++){
  const phi=j/segments*Math.PI*2,front=Math.max(0,Math.sin(phi));const maxTheta=Math.sin(phi)>0?1.60-.46*Math.pow(front,.4):1.87
  const theta=i/rings*maxTheta
  capPos.push(.548*Math.sin(theta)*Math.cos(phi),.636*Math.cos(theta)+.015,.465*Math.sin(theta)*Math.sin(phi)-.025)
  if(i<rings&&j<segments){const k=i*(segments+1)+j;capIdx.push(k,k+1,k+segments+1,k+1,k+segments+2,k+segments+1)}
 }
 const cap=new T.BufferGeometry();cap.setAttribute('position',new T.Float32BufferAttribute(capPos,3));cap.setIndex(capIdx);cap.computeVertexNormals();head.add(new T.Mesh(cap,hairMat))
 const locks:T.BufferGeometry[]=[]
 // Broad swept locks, a part on the viewer's right, and a long fringe on the left.
 const swept = [
  [[.14,.61,.12],[-.05,.66,.19],[-.34,.56,.23],[-.52,.27,.10]],
  [[.18,.60,.22],[-.02,.65,.29],[-.36,.50,.34],[-.51,.19,.23]],
  [[.19,.565,.30],[.02,.62,.36],[-.31,.46,.42],[-.47,.12,.32]],
  [[.19,.525,.355],[.06,.58,.405],[-.22,.40,.474],[-.375,.16,.418]],
  [[.20,.487,.391],[.105,.515,.454],[-.11,.34,.51],[-.26,.125,.459]],
  [[.215,.459,.391],[.16,.46,.47],[.015,.28,.514],[-.10,.19,.48]],
 ]
 swept.forEach((pts,i)=>locks.push(lock(pts,.104-i*.005,.031)))
 for(let i=0;i<5;i++){
  locks.push(lock([[.235+i*.011,.567-i*.016,.245-i*.041],[.35+i*.029,.49-i*.014,.37-i*.04],[.415+i*.02,.34-i*.039,.368-i*.035],[.35+i*.041,.22-i*.059,.368-i*.033]],.076,.029))
 }
 const hair=new T.Mesh(mergeGeometries(locks),hairMat);hair.name='Sculpted side-part hair';head.add(hair)
 // Sideburns, tapered into the hair cap.
 for(const side of [-1,1])head.add(new T.Mesh(lock([[side*.50,.25,.06],[side*.515,.13,.09],[side*.482,.003,.11]],.045,.021),hairMat))
 const restHand=[new T.Vector3(.18,-.33,.93),new T.Vector3(-.18,-.33,.93)], restPalm=new T.Vector3(0,-1,0)
 const up=new T.Vector3(0,1,0),dir=new T.Vector3(),temp=new T.Vector3(),normal=new T.Vector3(),right=new T.Vector3(),basis=new T.Matrix4(),q=new T.Quaternion(),invBody=new T.Quaternion()
 function makeArm(side:number){
  const upper=new T.Mesh(new T.CapsuleGeometry(.126,.29,5,14),navy),lower=new T.Mesh(new T.CapsuleGeometry(.108,.25,5,14),navy)
  const joint=ellipsoid(body,navy,[0,0,0],[.114,.114,.114],"Elbow");body.add(upper,lower);const hand=createHand(skin,side);hand.node.scale.setScalar(1.32);body.add(hand.node)
  const cuff=new T.Mesh(new T.CylinderGeometry(.090,.090,.044,18),white);body.add(cuff)
  const shoulder=new T.Vector3(),elbow=new T.Vector3(),wrist=new T.Vector3()
  const restUpper=new T.Vector3(side*.31,-.95,.04).normalize(),restLower=new T.Vector3(-side*.46,-.40,.80).normalize()
  return{apply(a:ArmPose,shrug:number,dt:number){
   const blend=clamp(a.present,0,1)
   shoulder.set(side*.432,.82+shrug*.05,0)
   dir.set(a.upperDir.x,a.upperDir.y,a.upperDir.z).normalize().lerp(restUpper,1-blend).normalize()
   elbow.copy(shoulder).addScaledVector(dir,.43);joint.position.copy(elbow)
   upper.position.copy(shoulder).add(elbow).multiplyScalar(.5);upper.quaternion.setFromUnitVectors(up,dir)
   dir.set(a.lowerDir.x,a.lowerDir.y,a.lowerDir.z).normalize().lerp(restLower,1-blend).normalize()
   wrist.copy(elbow).addScaledVector(dir,.39)
   lower.position.copy(elbow).add(wrist).multiplyScalar(.5);lower.quaternion.setFromUnitVectors(up,dir)
   cuff.position.copy(wrist).addScaledVector(dir,-.016);cuff.quaternion.copy(lower.quaternion)
   hand.node.position.copy(wrist)
   temp.set(a.handDir.x,a.handDir.y,a.handDir.z).lerp(restHand[side===1?1:0],1-blend).normalize()
   normal.set(a.palmNormal.x,a.palmNormal.y,a.palmNormal.z).lerp(restPalm,1-blend)
   normal.addScaledVector(temp,-normal.dot(temp)).normalize();right.crossVectors(temp,normal).normalize();normal.crossVectors(right,temp).normalize()
   basis.makeBasis(right,temp,normal);q.setFromRotationMatrix(basis);hand.node.quaternion.slerp(q,1-Math.exp(-dt*25));hand.apply(a)
  }}
 }
 const armL=makeArm(1),armR=makeArm(-1)
 const headQ=new T.Quaternion(),headE=new T.Euler(0,0,0,'YXZ')
 const hits:T.Object3D[]=[];root.traverse(o=>{if(o instanceof T.Mesh)hits.push(o)})
 const result:MingoModel={root,height:2.65,hitMeshes:hits,apply(f:RigFrame,dt:number,t:number){
  body.position.set(clamp(f.body.hipShift,-1,1)*.035+(f.motion?.shiftX??0)*.3,.23+(f.motion?.bounce??0)*.25,0)
  body.rotation.set(f.body.lean.z*.45,f.body.twist*.45+(f.motion?.spin??0),-f.body.lean.x*.45,'YXZ')
  body.scale.y=1+Math.sin(f.breath*Math.PI*2)*.004+(f.motion?.squash??0)*.06
  headE.set(-clamp(f.head.pitch,-.65,.65),clamp(f.head.yaw,-.9,.9)+(f.motion?.spin??0),-clamp(f.head.roll,-.5,.5),'YXZ');headQ.setFromEuler(headE);invBody.copy(body.quaternion).invert();headPivot.quaternion.copy(invBody).multiply(headQ)
  armL.apply(f.armL,f.body.shrugL,dt);armR.apply(f.armR,f.body.shrugR,dt);face.update(f)
  root.updateMatrixWorld(true)
 }}
 result.apply(neutralFrame(),1,0);return result
}
