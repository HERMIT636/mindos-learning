/* Native P6 cards reuse the existing safe prose/feedback helpers. */
window.MindOSTutor=(()=>{
 function comparison(block){const card=node('section','','teaching-block teaching-comparison'),wrap=node('div','','teaching-table-wrap'),table=node('table','','teaching-comparison');card.dataset.blockType='comparison';if(block.title)card.append(node('h3',block.title));const head=node('thead'),tr=node('tr');for(const c of block.columns)tr.append(node('th',c));head.append(tr);const body=node('tbody');for(const row of block.rows){const r=node('tr');for(const c of row)r.append(node('td',c));body.append(r);}table.append(head,body);wrap.append(table);card.append(wrap);return card;}
 function render(target,blocks,{action,onFeedback}={}){
  target.replaceChildren();target.classList.add('teaching-blocks');const auxiliary=node('div');MindOSTeaching.render(auxiliary,[],{action,onFeedback});const note=auxiliary.querySelector('.teaching-strategy-note');if(note)target.append(note);
  for(const b of blocks||[]){
   if(b.type==='diagram'){target.append(MindOSTeaching.TeachingBlock(b,onFeedback));continue;}
   if(['table','comparison'].includes(b.type)){target.append(comparison(b));continue;}
   if(['code','formula'].includes(b.type)){const card=node('section','','teaching-block tutor-code-card');card.dataset.blockType=b.type;card.append(node('h3',b.title||(b.type==='code'?'代码示例':'公式理解')));if(b.type==='code')card.append(node('p','用于理解，不自动执行。','muted'));const pre=node('pre',b.content,b.type==='formula'?'teaching-equation':'');card.append(pre);target.append(card);continue;}
   const mapped=b.type==='steps'?{type:'flow',title:b.title||'一步步理解',data:{steps:b.steps.map(label=>({label,description:''}))}}:{type:b.type==='paragraph'?'text':b.type==='question'?'checkpoint':b.type,title:b.title,content:b.content};target.append(MindOSTeaching.TeachingBlock(mapped,onFeedback));
  }
  const footer=auxiliary.querySelector('.teaching-response-footer');if(footer)target.append(footer);
 }
 return {render};
})();
