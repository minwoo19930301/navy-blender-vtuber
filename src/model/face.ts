import * as T from 'three'
import type { RigFrame } from '../contract'
import { faceZ } from './geometry'
const clamp = (v: number, a=0,b=1)=>Math.min(b,Math.max(a,Number.isFinite(v)?v:0))
export function createFace() {
  const canvas = document.createElement('canvas'); canvas.width=canvas.height=512
  const c = canvas.getContext('2d')!
  const texture = new T.CanvasTexture(canvas);texture.colorSpace=T.SRGBColorSpace;texture.generateMipmaps=false;texture.minFilter=T.LinearFilter
  const g = new T.PlaneGeometry(.92,.87,40,40), p=g.attributes.position
  for(let i=0;i<p.count;i++){const x=p.getX(i),y=p.getY(i)-.035;p.setXYZ(i,x,y,faceZ(x,y)+.004)}
  g.computeVertexNormals()
  const mesh = new T.Mesh(g,new T.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1}))
  mesh.name='Animated eyes, brows and lips'
  const X=(x:number)=>(x/.92+.5)*512, Y=(y:number)=>(.4-y)/.87*512
  function ellipse(x:number,y:number,rx:number,ry:number,color:string){c.fillStyle=color;c.beginPath();c.ellipse(X(x),Y(y),rx/.92*512,ry/.87*512,0,0,Math.PI*2);c.fill()}
  function line(points:number[],color:string,width:number){c.strokeStyle=color;c.lineWidth=width;c.lineCap='round';c.beginPath();c.moveTo(X(points[0]),Y(points[1]));c.quadraticCurveTo(X(points[2]),Y(points[3]),X(points[4]),Y(points[5]));c.stroke()}
  let signature=''
  return {mesh, update(f:RigFrame){
    const values=[f.blinkL,f.blinkR,f.gaze.x,f.gaze.y,f.browL,f.browR,f.mouthOpen,f.mouthSmile,f.fx.blush??0]
    const sig=values.map(v=>Math.round(v*45)).join(',')+JSON.stringify(f.fx)
    if(sig===signature)return;signature=sig;c.clearRect(0,0,512,512)
    for(const side of [-1,1]){
      const x=side*.205,y=-.015
      const blush=c.createRadialGradient(X(side*.30),Y(-.19),1,X(side*.30),Y(-.19),49)
      blush.addColorStop(0,`rgba(222,104,99,${.16+(f.fx.blush??0)*.28})`);blush.addColorStop(1,'rgba(222,104,99,0)');c.fillStyle=blush;c.fillRect(X(side*.30)-50,Y(-.19)-50,100,100)
      const blink=clamp((side===1?f.blinkL:f.blinkR)-.08,0,.78)/.78
      const open=(f.fx.sleepy?0:1-blink)
      if(f.fx.happy||open<.08){line([x-.08,y,x,y-(f.fx.happy?.045:.025),x+.08,y],'#342820',4)}
      else {
        c.save();c.translate(X(x),Y(y));c.scale(1,Math.max(.06,open));c.translate(-X(x),-Y(y))
        ellipse(x,y,.093,.108,'#fbf4e9')
        c.save();c.beginPath();c.ellipse(X(x),Y(y),.093/.92*512,.108/.87*512,0,0,7);c.clip()
        if(f.fx.heart){c.fillStyle='#d85872';c.font='bold 95px sans-serif';c.textAlign='center';c.fillText('♥',X(x),Y(y)+30)}
        else {
          const gx=x+clamp(f.gaze.x,-1,1)*.024, gy=y+clamp(f.gaze.y,-1,1)*.018
          ellipse(gx,gy,.079,.103,'#30251f');ellipse(gx,gy+.003,.069,.091,'#241d1a')
          ellipse(gx-.026,gy+.052,.018,.023,'#fff');ellipse(gx+.033,gy-.044,.007,.009,'#bd9f83')
        }
        c.restore();line([x-.09,y+.03,x-.095,y+.145,x+.078,y+.072],'#342a25',4.5)
        c.restore()
      }
      const brow=side===1?f.browL:f.browR
      const by=.19+brow*.035
      line([x-.09,by-.004,x-.01,by+.04,x+.087,by-.006],'#27262a',14)
    }
    const smile=clamp(f.mouthSmile,-1,1), open=clamp((f.mouthOpen-.025)/.65)
    const my=-.305, w=.111+Math.max(0,smile)*.022
    if(f.fx.kiss){line([-.03,my+.026,.042,my+.005,-.018,my],'#9c5447',3);line([-.018,my,.042,my-.022,-.03,my-.035],'#9c5447',3)}
    else if(open>.055){
      c.fillStyle='#603b36';c.beginPath();c.moveTo(X(-w),Y(my+.018));c.quadraticCurveTo(X(0),Y(my-.012),X(w),Y(my+.018));c.bezierCurveTo(X(w*.85),Y(my-.10*open-.025),X(-w*.85),Y(my-.10*open-.025),X(-w),Y(my+.018));c.fill()
      if(open>.3)ellipse(0,my-.065*open,.049,.016,'#ca8079')
      line([-w*.8,my+.011,0,my-.011,w*.8,my+.011],'#fff7e9',4)
    } else {line([-w,my+.01,0,my-(.057+smile*.035),w,my+.01],'#a0634e',2.6);ellipse(-w,my+.01,.006,.008,'#b77b64');ellipse(w,my+.01,.006,.008,'#b77b64')}
    texture.needsUpdate=true
  }}
}
