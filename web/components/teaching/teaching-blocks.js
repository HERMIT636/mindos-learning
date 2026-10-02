/* Typed teaching blocks. Model output is always text, never HTML or executable diagrams. */
(() => {
 const titles={question:'先想一个问题',analogy:'换个角度理解',concept:'简单理解',flow:'一步一步看',diagram:'看图理解',comparison:'放在一起比较',formula:'公式与推导',example:'具体例子',checkpoint:'口头自查'};
 const el=(tag,text='',className='')=>{const n=document.createElement(tag);n.textContent=text;n.className=className;return n;};
 const svg=(tag,attrs={})=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));return n;};
 function prose(value){
  const box=el('div','','teaching-prose');const source=String(value||'').replace(/\r\n?/g,'\n')
   .replace(/([。；！？])\s*(?=(?:第[一二三四五六七八九十]+[，、：:]|\d+[.、．）)]))/g,'$1\n')
   .replace(/\s+(?=\d+[.、．）)]\s+(?!\d))/g,'\n');
  let list=null;
  for(const line of source.split(/\n+/).filter(v=>v.trim())){
   const item=line.match(/^\s*(?:(\d+)(?:[.．](?!\s*\d)\s*|[、）)]\s*)|[-•●]\s+)(.+)$/);
   if(item){const type=item[1]?'ol':'ul';if(!list||list.tagName.toLowerCase()!==type){list=el(type,'','teaching-prose-list');box.append(list);}const row=el('li',item[2]);if(item[1])row.value=Number(item[1]);list.append(row);continue;}
   list=null;const sentences=line.match(/.*?[。！？]+[”’」』]?|.+$/g)||[line];let paragraph='';
   for(const sentence of sentences){paragraph+=sentence;if(paragraph.length>=180){box.append(el('p',paragraph));paragraph='';}}
   if(paragraph)box.append(el('p',paragraph));
  }return box;
 }
 function FlowBlock(block){const list=el('ol','','teaching-flow');for(const step of block.data.steps){const item=el('li');item.append(el('strong',step.label));if(step.description)item.append(el('p',step.description));list.append(item);}return list;}
 function DiagramBlock(block){
  const {nodes,edges}=block.data;const box=el('div','','teaching-diagram');const height=Math.ceil(nodes.length/2)*90+40;
  const drawing=svg('svg',{viewBox:`0 0 500 ${height}`,role:'img','aria-label':block.title||'知识关系图'});const positions=new Map();
  nodes.forEach((n,i)=>positions.set(n.id,{x:30+(i%2)*250,y:20+Math.floor(i/2)*90}));
  const markerId='teaching-arrow-'+crypto.randomUUID();const defs=svg('defs');const marker=svg('marker',{id:markerId,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});marker.append(svg('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'currentColor'}));defs.append(marker);drawing.append(defs);
  for(const edge of edges){const a=positions.get(edge.from),b=positions.get(edge.to);if(!a||!b)continue;let start,end;if(a.y!==b.y){start={x:a.x+95,y:a.y+(b.y>a.y?58:0)};end={x:b.x+95,y:b.y+(b.y>a.y?0:58)};}else{start={x:a.x+(b.x>a.x?190:0),y:a.y+29};end={x:b.x+(b.x>a.x?0:190),y:b.y+29};}drawing.append(svg('path',{d:`M ${start.x} ${start.y} L ${end.x} ${end.y}`,fill:'none',stroke:'currentColor','stroke-width':2,'marker-end':`url(#${markerId})`}));}
  for(const n of nodes){const p=positions.get(n.id);drawing.append(svg('rect',{x:p.x,y:p.y,width:190,height:58,rx:9,class:'teaching-diagram-node'}));const title=svg('title');title.textContent=n.label;drawing.append(title);const label=svg('text',{x:p.x+95,y:p.y+22,'text-anchor':'middle'});const chars=Array.from(n.label);for(let row=0;row<Math.min(3,Math.ceil(chars.length/13));row++){const line=svg('tspan',{x:p.x+95,dy:row?15:0});line.textContent=chars.slice(row*13,(row+1)*13).join('')+(row===2&&chars.length>39?'…':'');label.append(line);}drawing.append(label);}
  box.append(drawing);const list=el('ul','','teaching-relations');const names=new Map(nodes.map(n=>[n.id,n.label]));for(const e of edges)list.append(el('li',`${names.get(e.from)} → ${names.get(e.to)}${e.label?'：'+e.label:''}`));box.append(list);return box;
 }
 function ComparisonBlock(block){const wrap=el('div','','teaching-table-wrap');const table=el('table','','teaching-comparison');const head=el('tr');head.append(el('th',block.data.label_header||'比较方面'));for(const c of block.data.columns)head.append(el('th',c));const thead=el('thead');thead.append(head);table.append(thead);const body=el('tbody');for(const r of block.data.rows){const row=el('tr');row.append(el('th',r.label));for(const v of r.values)row.append(el('td',v));body.append(row);}table.append(body);wrap.append(table);return wrap;}
 function FormulaBlock(block){const box=el('div');box.append(el('pre',block.content,'teaching-equation'));const symbols=el('dl');for(const s of block.data?.symbols||[]){symbols.append(el('dt',s.symbol),el('dd',s.meaning));}box.append(symbols);const list=el('ol');for(const s of block.data?.steps||[])list.append(el('li',s));box.append(list);return box;}
 function CheckpointBlock(block,onFeedback){const box=el('div');box.append(prose(block.content),el('small','用自己的话想一想；不会改变掌握记录。','muted'));if(onFeedback){const form=el('form','','teaching-checkpoint-form');const label=el('label','试着回答');const input=el('textarea');input.rows=2;input.maxLength=160;input.required=true;input.setAttribute('aria-label','口头自查回答');input.placeholder='写下你的理解，老师会解释思路。';label.append(input);const button=el('button','帮我看看思路','button secondary');form.append(label,button);form.addEventListener('submit',e=>{e.preventDefault();onFeedback({kind:'rephrase',selfExplanation:input.value,checkQuestion:block.content,question:`这是我的口头自查回答。问题：${block.content.slice(0,180)}；回答：${input.value}。请解释我的思路，不作为独立测试评分。`,button});});box.append(form);}return box;}
 function TeachingBlock(block,onFeedback){const box=el('section','','teaching-block teaching-'+block.type);box.dataset.blockType=block.type;if(block.title||titles[block.type])box.append(el('h3',block.title||titles[block.type]));const special={flow:FlowBlock,diagram:DiagramBlock,comparison:ComparisonBlock,formula:FormulaBlock};if(special[block.type]){if(block.content&&block.type!=='formula')box.append(prose(block.content));box.append(special[block.type](block));}else if(block.type==='checkpoint')box.append(CheckpointBlock(block,onFeedback));else box.append(prose(block.content));return box;}
 function fromText(value){return String(value||'').split(/\n\s*\n/).filter(v=>v.trim()).map(v=>({type:'text',content:v.replace(/^#{1,6}\s*/gm,'').replace(/\*\*([^*]+)\*\*/g,'$1').replace(/^```[^\n]*\n?|```$/gm,'').trim()})).filter(b=>b.content);}
 function render(target,blocks,{onFeedback=null,action=null}={}){
  target.replaceChildren();target.classList.add('teaching-blocks');if(action?.presentation_reason||action?.reason){const details=el('details','','teaching-strategy-note');details.append(el('summary','本次讲法'),el('p',action.presentation_reason||action.reason));target.append(details);}
  for(const block of blocks||[])target.append(TeachingBlock(block,onFeedback));
  if(onFeedback){const footer=el('div','','teaching-response-footer');footer.append(el('span','接着理解','teaching-feedback-label'));const bar=el('div','','teaching-feedback');bar.setAttribute('aria-label','调整这次讲解');for(const [label,kind,question] of [['换个说法','rephrase','我还没理解，请换一种说法解释。'],['看个例子','example','请用一个具体例子解释当前知识。'],['看图理解','visual','请用图示解释当前知识。'],['公式没看懂','formula_confusing','公式我没看懂，请先用直觉和例子解释。']]){const button=el('button',label,'button secondary');button.type='button';button.addEventListener('click',()=>onFeedback({kind,question,button}));bar.append(button);}footer.append(bar);target.append(footer);}
 }
 window.MindOSTeaching={render,fromText,TeachingBlock,FlowBlock,DiagramBlock,CheckpointBlock,prose};
})();
