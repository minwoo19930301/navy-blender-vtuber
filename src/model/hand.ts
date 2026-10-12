import * as T from 'three'
import { ellipsoid } from './geometry'
import type { ArmPose } from '../contract'
/** Five articulated fingers, 3 joints each; all geometry is allocated once. */
export function createHand(mat:T.Material,side:number){
  const node=new T.Group();node.name=side===1?'Left hand':'Right hand'
  ellipsoid(node,mat,[0,.068,0],[.078,.099,.042],'Palm')
  const chains:T.Group[][]=[]
  for(let i=0;i<5;i++){
    const chain:T.Group[]=[];const base=new T.Group();node.add(base)
    if(i===0){base.position.set(-side*.064,.039,0);base.rotation.z=side*.84}
    else base.position.set(side*(i-2.5)*.039,.135-(i===4?.014:0),0)
    let par=base;const len=i===0?.049:[0,.055,.061,.055,.044][i]
    for(let j=0;j<3;j++){
      const joint=j===0?base:new T.Group()
      if(j>0){joint.position.y=len*(j===1?1:.77);par.add(joint)}
      const l=len*(j===0?1:.77)
      const finger=new T.Mesh(new T.CapsuleGeometry(i===0?.023:.020,Math.max(.005,l-.023),4,10),mat);finger.position.y=l*.49;joint.add(finger)
      chain.push(joint);par=joint
    }
    chains.push(chain)
  }
  return{node,apply(a:ArmPose){for(let i=0;i<5;i++){const curl=Math.min(1,Math.max(0,a.fingers[i]));chains[i].forEach((j,k)=>{j.rotation.x=curl*(k===0?.9:1.2)});if(i>0)chains[i][0].rotation.z=-side*(i-2.5)*a.spread*.17}}}
}
