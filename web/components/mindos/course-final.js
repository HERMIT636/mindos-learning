/* P1 course ending: backend-owned judgments, existing quiz submission and P0 repair. */
(() => {
 let generation=0;
 const endpoint=(cid,op)=>`/api/courses/${encodeURIComponent(cid)}/final/${op}`;
 const current=(cid,version)=>state.page==='course'&&state.courseId===cid&&(version===undefined||version===generation);
 const names={concept:'概念理解',application:'知识应用',transfer:'陌生情境迁移',retention:'延迟回忆'};
 const percent=v=>v===null||v===undefined?'未测':Math.round(v*100)+'%';
 function button(text,callback,primary=false){const b=node('button',text,'button '+(primary?'primary':'secondary'));b.type='button';b.onclick=()=>action(b,'正在处理…',()=>callback(b));return b;}
 async function reload(cid){const ordinal=state.data?.section.ordinal;const data=await api('/api/course?'+new URLSearchParams({course_id:cid,ordinal}));if(current(cid))renderCourse(data);}
 async function operation(cid,op,body={}){if(op==='start')window.MindOSStudy?.suggestFor('final_assessment',cid,null,20);const r=await api(endpoint(cid,op),body);if(!current(cid))return;if(r.available===false)showNotice(r.note||r.rationale?.join(' ')||'暂时没有可用检测，未测状态会保留。');await reload(cid);}
 function quiz(root,info,cid){
  const q=info.questions[0],form=node('form','','final-question');form.dataset.quizId=info.id;
  form.append(node('p',names[info.item.dimension]+' · '+info.item.reason,'eyebrow'));
  if(q.scenario){const scenario=node('div','','final-scenario');scenario.append(node('h3','试着用在一个新情境里'),node('p',q.scenario));form.append(scenario);}
  const group=node('fieldset');group.append(node('legend',q.prompt));
  for(const [value,text]of Object.entries(q.choices)){const label=node('label','','option'),input=document.createElement('input');input.type='radio';input.name='final-answer';input.value=value;input.required=true;label.append(input,document.createTextNode(text));group.append(label);}
  MindOSLearningLoop.answerInputs(group,0,info,cid);form.append(group);
  const submit=node('button','提交这道题','button primary');submit.type='submit';form.append(submit);
  form.onsubmit=e=>{e.preventDefault();const answer=form.querySelector('[name="final-answer"]:checked')?.value;if(!answer)return;
   action(submit,'正在保存独立答题…',async()=>{const result=await api('/api/quizzes/submit',{course_id:cid,quiz_id:info.id,answers:[answer],...MindOSLearningLoop.answerMetadata(form,1)});if(!current(cid))return;showNotice((result.score?'这道题答对了。':'这道题还有困难。')+'检测后会汇总需要巩固的知识。');await reload(cid);});};root.append(form);
 }
 async function evidence(cid,atom){await openCourse(cid,undefined,'stars');if(current(cid)){await openAtom(atom);if(current(cid)){$('atom-learning-details').open=true;$('atom-learning-details').scrollIntoView({behavior:'smooth',block:'center'});}}}
 function group(root,title,atoms,cid){
  const details=node('details','','final-knowledge-group');details.append(node('summary',`${title} · ${atoms.length} 项`));
  if(!atoms.length)details.append(node('p','当前没有这一类记录。','muted'));
  for(const atom of atoms.slice(0,12)){const line=node('div','','final-knowledge-row');line.append(node('span',atom.title||atom.description||atom.atom_id));if(atom.knowledge_state)line.append(node('small',`理解 ${percent(atom.knowledge_state.understanding)} · 应用 ${percent(atom.knowledge_state.application)} · 迁移 ${percent(atom.knowledge_state.transfer)}`,'muted'));line.append(button('查看答题依据',()=>evidence(cid,atom.atom_id||atom.id)));details.append(line);}if(atoms.length>12)details.append(node('p','还有更多知识点，可在本课程星图中查看。','muted'));root.append(details);
 }
 function reportView(root,report,cid){
  root.replaceChildren();root.append(node('h3','这门课学到了什么？'),node('p',report.mastery_state.label,'final-state'),node('small',`报告第 ${report.version} 版 · ${new Date(report.created_at).toLocaleString('zh-CN')} · 规则 ${report.policy_version}`,'muted'));
  if(report.is_stale)root.append(node('p','之后有新答题或课程变更。这份报告保留当时的判断，可刷新查看最新结果。','muted'));
  const r=report.mastery_state,grid=node('dl','','final-metrics');for(const [key,label]of [['completion_ratio','内容完成'],['mastery_score','综合掌握估计'],['mastery_confidence','判断依据充分程度'],['understanding','理解'],['application','应用'],['transfer','迁移'],['retention','长期记忆']])grid.append(node('dt',label),node('dd',percent(r[key])));root.append(grid);
  if(r.retention_pending)root.append(node('p','长期记忆仍需间隔后独立回忆验证。本次答对不代表长期记住。','muted'));
  const reason=node('ul','','final-reasons');for(const item of r.reasons)reason.append(node('li',item.message));root.append(reason);
  group(root,'已有较稳定表现的知识',r.stable_atoms,cid);group(root,'值得巩固的知识',r.weak_atoms,cid);group(root,'证据还不充分的知识',r.unknown_atoms,cid);group(root,'需要厘清的混淆',r.misconception_atoms,cid);group(root,'建议间隔复习',r.review_due_atoms,cid);
  const recommendations=node('ul');for(const a of report.recommendations)recommendations.append(node('li',a.reason));root.append(recommendations);
  if(report.summary?.summary)root.append(node('p',report.summary.summary,'final-explanation'));
  const controls=node('div','','action-row');controls.append(button('刷新掌握报告',()=>operation(cid,'report')),button(report.summary?.summary?'查看已保存的报告说明':'生成一段通俗说明',async()=>{const next=await api(endpoint(cid,'report'),{summary:true});if(current(cid))reportView(root,next,cid);}));root.append(controls,node('small',r.boundary,'muted'));
  window.MindOSAuthentic?.render(root,report,cid);
 }
 function render(data){
  const root=$('course-final-panel');if(!root)return;root.replaceChildren();const cid=data.course.id,version=++generation,f=data.course_final;
  const last=data.course.current_ordinal===data.course.sections.length;
  root.hidden=!f||(!last&&!f.latest_report);if(root.hidden)return;
  root.append(node('p','课程收尾','eyebrow'),node('h2',f.mastery_state.label),node('p','内容学完和掌握知识是两件事。用少量理解、应用与陌生情境题，看看哪些已经较稳定、哪些还值得巩固。','muted'));
  if(!f.eligible_for_final){root.append(node('p','先逐节学习并生成讲解，最后确认课程内容已学完。这个确认只记录进度。','muted'));if(data.section.ordinal===data.course.sections.length&&data.section.lesson)root.append(button('课程内容已学完',()=>operation(cid,'complete-content'),true));return;}
  if(!f.knowledge_index_available){root.append(node('p','课程内容已完成，章节成绩已保留。先生成知识地图，才能按知识点规划掌握检测。','muted'),button('去课程知识星图',()=>{setCourseMode('map');$('graph-build').scrollIntoView({block:'center'});}));}
  const plan=f.plan,repair=f.repair_plan;
  if(plan?.status==='active'&&!plan.stale){
   const completed=plan.blueprint.filter(q=>q.status==='completed').length,unavailable=plan.blueprint.filter(q=>q.status==='unavailable').length;
   root.append(node('p',`已回答 ${completed} / ${plan.blueprint.length} 道 · 第 ${Math.max(...plan.blueprint.map(q=>q.stage))} 阶段 · 约 ${plan.estimated_minutes} 分钟`,'final-plan-progress'));
   for(const text of plan.rationale)root.append(node('small',text,'muted'));
   if(unavailable)root.append(node('p',`${unavailable} 项暂缺有效题源，保留未测；不按答错计算。`,'muted'));
   if(f.current_quiz)quiz(root,f.current_quiz,cid);else root.append(button('继续下一道检测题',()=>operation(cid,'assessment'),true));
   root.append(node('p','检测期间，AI 导师优先引导思考。查看解释或向导师求助会留下提示记录，这题按练习处理。','muted'));
  }else if(plan?.stale)root.append(node('p','课程目标或知识结构已有变化，旧计划保留为历史。请按新结构重新开始检测。','muted'));
  if(!plan||plan.status!=='active'||plan.stale){
   const row=node('div','','action-row');if(f.knowledge_index_available&&!repair)row.append(button(plan?'重新做掌握检测':'开始课程掌握检测',()=>operation(cid,'start'),true));
   if(plan&&['completed','deferred'].includes(plan.status)&&!repair&&f.mastery_state.status!=='mastered')row.append(button('只补强当前缺口',()=>operation(cid,'remediation-start')));root.append(row);
  }
  if(repair){const box=node('div','','final-repair');box.append(node('h3','只补这几处，再用新题验证'),node('p','短时讲解、诊断和返回位置沿用现有补强流程。看完不会自动判为掌握。','muted'));
   for(const t of repair.targets){const atom=data.knowledge.atoms.find(a=>a.id===t.atom_id),line=node('div','','final-knowledge-row');line.append(node('span',(atom?.title||t.atom_id)+(t.status==='completed'?' · 补强已完成，仍需复测':' · 待补强')));
    if(t.status!=='completed')line.append(button('进入短时补强',async()=>{await api(endpoint(cid,'remediation-target'),{atom_id:t.atom_id,return_context:{section_ordinal:data.section.ordinal,view:'learn',scroll_y:scrollY}});if(current(cid))await reload(cid);$('learning-loop-panel').scrollIntoView({block:'start'});}));box.append(line);}
   if(repair.status==='needs_verification')box.append(button('补强完成，用新题重新验证',()=>operation(cid,'start',{reassessment:true}),true));root.append(box);
  }
  const defer=node('div','','action-row final-defer');defer.append(button('稍后再检测',()=>operation(cid,'defer')),button('先结束课程，保留待巩固知识',()=>operation(cid,'defer',{end_with_gaps:true})));root.append(defer);
  if(f.latest_report){const report=node('section','','final-report');report.append(node('p','正在读取掌握报告…','muted'));root.append(report);api(endpoint(cid,'report')).then(r=>{if(current(cid,version))reportView(report,r,cid);}).catch(e=>{if(current(cid,version))report.replaceChildren(node('p',e.message,'muted'));});}
 }
 window.MindOSCourseFinal={render};
})();
