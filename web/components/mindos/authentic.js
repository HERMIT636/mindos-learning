/* Optional shadow assessments: server-owned rubric, saved text draft, no mastery writes. */
(() => {
 const names={explanation:'开放解释',analysis:'辨析错误',design:'应用设计',open_transfer:'开放迁移'};
 const alive=(cid,root)=>state.page==='course'&&state.courseId===cid&&root.isConnected;
 const path=(cid,op)=>`/api/courses/${encodeURIComponent(cid)}/authentic/${op}`;
 function control(text,fn,primary=false){const b=node('button',text,'button '+(primary?'primary':'secondary'));b.type='button';b.onclick=()=>action(b,'正在处理…',fn);return b;}
 async function render(parent,report,cid,requested=null,existingTaskId=null){
  const root=node('section','','authentic-verification');parent.append(root);state.authenticTask=null;
  root.append(node('h3','进一步验证真实能力'),node('p','可选的 3–10 分钟开放任务。自己解释、分析或设计，比识别选项更进一步。模型辅助评分暂不改变课程掌握结论。','muted'));
  const body=node('div');root.append(body);
  async function show(task){
   if(!alive(cid,root))return;
   if(task?.status==='created')window.MindOSStudy?.suggestFor('authentic_assessment',cid,task.atom_id,15);
   if(typeof MindOSGrowth!=='undefined')await MindOSGrowth.attach(cid,task);
   body.replaceChildren();state.authenticTask=task?.status==='created'?{...task,course_id:cid}:null;
   if(!task||['deferred','unavailable'].includes(task.status)){choose();return;}
   body.append(node('h4',names[task.task_type]),node('p',task.prompt||'正在准备任务，请稍后刷新。','authentic-prompt'));
   if(['generating','evaluating'].includes(task.status)){body.append(node('p','任务正在处理，回答会保留。','muted'),control('刷新任务',refresh));return;}
   const rubric=node('details','','authentic-rubric');rubric.append(node('summary','查看评价标准（不是标准答案）'));
   for(const criterion of task.rubric?.criteria||[])rubric.append(node('p',`${criterion.description} · ${Math.round(criterion.weight*100)}%`));body.append(rubric);
   if(task.status==='submitted'){
    const result=task.result;body.append(node('h4','你的回答'),node('p',result.answer,'authentic-answer'));
    if(result.score===null)body.append(node('p',result.evaluation.note,'muted'));
    else{
     body.append(node('h4',`模型辅助评分：${Math.round(result.score*100)}%`),node('p','评分尚未证明稳定或准确，不是能力认证，也不修改知识状态。','muted'));
     for(const item of result.evaluation.criteria){const card=node('article','','authentic-criterion');card.append(node('strong',(task.rubric.criteria.find(c=>c.id===item.id)?.description||item.id)+` · ${Math.round(item.score*100)}%`),node('blockquote',item.evidence));body.append(card);}
     body.append(node('p',result.valid_for_calibration?result.agreement.message:'本次使用了提示或评分依据不充分，不用于校准。课程掌握状态不变。','muted'));
     if(result.valid_for_calibration&&result.agreement.action==='reassess')body.append(control('主动开始新的独立检测',async()=>{await api(`/api/courses/${cid}/final/start`);await openCourse(cid);}));
    }
    body.append(control('再选择一个开放任务',choose),control('返回掌握报告',()=>{parent.scrollIntoView({block:'start',behavior:'smooth'});}));return;
   }
   const label=node('label','用自己的话回答（可多行）'),input=document.createElement('textarea');input.rows=8;input.maxLength=20000;input.className='authentic-input';input.dataset.taskId=task.id;input.value=task.draft||'';label.append(input);body.append(label);
   const note=node('small','回答会自动保存到本机课程草稿。','muted');body.append(note);let timer,pending=Promise.resolve();
   async function save(){const answer=input.value;pending=api(path(cid,task.id+'/draft'),{answer});await pending;if(alive(cid,root))note.textContent='草稿已保存。';}
   input.oninput=()=>{clearTimeout(timer);note.textContent='正在保存草稿…';timer=setTimeout(()=>save().catch(e=>{note.textContent='草稿尚未保存：'+e.message;}),400);};
   body.append(node('p',task.hint_used?'已向导师求助：本次按练习处理，不用于校准。':'请先独立尝试；向导师求助会标记提示，本次不用于校准。','muted'));
   const controls=node('div','','action-row');controls.append(control('提交开放回答',async()=>{clearTimeout(timer);await pending;await save();const r=await api(path(cid,task.id+'/submit'),{answer:input.value});await show(r.task);},true),control('向导师请求引导',async()=>{await api(path(cid,task.id+'/hint'),{});state.authenticTask={...task,course_id:cid};$('assistant-toggle').click();}),control('暂缓本次开放任务',async()=>{clearTimeout(timer);await pending;await save();const r=await api(path(cid,task.id+'/defer'),{});await show(r.task);}),control('先保存，稍后再做',async()=>{clearTimeout(timer);await pending;await save();note.textContent='草稿已保存，可离开页面，回来继续。';}));body.append(controls);
  }
  function choose(){
   if(!alive(cid,root))return;body.replaceChildren();state.authenticTask=null;
   body.append(node('p','开放式真实能力尚未额外验证。可以跳过，不影响已保存的掌握报告。','muted'));
   const atoms=state.data.knowledge.atoms.filter(a=>a.unlocked&&a.quality_status!=='deprecated'),label=node('label','选择知识点'),select=document.createElement('select');
   for(const atom of atoms){const option=document.createElement('option');option.value=atom.id;option.textContent=atom.title;select.append(option);}if(requested){select.value=requested.atom_id;select.disabled=true;}label.append(select);body.append(label);
   const buttons=node('div','','action-row');for(const [type,name]of Object.entries(names).filter(([type])=>!requested||requested.task_type===type))buttons.append(control(name,async()=>{if(!select.value)return;const r=await api(path(cid,'start'),{...(requested||{}),atom_id:select.value,task_type:type});await show(r.task);}));body.append(buttons);
   body.append(control('查看已有开放任务',refresh),control('查看间隔后验证情况',async()=>{const result=await api(`/api/courses/${cid}/calibration`);if(!alive(cid,root))return;const box=node('div');box.append(node('p',result.boundary,'muted'));for(const [version,windows]of Object.entries(result.windows)){box.append(node('strong',version));for(const [days,sources]of Object.entries(windows))box.append(node('p',`${days} 天：独立检测 ${sources.independent_mcq.samples} 次 · 开放评分 ${sources.llm_rubric.samples} 次。${sources.independent_mcq.classification==='insufficient_future_evidence'?'证据不足，暂不判断偏差。':'已积累可分析的独立结果。'}`));}body.append(box);}));
   const params=new URLSearchParams(location.search);if(params.get('debug_learning')==='1')body.append(control('查看开发校准统计',async()=>{const r=await api('/api/debug/learning/calibration');if(alive(cid,root)){const details=node('pre',JSON.stringify(r,null,2),'calibration-debug');body.append(details);}}));
  }
  async function refresh(){const r=await api(path(cid,existingTaskId||'current'));await show(r.task);}
  try{if(requested){const r=await api(path(cid,'start'),requested);await show(r.task);}else await refresh();}catch(e){if(alive(cid,root))body.append(node('p',e.message,'muted'));}
 }
 window.MindOSAuthentic={render};
})();
