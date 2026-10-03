/* Bounded 2D canvas with accessible DOM targets; no physics or particle simulation. */
window.KnowledgeUniverseRenderer=class{
 constructor(host,{select,relation,save}){
  this.listeners=[];this.listen=(type,fn,options)=>{host.addEventListener(type,fn,options);this.listeners.push(()=>host.removeEventListener(type,fn,options));};this.host=host;this.select=select;this.relation=relation;this.save=save;this.nodes=[];this.edges=[];this.points=new Map();this.transform={x:0,y:0,scale:1};this.frame=null;this.pointers=new Map();this.timings=[];this.moved=false;
  this.canvas=document.createElement('canvas');this.canvas.setAttribute('aria-hidden','true');this.targets=node('div','','ku-targets');host.replaceChildren(this.canvas,this.targets);host.tabIndex=0;host.setAttribute('aria-label','二维知识宇宙，方向键移动，加减键缩放，Home居中');
  this.resize=new ResizeObserver(()=>this.schedule());this.resize.observe(host);
  this.listen('wheel',e=>{e.preventDefault();const r=host.getBoundingClientRect();this.zoom(Math.exp(-e.deltaY*.001),e.clientX-r.x,e.clientY-r.y);},{passive:false});
  this.listen('pointerdown',e=>{if(e.button!==0)return;this.moved=false;if(e.target.closest('button')&&e.pointerType!=='touch')return;this.pointers.set(e.pointerId,{x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY});if(this.pointers.size>1)this.moved=true;(e.target.closest('button')||host).setPointerCapture(e.pointerId);});
  this.listen('pointermove',e=>{if(!this.pointers.has(e.pointerId))return;const old=this.pointers.get(e.pointerId);if(Math.hypot(e.clientX-old.startX,e.clientY-old.startY)>3)this.moved=true;if(this.pointers.size===2){const other=[...this.pointers.entries()].find(([id])=>id!==e.pointerId)[1];const before=Math.hypot(old.x-other.x,old.y-other.y),after=Math.hypot(e.clientX-other.x,e.clientY-other.y);if(before>4){const r=host.getBoundingClientRect();this.zoom(after/before,(e.clientX+other.x)/2-r.x,(e.clientY+other.y)/2-r.y);}}else{this.transform.x+=e.clientX-old.x;this.transform.y+=e.clientY-old.y;this.schedule();}this.pointers.set(e.pointerId,{...old,x:e.clientX,y:e.clientY});});
  for(const kind of ['pointerup','pointercancel'])this.listen(kind,e=>{this.pointers.delete(e.pointerId);this.remember();});
  this.listen('click',e=>{if(this.moved||e.target.closest('button'))return;const r=host.getBoundingClientRect(),hit=this.hitEdge(e.clientX-r.x,e.clientY-r.y);if(hit)this.relation(hit);});
  this.listen('keydown',e=>{if(e.target!==host)return;const k=e.key;if(['+','=','-','Home','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(k))e.preventDefault();if(k==='Home')this.fit();else if(['+','=','-'].includes(k))this.zoom(k==='-'?.8:1.25);else if(k.startsWith('Arrow')){this.transform.x+=k==='ArrowLeft'?40:k==='ArrowRight'?-40:0;this.transform.y+=k==='ArrowUp'?40:k==='ArrowDown'?-40:0;this.schedule();this.remember();}});
 }
 set(nodes,edges,view,saved){
  this.nodes=nodes;this.edges=edges;this.view=view;this.points.clear();this.targets.replaceChildren();
  const cols=Math.max(2,Math.ceil(Math.sqrt(Math.max(1,nodes.length)*1.4))),gap=view==='star'?165:220;
  this.world={width:cols*gap+100,height:Math.ceil(nodes.length/cols)*(view==='star'?130:175)+100};
  nodes.forEach((n,i)=>{const p={x:85+(i%cols)*gap+(Math.floor(i/cols)%2)*20,y:85+Math.floor(i/cols)*(view==='star'?130:175)};this.points.set(n.id,p);
   const b=node('button','','ku-target');b.type='button';b.dataset.nodeId=n.id;b.setAttribute('aria-label',n.name+(n.state_label?'，'+n.state_label:'')+(n.unlocked===false?'，后续章节':''));b.title=b.getAttribute('aria-label');b.append(node('span',n.name,'ku-node-label'));b.onclick=e=>{if(!this.moved||e.detail===0)this.select(n);};b.onfocus=()=>{this.focused=n.id;const x=this.transform.x+p.x*this.transform.scale,y=this.transform.y+p.y*this.transform.scale;if(x<25||x>this.host.clientWidth-25||y<25||y>this.host.clientHeight-25)this.focus(n.id);else this.schedule();};this.targets.append(b);});
  if(saved&&[saved.x,saved.y,saved.scale].every(Number.isFinite)&&saved.scale>=.2&&saved.scale<=3)this.transform={...saved};else this.fit(false);
  this.schedule();
 }
 hitEdge(x,y){const t=this.transform;x=(x-t.x)/t.scale;y=(y-t.y)/t.scale;for(const e of this.edges){const a=this.points.get(e.source),b=this.points.get(e.target);if(!a||!b)continue;const c={x:(a.x+b.x)/2,y:(a.y+b.y)/2-20};for(let i=1;i<12;i++){const k=i/12,px=(1-k)**2*a.x+2*(1-k)*k*c.x+k*k*b.x,py=(1-k)**2*a.y+2*(1-k)*k*c.y+k*k*b.y;if(Math.hypot(x-px,y-py)<8/t.scale)return e;}}return null;}
 fit(persist=true){const r=this.host.getBoundingClientRect(),scale=Math.max(.2,Math.min(1.15,(r.width-45)/this.world.width,(r.height-45)/this.world.height));this.transform={scale,x:(r.width-this.world.width*scale)/2+30,y:(r.height-this.world.height*scale)/2+30};this.schedule();if(persist)this.remember();}
 zoom(factor,x=this.host.clientWidth/2,y=this.host.clientHeight/2){const t=this.transform,scale=Math.max(.2,Math.min(3,t.scale*factor)),ratio=scale/t.scale;t.x=x-(x-t.x)*ratio;t.y=y-(y-t.y)*ratio;t.scale=scale;this.schedule();this.remember();}
 focus(id){const p=this.points.get(id);if(!p)return;this.focused=id;this.transform.scale=Math.max(.85,this.transform.scale);this.transform.x=this.host.clientWidth/2-p.x*this.transform.scale;this.transform.y=this.host.clientHeight/2-p.y*this.transform.scale;this.schedule();this.remember();}
 remember(){this.save({...this.transform});}
 schedule(){if(this.frame)return;this.frame=requestAnimationFrame(()=>{this.frame=null;this.draw();});}
 draw(){
  const started=performance.now(),w=this.host.clientWidth,h=this.host.clientHeight;if(!w||!h)return;const dpr=Math.min(devicePixelRatio||1,2);if(this.canvas.width!==Math.round(w*dpr)||this.canvas.height!==Math.round(h*dpr)){this.canvas.width=Math.round(w*dpr);this.canvas.height=Math.round(h*dpr);}const ctx=this.canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  // Sparse fixed background marks are decorative, never knowledge nodes.
  ctx.fillStyle='#8da4c4';ctx.globalAlpha=.14;for(let i=0;i<26;i++){ctx.beginPath();ctx.arc((i*137+37)%w,(i*83+19)%h,1,0,Math.PI*2);ctx.fill();}ctx.globalAlpha=1;
  const t=this.transform;ctx.translate(t.x,t.y);ctx.scale(t.scale,t.scale);
  for(const e of this.edges){const a=this.points.get(e.source),b=this.points.get(e.target);if(!a||!b)continue;ctx.strokeStyle='#9cacf0';ctx.globalAlpha=e.relation_type==='prerequisite'?.42:.24;ctx.lineWidth=1.1/t.scale;ctx.setLineDash(e.relation_type==='prerequisite'?[]:[4/t.scale,5/t.scale]);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.quadraticCurveTo((a.x+b.x)/2,(a.y+b.y)/2-20,b.x,b.y);ctx.stroke();if(e.relation_type==='prerequisite'){const angle=Math.atan2(b.y-a.y,b.x-a.x),x=b.x-Math.cos(angle)*22,y=b.y-Math.sin(angle)*22;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x-Math.cos(angle-.4)*8,y-Math.sin(angle-.4)*8);ctx.moveTo(x,y);ctx.lineTo(x-Math.cos(angle+.4)*8,y-Math.sin(angle+.4)*8);ctx.stroke();}}
  ctx.setLineDash([]);
  this.nodes.forEach((n,i)=>{const p=this.points.get(n.id),size=this.view==='star'?7+(n.importance||1)*2:this.view==='galaxy'?23:16,alpha=n.brightness??.82;
   const gradient=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,size*3.7);gradient.addColorStop(0,`rgba(156,175,255,${alpha*.38})`);gradient.addColorStop(1,'rgba(156,175,255,0)');ctx.fillStyle=gradient;ctx.globalAlpha=n.unlocked===false?.35:1;ctx.beginPath();ctx.arc(p.x,p.y,size*3.7,0,Math.PI*2);ctx.fill();ctx.globalAlpha=(n.unlocked===false?.35:1)*alpha;ctx.fillStyle='#c1ceff';ctx.beginPath();ctx.arc(p.x,p.y,size,0,Math.PI*2);ctx.fill();ctx.globalAlpha=.35;ctx.strokeStyle='#b2c0ff';ctx.lineWidth=1/t.scale;ctx.beginPath();ctx.arc(p.x,p.y,size+8,0,Math.PI*2);ctx.stroke();
   if(n.risk_flags?.length){ctx.setLineDash([3/t.scale,5/t.scale]);ctx.beginPath();ctx.arc(p.x,p.y,size+17,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);}
   if(this.focused===n.id){ctx.globalAlpha=.85;ctx.lineWidth=2/t.scale;ctx.beginPath();ctx.arc(p.x,p.y,size+24,0,Math.PI*2);ctx.stroke();}
   const b=this.targets.children[i],bw=Math.max(44,130*t.scale),bh=Math.max(44,75*t.scale);b.style.width=bw+'px';b.style.height=bh+'px';b.style.transform=`translate(${t.x+p.x*t.scale-bw/2}px,${t.y+p.y*t.scale-24}px)`;b.style.opacity=n.unlocked===false?'.55':'1';b.dataset.state=n.mastery_state||'';b.dataset.selected=String(this.focused===n.id);b.firstChild.style.top=(24+12*t.scale)+'px';b.firstChild.style.fontSize=Math.max(9,12*t.scale)+'px';
  });ctx.globalAlpha=1;this.timings.push(performance.now()-started);if(this.timings.length>120)this.timings.shift();
 }
 destroy(){if(this.frame)cancelAnimationFrame(this.frame);this.resize.disconnect();this.listeners.forEach(remove=>remove());this.listeners=[];this.pointers.clear();}
};
