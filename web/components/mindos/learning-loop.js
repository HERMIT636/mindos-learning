/* Small course-scoped additions. Decisions are supplied by the backend. */
(() => {
 let memory=null,displayQuiz=null,generation=0;
 const labels={unknown:'未测',introduced:'已接触',learning:'学习中',unstable:'需要练习',mastered:'多次检测较稳定',review_due:'待复习',misconception:'需要厘清混淆',prerequisite_gap:'前置知识待补强'};
 const reason={PREREQUISITE_GAP:'前置知识的检测结果较弱，建议做短时补强。',MISCONCEPTION_DETECTED:'多次答题显示可能存在同一种混淆，建议定点检查。',REPEATED_FAILURE:'最近多次检测仍有困难，可以换一个例子做短时练习。',REPAIR_DEPTH_LIMIT:'前置知识较多，先回看基础小节或向导师提问，再做短检测。',LOW_CONFIDENCE:'独立证据还不充分，建议用新题检查理解。',REVIEW_DUE:'到了回忆检测时间。',FORGETTING_RISK:'建议检查是否仍能独立回忆。'};
 const endpoint=(cid,op)=>`/api/courses/${encodeURIComponent(cid)}/loop/${op}`;
 function button(text,callback){const b=node('button',text,'button secondary');b.type='button';b.onclick=()=>action(b,'正在处理…',()=>callback(b));return b;}
 function current(cid){return state.page==='course'&&state.courseId===cid;}
 const context=()=>{const atom=state.courseMode==='map'?state.atomDetail?.atom:null;return {section_ordinal:atom?.section||state.data.section.ordinal,knowledge_atom_id:atom?.id||null,atom_mode:state.atomMode,view:state.courseMode==='map'?'stars':'learn',scroll_y:scrollY};};
 async function reload(cid){const ordinal=state.data?.section.ordinal;const data=await api('/api/course?'+new URLSearchParams({course_id:cid,ordinal}));if(current(cid))renderCourse(data);}
 async function restore(cid,c){await openCourse(cid,c.section_ordinal,c.view);if(!current(cid))return;if(c.view==='stars'&&c.knowledge_atom_id){state.atomMode=c.atom_mode||'quick';await openAtom(c.knowledge_atom_id);}if(current(cid))scrollTo(0,c.scroll_y||0);}
 function answerInputs(group,index,quiz,cid){
  if(quiz.hint_used?.[index])group.append(node('p','已使用讲解帮助，这题按有提示练习记录。','muted'));
  const label=node('label','你对这个答案有多确定？','answer-confidence');const select=node('select');select.dataset.confidenceIndex=index;
  for(const [value,text] of [['','暂不选择'],['low','不确定'],['medium','比较确定'],['high','非常确定']]){const o=node('option',text);o.value=value;select.append(o);}label.append(select);group.append(label);
  const hint=button('查看解释（计作有提示练习）',async()=>{const result=await api(endpoint(cid,'hint'),{quiz_id:quiz.id,question_index:index});if(current(cid))hint.replaceWith(node('p',result.hint+' '+result.note,'muted'));});group.append(hint);
 }
 function answerMetadata(form,count){return {confidence:Array.from({length:count},(_,i)=>form.querySelector(`[data-confidence-index="${i}"]`)?.value||null)};}
 async function check(cid,atom,purpose,session=null){
  window.MindOSStudy?.suggestFor(purpose==='review'?'review':purpose==='diagnostic'?'cross_course_verify':'micro_practice',cid,atom,purpose==='review'?5:8);
  const quiz=await api(endpoint(cid,'assessment'),{atom_id:atom,purpose,session_id:session?.id||''});if(!current(cid))return;
  if(quiz.available===false){showNotice(quiz.note);return;}
  memory=session?{cid,kind:purpose==='remediation'?'repair':'returning',id:session.id}:null;displayQuiz={...quiz,cid,atom_id:atom};render(state.data);
 }
 async function finish(cid){
  const task=memory;
  if(task&&task.cid===cid){const result=await api(endpoint(cid,task.kind)+'?id='+encodeURIComponent(task.id));if(!current(cid))return;
   if(result.status==='completed'){const c=result.return_context;memory=null;displayQuiz=null;await restore(cid,c);
    if(current(cid)&&result.decision?.action!=='continue'&&result.decision?.action)showNotice('回忆检测已完成，有些知识建议再复习。可在学习建议中查看。');return;}
   if(result.status==='needs_review')showNotice('这次短检测还有困难，先回看解释或向导师提问；原课程位置已保留。');
  }
  displayQuiz=null;await reload(cid);
 }
 function quizView(root,quiz,cid){
  const box=node('div','','loop-assessment');box.append(node('h3','短检测 · 先独立回忆'),node('p','答题信心用于辨别不确定与可能的混淆，不等于系统对能力的确定程度。','muted'));if(quiz.note)box.append(node('p',quiz.note,'muted'));
  const form=node('form');quiz.questions.forEach((q,i)=>{const group=node('fieldset');group.append(node('legend',`${i+1}. ${q.prompt}`));for(const [value,text]of Object.entries(q.choices)){const label=node('label','','option'),input=document.createElement('input');input.type='radio';input.name='loop-answer-'+i;input.value=value;input.required=true;label.append(input,document.createTextNode(text));group.append(label);}answerInputs(group,i,quiz,cid);form.append(group);});
  const submit=node('button','提交短检测','button primary');submit.type='submit';form.append(submit);form.onsubmit=e=>{e.preventDefault();const answers=quiz.questions.map((_,i)=>form.querySelector(`[name="loop-answer-${i}"]:checked`)?.value);if(answers.some(a=>!a))return;action(submit,'正在保存…',async()=>{await api('/api/quizzes/submit',{course_id:cid,quiz_id:quiz.id,answers,...answerMetadata(form,answers.length)});if(current(cid))await finish(cid);});};box.append(form);root.append(box);
 }
 function render(data){
  const root=$('learning-loop-panel');if(!root)return;root.replaceChildren();const cid=data.course.id,loop=data.knowledge.learning_loop;
  root.hidden=!loop;if(!loop)return;
  if(data.course_final?.plan?.status==='active'&&!data.course_final.plan.stale&&!loop.active_repair&&!loop.returning_session){root.hidden=true;return;}const version=++generation;root.append(node('h2','下一步学习建议'));
  const session=loop.active_repair,returning=loop.returning_session;
  if(!session&&!returning)memory=null;
  if(memory&&memory.cid!==cid)memory=null;if(displayQuiz?.cid!==cid||displayQuiz?.session_id&&!loop.pending_assessments.some(q=>q.id===displayQuiz.id))displayQuiz=null;
  if(session){root.append(node('p','短时补强：先做诊断，必要时看一个解释与例子，再检测。完成后返回原位置。','muted'));
   const target=data.knowledge.atoms.find(a=>a.id===session.target_atom_id);root.append(node('h3',target?.title||'前置知识'));
   memory={cid,kind:'repair',id:session.id};
   if(session.status==='diagnostic')root.append(button('开始短诊断',()=>check(cid,session.target_atom_id,'remediation',session)));
   else{if(session.content?.blocks){const content=node('div');MindOSTeaching.render(content,session.content.blocks);root.append(content);root.append(button('做补强检测',()=>check(cid,session.target_atom_id,'remediation',session)));}
    else root.append(button('看短讲解与例子',async()=>{await api(endpoint(cid,'repair-content'),{session_id:session.id});if(current(cid))await reload(cid);}));}
   root.append(button('先返回原小节',async()=>{const s=await api(endpoint(cid,'defer'),{kind:'repair',session_id:session.id});if(current(cid)){memory=null;displayQuiz=null;await restore(cid,s.return_context);}}));
  }else if(returning){root.append(node('p','离开课程有一段时间了。先做几个短回忆检测，再决定继续还是回顾；不会自动进入下一节。','muted'));
   for(const atom of returning.targets.filter(a=>!returning.completed_targets?.includes(a))){const a=data.knowledge.atoms.find(v=>v.id===atom);root.append(button('回忆检测：'+(a?.title||atom),()=>check(cid,atom,'returning',returning)));}
   root.append(button('先回看当前小节',async()=>{await api(endpoint(cid,'defer'),{kind:'returning',session_id:returning.id});if(current(cid)){memory=null;displayQuiz=null;await reload(cid);}}));
  }else{
   const d=loop.decisions.find(d=>d.action==='remediate');if(d){root.append(node('p',reason[d.reason_code]||'建议短时补强当前困难。'));if(d.metadata.repair_available===false)root.append(node('p',d.metadata.repair_note,'muted'));else root.append(button('开始约 5 分钟补强',async()=>{const s=await api(endpoint(cid,'repair-start'),{origin_atom_id:d.metadata.origin_atom_id,return_context:context()});if(current(cid)){memory={cid,kind:'repair',id:s.id};await reload(cid);}}));}
   if(loop.review_queue.length){root.append(node('h3','需要复习'));for(const r of loop.review_queue)root.append(button(r.title+' · 回忆检测',()=>check(cid,r.atom_id,'review')));}
   const reassess=loop.decisions.find(d=>d.action==='reassess');if(!d&&!loop.review_queue.length&&reassess){root.append(node('p',reason[reassess.reason_code]||'再用一道新题检查理解。','muted'));root.append(button('做短检测',()=>check(cid,reassess.target_atom_id,'diagnostic')));}
   if(!d&&!loop.review_queue.length&&!reassess)root.append(node('p','继续当前小节；只有你明确选择，才会进入下一节。','muted'));
   for(const m of loop.misconceptions.slice(0,3))root.append(node('p',`${m.status==='confirmed'?'重复答题支持的混淆':'可能的混淆'}：${m.description}`,'loop-misconception'));
  }
  if(!displayQuiz){const pending=loop.pending_assessments.find(q=>session?q.session_id===session.id:returning?q.session_id===returning.id:!q.session_id);if(pending)displayQuiz={...pending,cid};}
  if(displayQuiz){const pending=displayQuiz;if(pending.session_id&&!memory)memory={cid,kind:pending.assessment_kind==='remediation'?'repair':'returning',id:pending.session_id};quizView(root,pending,cid);}
  if(loop.debug_enabled){root.append(button('开发：查看学习证据',async()=>{const value=await api(endpoint(cid,'debug'));if(current(cid)&&version===generation){const pre=node('pre',JSON.stringify(value,null,2),'loop-debug');root.append(pre);}}));}
 }
 async function stateDetail(cid,atom){const root=$('atom-learning-state');if(!root)return;root.replaceChildren(node('p','正在读取检测依据…','muted'));
  try{const r=await api(endpoint(cid,'state')+'?atom_id='+encodeURIComponent(atom));if(!current(cid)||state.atomDetail?.atom.id!==atom)return;root.replaceChildren();root.append(node('p',labels[r.knowledge_state.state]||'未测'));const grid=node('dl','','knowledge-state-grid');for(const [key,label]of [['understanding','理解'],['application','应用'],['transfer','迁移'],['retention','延迟记忆']]){const v=r.knowledge_state[key];grid.append(node('dt',label),node('dd',v===null?'未测':Math.round(v*100)+'%（规则估计）'));}root.append(grid);for(const text of r.reasons)root.append(node('p',text,'muted'));for(const m of r.misconceptions)root.append(node('p','可能混淆：'+m.description,'loop-misconception'));const list=node('ul');for(const e of r.evidence.slice(0,6))list.append(node('li',`${e.created_at.slice(0,10)} · ${e.result==='correct'?'答对':e.result==='wrong'?'答错':'学习信号'}${e.hint_used?' · 使用过解释':''}${e.metadata.question?' · '+e.metadata.question:''}`));root.append(list,node('small',r.boundary,'muted'));
  }catch(error){if(current(cid)&&state.atomDetail?.atom.id===atom)root.replaceChildren(node('p',error.message,'muted'));}}
 window.MindOSLearningLoop={render,stateDetail,answerInputs,answerMetadata,check,labels};
})();
