/* Related personal records stay in details; no global graph, no mastery inheritance. */
(() => {
 const make=(text,fn)=>{const b=node('button',text,'button secondary');b.type='button';b.onclick=()=>action(b,'正在处理…',fn);return b;};
 async function profile(){
  await MindOSUniverse.showDashboard('growth');const root=$('growth-profile');root.replaceChildren(node('h2','个人知识档案'),node('p','已确认的知识关联与历史答题形成长期参考。每门课程仍独立保存掌握状态。','muted'));
  const field=node('label','搜索知识名称'),input=document.createElement('input');input.type='search';field.append(input);root.append(field);const domain=document.createElement('select'),status=document.createElement('select');domain.setAttribute('aria-label','知识领域');status.setAttribute('aria-label','知识状态');for(const [v,t] of [['','全部领域'],['machine_learning','机器学习'],['mathematics','数学'],['cognitive_psychology','认知心理学']]){const o=document.createElement('option');o.value=v;o.textContent=t;domain.append(o);}for(const [v,t] of [['','全部状态'],['unknown','待验证'],['weak','已有学习记录'],['moderate','已有基础'],['strong','较稳定'],['conflicted','存在冲突'],['stale','需要复习']]){const o=document.createElement('option');o.value=v;o.textContent=t;status.append(o);}root.append(domain,status);const content=node('div');root.append(content);let request=0;
  async function load(){const version=++request;const r=await api('/api/knowledge/profile?'+new URLSearchParams({search:input.value,domain:domain.value,status:status.value}));if(version!==request||state.page!=='growth')return;content.replaceChildren();if(!r.profiles.length)content.append(node('p','还没有可汇总的知识。先在课程中学习并进行独立答题；不凭阅读判断掌握。','muted'));
   for(const p of r.profiles){const box=node('details','','personal-knowledge-card');box.append(node('summary',`${p.name} · ${p.label}`),node('p',`来源领域：${({machine_learning:'机器学习',cognitive_psychology:'认知心理学',mathematics:'数学'})[p.domain]||'课程专属领域'} · ${p.course_count} 门课程有答题记录`,'muted'));
    if(p.cross_course_conflict)box.append(node('p','不同课程的表现存在差异，建议独立验证当前需求。历史课程分数保留。','muted'));
    for(const s of p.sources){const row=node('div','','personal-source');row.append(node('strong',s.course_title+(s.source_course_deleted?'（已移入回收站）':'')),node('p',`独立答题记录 ${s.independent_evidence} 条 · 已测：${s.dimensions.join('、')||'暂无'} · 最近验证 ${s.last_verified_at?new Date(s.last_verified_at).toLocaleDateString('zh-CN'):'暂无'}`));if(!s.source_course_deleted)row.append(make('查看来源课程',async()=>{await openCourse(s.course_id,undefined,'stars');await openAtom(s.course_atom_id);}));box.append(row);}box.append(node('small',p.boundary,'muted'));content.append(box);}
  }
  domain.onchange=status.onchange=()=>load().catch(e=>showNotice(e.message));input.oninput=()=>load().catch(e=>showNotice(e.message));await load();
  if(new URLSearchParams(location.search).get('debug_learning')==='1')root.append(make('查看长期知识开发记录',async()=>{const r=await api('/api/debug/learning/personal');root.append(node('pre',JSON.stringify(r,null,2),'calibration-debug'));}));
 }
 async function atom(cid,aid){
  let root=$('atom-personal');if(!root){root=node('div');root.id='atom-personal';$('atom-meta').after(root);}root.replaceChildren();
  const alive=()=>state.courseId===cid&&state.atomDetail?.atom.id===aid&&root.isConnected;
  try{
   const [mapping,prior]=await Promise.all([api(`/api/courses/${cid}/knowledge/mappings`),api(`/api/courses/${cid}/knowledge/priors`)]);if(!alive())return;
   const rows=mapping.mappings.filter(m=>m.course_atom_id===aid&&['candidate','verified'].includes(m.status)),p=prior.priors.find(p=>p.course_atom_id===aid);
   const card=node('section','','personal-atom-card');root.append(card);
   card.append(node('h3',p?'你以前学过相关知识':'课程知识关联'),node('p','历史基础只作为教学参考；本课程仍需自己的独立答题依据。','muted'));
   for(const m of rows){const line=node('div','','personal-source');line.append(node('p',m.needs_rescan?'关联依据已变化，请重新检查。':m.status==='verified'?(m.identity_scope==='course_self'?`本课程的独立知识身份：${m.canonical_name}`:`已关联到你的长期知识：${m.canonical_name}`):`可能与已有知识相关：${m.canonical_name}`));if(m.status==='verified'||!['broader','narrower','related','different'].includes(m.relationship))line.append(make(m.status==='verified'?'取消关联':'确认关联',async()=>{await api(`/api/courses/${cid}/knowledge/mappings/${m.id}/${m.status==='verified'?'reject':'verify'}`,{});await atom(cid,aid);}));if(['broader','narrower','related','different'].includes(m.relationship))line.append(node('p','这些概念有联系，但不作为同一知识继承。','muted'));if(m.status==='candidate')line.append(make('不是同一个知识',async()=>{await api(`/api/courses/${cid}/knowledge/mappings/${m.id}/reject`,{});await atom(cid,aid);}));card.append(line);}
   if(!rows.some(m=>m.status==='verified')||rows.some(m=>m.needs_rescan))card.append(make(rows.length?'重新检查关联':'检查相关历史知识',async()=>{await api(`/api/courses/${cid}/knowledge/mappings/scan`,{});await atom(cid,aid);}));
   if(p){card.append(node('p','来自：'+p.source_courses.map(s=>s.title+(s.deleted?'（已删除）':'')).join('、')),node('p',p.scope.target_depth_relation==='higher'?'本课程要求更深入；历史记录只覆盖基础部分。':'历史记录与当前要求相近。','muted'));
    if(p.status==='conflicted')card.append(node('p','当前要求与历史表现有差异，按正常节奏学习即可；不会篡改历史课程状态。'));
    else if(p.status==='verified_in_course')card.append(node('p','✓ 已在本课程独立验证相关基础，讲解可以简短回顾，章节仍需手动推进。'));
    else card.append(node('p',p.status==='stale'?'历史验证已间隔较久，建议快速回忆。':'可以快速确认已有基础，也可以直接正常学习。'));
    const quizRoot=node('div');card.append(quizRoot);
    const show=async q=>{if(!alive())return;renderKnowledgeTests(quizRoot,[q],async()=>{await atom(cid,aid);});};
    card.append(make(p.quiz_id?'查看基础验证':'快速确认已有基础',async()=>{window.MindOSStudy?.suggestFor('cross_course_verify',cid,aid,8);const r=await api(`/api/courses/${cid}/knowledge/priors/${p.id}/verify`,{});if(r.quiz.available===false){showNotice(r.quiz.note);return;}await show(r.quiz);}));
    if(p.quiz)await show(p.quiz);
    card.append(make('正常学习',()=>{$('atom-content').scrollIntoView({block:'center',behavior:'smooth'});}));
   }
  }catch(e){if(alive())root.append(node('p','跨课程知识提示暂未完成：'+e.message,'muted'));}
 }
 document.addEventListener('DOMContentLoaded',()=>{$('personal-open').onclick=()=>profile().catch(e=>showNotice(e.message));});
 window.MindOSPersonal={profile,atom};
})();
