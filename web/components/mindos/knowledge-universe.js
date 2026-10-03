/* P7 read-only exploration. Cache and positions are UI state, never learning evidence. */
const MindOSKnowledgeUniverse=(()=>{
 let graph=null,view='galaxy',cid=null,chapter=null,offset=0,selected=null,renderer=null,version=0,searchVersion=0;const cache=new Map(),root=$('knowledge-universe');
 const btn=(text,fn,style='button secondary')=>{const b=node('button',text,style);b.type='button';b.onclick=()=>Promise.resolve(fn()).catch(e=>error(e.message));return b;};
 const positionKey=()=>['ku-layout',view,cid||'',chapter||'',offset].join(':');
 function error(text){$('ku-error').textContent=text||'';}
 function save(){try{localStorage.setItem('mindos-universe-navigation',JSON.stringify({view,cid,chapter,offset,selected}));}catch(_){}history.replaceState(null,'',location.pathname+location.search+'#knowledge-universe');}
 function layout(){try{return JSON.parse(localStorage.getItem(positionKey()));}catch(_){return null;}}
 async function read(path,force=false){const old=cache.get(path);if(!force&&old&&Date.now()-old.at<30000)return old.data;const r=await fetch(path,{cache:'no-store'}),data=await r.json();if(!r.ok)throw Error(data.error||'知识宇宙暂时不可用');cache.set(path,{data,at:Date.now()});while(cache.size>24)cache.delete(cache.keys().next().value);return data;}
 function clearContext(){$('ku-bottom-tutor').disabled=true;state.universeSelection=null;state.courseId=null;state.data=null;state.atomDetail=null;CourseAssistant.sync();}
 function path(){return view==='galaxy'?'/api/universe?offset='+offset:'/api/universe/course/'+encodeURIComponent(cid)+'?'+new URLSearchParams({offset,...(view==='star'?{chapter_id:chapter}:{})});}
 async function show(options={}){
  invalidateNavigation();MindOSUniverse.hideStandalone();MindOSUniverse.navigation('universe');for(const id of ['welcome','course-view','course-management','review-view'])$(id).hidden=true;root.hidden=false;$('breadcrumb').textContent='个人知识档案 / 知识宇宙';
  if(options.restore){try{const saved=JSON.parse(localStorage.getItem('mindos-universe-navigation'));if(saved&&['galaxy','nebula','star'].includes(saved.view)&&Number.isInteger(saved.offset)){({view,cid,chapter,offset,selected}=saved);}}catch(_){}}
  else{view='galaxy';cid=null;chapter=null;offset=0;selected=null;}
  clearContext();await load(true);if(selected)try{await selectStar(selected,false);}catch(_){selected=null;clearContext();}
 }
 async function load(force=false){
  const token=++version;root.setAttribute('aria-busy','true');error('');try{const data=await read(path(),force);if(token!==version||state.page!=='universe')return;graph=data;root.dataset.animation=String(data.policy.enable_animation);render();save();}catch(e){if(token===version){error(e.message);if(view!=='galaxy'){view='galaxy';cid=null;chapter=null;offset=0;selected=null;clearContext();await load(true);}}}finally{if(token===version)root.setAttribute('aria-busy','false');}
 }
 async function enterCourse(id){cid=id;chapter=null;offset=0;view='nebula';selected=null;clearContext();await load();}
 async function enterChapter(n){cid=n.course_id;chapter=n.chapter_id;offset=0;view='star';selected=null;clearContext();await load();}
 function render(){
  $('ku-level').textContent={galaxy:'课程星系',nebula:'章节星云',star:'知识星辰'}[view];$('ku-current').textContent=graph.galaxies.length===1?graph.galaxies[0].name+(view==='star'?' / '+graph.nebulae[0].name:''):'选择一门课程，查看属于你的知识联系。';
  $('ku-back').hidden=view==='galaxy';$('ku-back').onclick=()=>{if(view==='star')enterCourse(cid);else{view='galaxy';cid=null;chapter=null;offset=0;selected=null;clearContext();load();}};
  $('ku-course-select').replaceChildren(node('option','选择课程'));$('ku-course-select').firstChild.value='';const courses=view==='galaxy'?graph.galaxies:(state.courses||[]).map(c=>({course_id:c.id,name:c.title}));for(const c of courses){const o=node('option',c.name);o.value=c.course_id;$('ku-course-select').append(o);}$('ku-course-select').value=cid||'';
  $('ku-view-select').value=view;$('ku-view-select').options[1].disabled=!cid;$('ku-view-select').options[2].disabled=!chapter;
  const nodes=view==='galaxy'?graph.galaxies:view==='nebula'?graph.nebulae:graph.stars;
  renderer?.destroy();renderer=new KnowledgeUniverseRenderer($('ku-canvas'),{select:n=>Promise.resolve(view==='galaxy'?enterCourse(n.course_id):view==='nebula'?enterChapter(n):selectStar(n.id)).catch(e=>error(e.message)),relation:async e=>{try{await selectStar(e.source);renderOrbit(e);}catch(err){error(err.message);}},save:point=>{try{localStorage.setItem(positionKey(),JSON.stringify(point));}catch(_){}}});renderer.set(nodes,graph.edges,view,layout());
  $('ku-empty').hidden=Boolean(nodes.length);$('ku-empty').textContent=view==='galaxy'?'还没有课程。创建并审查课程后，才能看到课程星系。':view==='nebula'?'课程尚无章节结构。':'本章还没有知识原子。可回到课程，审查知识候选或生成课程知识地图。';
  const list=$('ku-list');list.replaceChildren(...nodes.map(n=>btn(n.name+(n.state_label?' · '+n.state_label:'')+(n.unlocked===false?' · 后续章节':''),()=>view==='galaxy'?enterCourse(n.course_id):view==='nebula'?enterChapter(n):selectStar(n.id),'ku-list-item')));
  $('ku-pages').replaceChildren();if(offset)$('ku-pages').append(btn('上一批',async()=>{offset=Math.max(0,offset-(view==='star'?200:60));selected=null;clearContext();await load();}));if(graph.has_more)$('ku-pages').append(btn('下一批',async()=>{offset=graph.next_offset;selected=null;clearContext();await load();}));
  $('ku-cluster-note').textContent=graph.clusters.length?`本章包含 ${graph.clusters[0].star_count} 颗星辰，按已有章节聚合；每批最多显示 200 颗。`:graph.edges_truncated?'为保持清晰，当前批次只显示部分星轨；完整关联可在星辰详情分批查看。':'星辰大小表示前置关系连接的重要性，亮度表示已有证据类别；不显示知识分数或排名。';
  const exploration=$('ku-exploration');exploration.replaceChildren();const current=graph.current_exploration;if(current){exploration.append(node('p','当前学习位置：'+current.course_name+' / '+(current.chapter_name||'尚无章节')+(current.star_name?' / '+current.star_name:''),'muted'),btn('定位当前学习位置',()=>current.star_id?selectStar(current.star_id):current.chapter_id?enterChapter({course_id:current.course_id,chapter_id:current.chapter_id}):enterCourse(current.course_id)),node('small',current.basis,'muted'));}
  const goals=$('ku-goals');goals.replaceChildren();for(const g of graph.goal_context||[])goals.append(node('p',`已有成长目标：${g.goal} · 下一步任务：${g.task}`,'muted'));
  const explored=$('ku-path');explored.replaceChildren();if(graph.explored_path?.length){explored.append(node('strong','已探索轨迹（已有学习记录）'));for(const p of graph.explored_path)explored.append(btn(p.name+' · '+new Date(p.created_at).toLocaleDateString('zh-CN'),()=>selectStar(p.star_id)));}
  if(!selected)$('ku-detail').replaceChildren(node('p','选择星辰，查看已测范围、相关知识与学习记录。点击和探索不会改变掌握状态。','muted'));
 }
 async function selectStar(id,focus=true){
  const token=++version;error('');const data=await read('/api/universe/star/'+encodeURIComponent(id),true);if(token!==version||state.page!=='universe')return;
  const star=data.atom;if(view!=='star'||cid!==star.course_id||chapter!==star.chapter_id||!graph?.stars.some(s=>s.id===id)){view='star';cid=star.course_id;chapter=star.chapter_id;offset=data.window_offset;selected=null;clearContext();const expected=version+1;await load();if(version!==expected||state.page!=='universe')return;}
  selected=id;save();
  state.universeSelection={star,course:data.galaxy,section:data.nebula,detail:data};state.courseId=star.unlocked?star.course_id:null;
  state.data=star.unlocked?{course:{id:star.course_id,title:data.galaxy.name,current_ordinal:data.galaxy.current_ordinal,sections:[{ordinal:star.section_ordinal,title:data.nebula.name}]},section:{ordinal:star.section_ordinal},knowledge:{atoms:[]}}:null;
  state.atomDetail=null;CourseAssistant.sync();if(focus)renderer?.focus(id);else if(renderer){renderer.focused=id;renderer.schedule();}renderDetail(data);
 }
 function renderDetail(data){
  const star=data.atom,detail=$('ku-detail');$('ku-bottom-tutor').disabled=!star.unlocked;detail.replaceChildren(node('p','当前星辰','eyebrow'),node('h2',star.name),node('p',star.description),node('p',`${data.galaxy.name} / ${data.nebula.name}`,'muted'),node('strong',star.state_label),node('p',star.state_basis,'muted'));
  detail.append(node('p','已测维度：'+(star.measured_dimensions.map(k=>({understanding:'理解',application:'应用',transfer:'迁移',retention:'延迟记忆'})[k]).join('、')||'暂无；未测维度不推断掌握'),'muted'));
  for(const risk of star.risk_flags)detail.append(node('p',risk.label+(risk.estimated?'（时间规则提醒，不改历史成绩）':''),'ku-risk'));
  if(data.personal_reference){const p=data.personal_reference;detail.append(node('p',`个人知识档案快照：${p.name} · ${p.label}`,'muted'),node('p',p.boundary,'muted'));if(p.cross_course_conflict)detail.append(node('p','不同课程的历史表现存在差异，建议在本课独立验证。','ku-risk'));}
  if(data.calibration_reference)detail.append(node('p',data.calibration_reference.label,'muted'),node('small',data.calibration_reference.boundary,'muted'));
  const tutor=btn('让 AI 导师解释这个知识点',()=>{CourseAssistant.open();},'button primary');tutor.id='ku-tutor-open';tutor.disabled=!star.unlocked;detail.append(tutor);
  if(!star.unlocked)detail.append(node('p','这是后续章节。可以查看结构，学习与导师问答需你先进入相应小节。','muted'));
  detail.append(btn('回到课程学习空间',()=>openCourse(star.course_id,star.unlocked?star.section_ordinal:undefined,'learn')));
  detail.append(node('h3','附近的知识与星轨'));for(const r of data.relations){const link=btn(`${r.label} · ${r.other_star.name}`,()=>renderOrbit(r),'ku-relation');link.dataset.relationType=r.relation_type;detail.append(link,btn('定位 '+r.other_star.name,()=>selectStar(r.other_star.id),'ku-relation'),node('small',r.boundary,'muted'));}
  if(!data.relations.length)detail.append(node('p','当前图谱还没有关联关系，不由可视化层补造。','muted'));
  if(data.has_more_relations)detail.append(btn('更多关联',async()=>{const r=await read('/api/universe/star/'+star.id+'?relation_offset='+data.next_relation_offset,true);if(selected===star.id&&state.page==='universe')renderDetail(r);}));
  detail.append(node('h3','已有独立答题记录'));for(const h of data.independent_history)detail.append(node('p',`${new Date(h.created_at).toLocaleDateString('zh-CN')} · ${h.label}`,'muted'));if(!data.independent_history.length)detail.append(node('p','暂无独立答题记录。阅读或聊天不会代替检测。','muted'));
  detail.append(node('small',data.boundary,'muted'));
 }
 function renderOrbit(e){const box=node('section','','ku-risk');box.id='ku-orbit-detail';const names=new Map((graph?.stars||[]).map(s=>[s.id,s.name]));if(state.universeSelection)names.set(state.universeSelection.star.id,state.universeSelection.star.name);if(e.other_star)names.set(e.other_star.id,e.other_star.name);box.append(node('h3','为什么连接？'),node('p',`${names.get(e.source)||'来源知识'} → ${names.get(e.target)||'关联知识'} · ${e.label}`),node('p',e.relation_type==='prerequisite'?'现有图谱把起点列为终点的前置知识，建议先理解起点。':'这是现有图谱保存的'+e.label+'，可用于比较或扩展理解。'),node('small',e.boundary+' 可视化层不补造连接原因。','muted'));$('ku-orbit-detail')?.remove();$('ku-detail').prepend(box);}
 async function selectByAtom(course,atom){const id='s-'+btoa(unescape(encodeURIComponent(JSON.stringify([course,atom])))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');await selectStar(id);}
 async function refresh(){cache.clear();if(state.page!=='universe')return;const old=selected;await load(true);if(old)try{await selectStar(old,false);}catch(e){selected=null;clearContext();error(e.message);}}
 function hide(){root.hidden=true;version++;renderer?.destroy();renderer=null;if(location.hash==='#knowledge-universe')history.replaceState(null,'',location.pathname+location.search);}
 $('ku-course-select').onchange=e=>{if(e.target.value)enterCourse(e.target.value);};$('ku-view-select').onchange=async e=>{view=e.target.value;offset=0;selected=null;clearContext();await load();};
 $('ku-refresh').onclick=()=>refresh().catch(e=>error(e.message));$('ku-zoom-in').onclick=()=>renderer?.zoom(1.25);$('ku-zoom-out').onclick=()=>renderer?.zoom(.8);$('ku-fit').onclick=()=>renderer?.fit();
 $('ku-bottom-tutor').onclick=()=>CourseAssistant.open();
 $('ku-profile-back').onclick=()=>MindOSPersonal.profile().catch(e=>error(e.message));
 $('ku-search').oninput=async e=>{const q=e.target.value.trim(),token=++searchVersion,result=$('ku-search-results');result.replaceChildren();if(!q)return;try{const data=await read('/api/universe?search='+encodeURIComponent(q));if(token!==searchVersion||state.page!=='universe')return;for(const r of data.results)result.append(btn(`${({galaxy:'课程',nebula:'章节',star:'知识点'})[r.type]} · ${r.name}`,async()=>{result.replaceChildren();if(r.type==='galaxy')await enterCourse(r.course_id);else if(r.type==='nebula')await enterChapter(r);else{await enterChapter(r);await selectStar(r.star_id);}}));if(!data.results.length)result.append(node('p','没有匹配的已有知识。','muted'));}catch(e){if(token===searchVersion)error(e.message);}};
 let scheduled=false;window.addEventListener('mindos:knowledge-changed',()=>{cache.clear();if(scheduled||state.page!=='universe')return;scheduled=true;setTimeout(()=>{scheduled=false;refresh().catch(e=>error(e.message));},0);});
 return {show,hide,refresh,selectStar,selectByAtom,notifyChange(path,method){if(method!=='GET'&&/^\/api\/(courses(?:\/|$)|quizzes\/submit|sections\/(read|next)|growth\/|learning\/|knowledge\/|atoms\/|graph\/)/.test(path)&&!path.includes('/assistant/'))window.dispatchEvent(new CustomEvent('mindos:knowledge-changed'));},performance(){return {visible_nodes:renderer?.nodes.length||0,draw_milliseconds:renderer?.timings||[],transform:renderer?.transform,cache_entries:cache.size};}};
})();

window.MindOSKnowledgeUniverse=MindOSKnowledgeUniverse;
