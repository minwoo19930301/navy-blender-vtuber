import * as T from 'three'
import { createNavy, applyEnvironment } from './model'
import { PRESETS, PRESET_NAMES, applyOverrides, isPreset } from './harness/presets'
import { createReactions } from './reactions'
const q=new URLSearchParams(location.search),canvas=document.getElementById('stage') as HTMLCanvasElement
const r=new T.WebGLRenderer({canvas,antialias:true,alpha:true,preserveDrawingBuffer:true});r.setSize(innerWidth,innerHeight);r.setPixelRatio(1)
const scene=new T.Scene();scene.background=new T.Color('#'+(q.get('bg')??'f1eee9'))
applyEnvironment(r,scene)
const avatar=createNavy();scene.add(avatar.root);await avatar.ready
const reactions=createReactions();await reactions.ready;reactions.fxRoot.scale.setScalar(.8);reactions.fxRoot.position.y=.98;scene.add(reactions.fxRoot)
const cam=new T.PerspectiveCamera(17,innerWidth/innerHeight,.1,100)
function pose(name:string,orbit=0){
 const frame=applyOverrides(PRESETS[isPreset(name)?name:'idle'](),q)
 for(let i=0;i<40;i++)avatar.apply(frame,1/60,i/60)
 if(q.has('reaction')){reactions.trigger(Number(q.get('reaction')),0);for(let i=0;i<90;i++)avatar.apply(reactions.compose(PRESETS.idle(),1/60,i/60),1/60,i/60)} else reactions.compose(PRESETS.idle(),1/60,0)
 const dist=Math.max(3.5,3.3/cam.aspect)/(2*Math.tan(T.MathUtils.degToRad(8.5)))/(Number(q.get('zoom'))||1)
 const ty=Number(q.get('ty')??1.5),el=Number(q.get('elev')??4)*Math.PI/180
 const a=orbit*Math.PI/180;cam.position.set(Math.sin(a)*Math.cos(el)*dist,ty+Math.sin(el)*dist,Math.cos(a)*Math.cos(el)*dist);cam.lookAt(0,ty,0);cam.updateProjectionMatrix()
}
if(q.has('sheet')){
 const names=q.get('sheet')==='1'?PRESET_NAMES:q.get('sheet')!.split(',');const cols=Number(q.get('cols'))||3,rows=Math.ceil(names.length/cols),w=innerWidth/cols,h=innerHeight/rows
 r.setScissorTest(true);cam.aspect=w/h
 names.forEach((name,i)=>{const x=(i%cols)*w,y=innerHeight-(Math.floor(i/cols)+1)*h;pose(name);r.setViewport(x,y,w,h);r.setScissor(x,y,w,h);r.render(scene,cam);const label=document.createElement('div');label.textContent=name;label.style.cssText=`position:absolute;left:${x+24}px;top:${innerHeight-y-h+20}px;font:13px -apple-system;color:#657087;letter-spacing:1px`;document.body.append(label)})
}else{pose(q.get('preset')??'idle',Number(q.get('orbit'))||0);r.render(scene,cam)}
;(window as any).__modelStats={triangles:r.info.render.triangles,drawCalls:r.info.render.calls,geometries:r.info.memory.geometries,textures:r.info.memory.textures}
;(window as any).__navy={avatar,scene,T}
document.title='READY'

// Deterministic preview: the same real model and rig used by the app, without a camera.
;(window as any).__navyRenderAt=(t:number)=>{
 const f=PRESETS.idle(),cycle=t/6*Math.PI*2
 f.head.yaw=Math.sin(cycle)*.30;f.head.roll=Math.sin(cycle)*.045;f.breath=t*.24
 f.blinkL=f.blinkR=Math.pow(Math.max(0,Math.cos(cycle*2)),32)
 f.mouthOpen=.28*Math.max(0,Math.sin(cycle*3));f.mouthSmile=.35
 const wave=PRESETS.wave().armL;wave.present=.5-.5*Math.cos(cycle);f.armL=wave
 f.armL.lowerDir.x+=Math.sin(cycle*5)*.16
 avatar.root.rotation.y=Math.sin(cycle)*.23
 avatar.apply(f,1/24,t);r.render(scene,cam)
}
