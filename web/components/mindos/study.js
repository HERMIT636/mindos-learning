/* Voluntary local timing. No focus, input, OS activity or attention tracking. */
(() => {
 let session=null,suggestion=null,bar=null,entry=null,pending=false,serial=0,tick=0,defaults={course_learning:25};
 const hidden=()=>localStorage.getItem('mindos-study-hide-time')==='1';
 const statuses={active:'正在学习',paused:'已暂停',interrupted:'记录中断',completed:'本次已结束',abandoned:'本次已停止'};
 const reasons={finished:'本次内容完成',time_box_end:'按本次时间安排结束',user_stopped:'主动停止',blocked:'暂时卡住',too_difficult:'当前需要更多帮助',interrupted:'中途退出',route_changed:'更换学习任务'};
 const types={course_learning:'课程学习',review:'复习',cross_course_verify:'基础验证',final_assessment:'课程检测',authentic_assessment:'开放实践',micro_practice:'小练习',goal_task:'目标任务',free_study:'自主学习'};
 async function call(path,data,method){const response=await fetch(path,{method:method||(data===undefined?'GET':'POST'),headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const r=await response.json();if(!response.ok)throw Error(r.error||'学习记录更新失败');return r;}
 function btn(text,fn,primary=false){const b=node('button',text,'button '+(primary?'primary':'secondary'));b.type='button';b.onclick=async()=>{if(pending)return;pending=true;b.disabled=true;try{await fn();}catch(e){showNotice(e.message);}finally{pending=false;if(b.isConnected)b.disabled=false;}};return b;}
 function elapsed(){return Math.max(0,(session?.active_seconds||0)+(session?.status==='active'?Math.max(0,(Date.now()-Date.parse(session.server_time))/1000):0));}
 function time(seconds){const m=Math.floor(seconds/60);return `${m}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;}
 function dialog(title){const d=node('dialog','','study-dialog');d.setAttribute('aria-label',title);const top=node('div','','action-row');top.append(node('h2',title),btn('关闭',()=>d.close()));d.append(top);document.body.append(d);d.addEventListener('close',()=>d.remove());d.showModal();return d;}
 async function refresh(){const token=++serial;const r=await call('/api/study/sessions/current');if(token!==serial)return;session=r.session;defaults=r.activity_defaults||defaults;render();}
 async function change(op,payload={}){if(!session)return;const id=session.id;const r=await call(`/api/study/sessions/${id}/${op}`,payload);++serial;session=r.session?.status==='completed'||r.session?.status==='abandoned'?null:r.session;render();return r;}
 function render(){if(!bar)return;bar.replaceChildren();bar.hidden=!session;
  if(session){const copy=node('div','','study-session-copy');copy.append(node('strong',session.title),node('small',statuses[session.status],'muted'));bar.append(copy);
   const timer=node('span',hidden()?'计时已隐藏':time(elapsed()),'study-elapsed');timer.id='study-elapsed';bar.append(timer);
   if(session.status==='interrupted')bar.append(node('p','检测到未正常结束的学习记录，离线时间未计入。','study-interrupted'));
   bar.append(btn(session.status==='active'?'暂停':'继续',()=>change(session.status==='active'?'pause':'resume')),btn('结束本次学习',()=>endDialog(),true),btn('修改时间',()=>endDialog(true)),btn(hidden()?'显示时间':'隐藏时间',()=>{localStorage.setItem('mindos-study-hide-time',hidden()?'0':'1');render();}));
   if(session.course_id)bar.append(btn('回到本次课程',()=>openCourse(session.course_id)));
   if(session.status==='active')bar.append(node('small','未监测专注；离开学习时可主动暂停。','muted'));
  }
  renderEntry();
 }
 function activeContext(){if(['create','growth-roadmap'].includes(state.page)&&suggestion?.activity_type==='goal_task')return suggestion;if(state.page!=='course'||!state.data||!state.courseId)return null;
  if(suggestion?.course_id===state.courseId)return suggestion;
  return {course_id:state.courseId,activity_type:'course_learning',title:state.data.course.title,base_minutes:defaults.course_learning,predicted_minutes:defaults.course_learning,source:'course',estimate_source:'初始规则估时'};
 }
 function renderEntry(){if(!entry)return;const context=activeContext();entry.replaceChildren();entry.hidden=!context;
  if(!context)return;
  entry.append(node('strong',`本次${types[context.activity_type]||'学习'} · 约 ${context.predicted_minutes||context.base_minutes} 分钟`),node('small',`${context.estimate_source||'完整记录不足，暂用初始规则估时'} · 初始参考 ${context.base_minutes||25} 分钟`,'muted'));
  if(!session)entry.append(btn('开始本次学习',()=>start(context),true));else entry.append(node('p','已有学习记录；可在上方继续或结束。','muted'));
  entry.append(btn('查看学习记录',history));
 }
 async function start(context){const fields={};for(const key of ['growth_task_id','course_id','atom_id','activity_type','source'])if(context[key])fields[key]=context[key];fields.planned_minutes=context.base_minutes??25;
  const r=await call('/api/study/sessions/start',fields);++serial;session=r.session;render();showNotice('学习记录已开始。暂停时间不计入学习；时长不代表掌握。');}
 function suggest(value){suggestion=value;renderEntry();}
 function suggestFor(kind,cid,aid,base){base=defaults[kind]??base;if(suggestion?.growth_task_id&&suggestion.course_id===cid)return; suggestion={course_id:cid,atom_id:aid||undefined,activity_type:kind,base_minutes:base,predicted_minutes:base,source:kind==='review'?'review':'assessment',title:state.data?.course.title||'本次学习',estimate_source:'初始规则估时'};renderEntry();}
 function endDialog(adjust=false){if(!session)return;const id=session.id,d=dialog('结束本次学习记录');d.append(node('p','这只结束本次计时，不会把课程、成长任务或知识点标为掌握。','muted'));
  const choose=node('label','本次完成情况'),completion=node('select');completion.name='completion';for(const [v,label]of Object.entries({partial:'完成一部分',mostly_done:'大部分完成',done:'本次安排已完成',not_started:'还未开始便停止'})){const o=node('option',label);o.value=v;completion.append(o);}choose.append(completion);d.append(choose);
  const why=node('label','结束原因'),reason=node('select');reason.name='reason';for(const [v,label]of Object.entries(reasons)){const o=node('option',label);o.value=v;reason.append(o);}why.append(reason);d.append(why);
  const correction=node('label','修正实际学习分钟（可留空）'),minutes=node('input');minutes.type='number';minutes.name='adjusted_active_minutes';minutes.min=0;minutes.max=1440;minutes.step=.1;if(adjust)minutes.value=Math.round(elapsed()/6)/10;correction.append(minutes);d.append(correction,node('small','例如忘记暂停，可只保留实际学习时间。中断记录不会进入完整任务估时。','muted'));
  const valid=node('label','','option'),invalid=node('input');invalid.type='checkbox';valid.append(invalid,document.createTextNode('这是一条错误记录，不用于估时'));d.append(valid);
  const long=node('label','','option'),confirm=node('input');confirm.type='checkbox';long.append(confirm,document.createTextNode('我确认这个较长时段的记录准确'));long.hidden=elapsed()<=240*60;d.append(long);
  d.append(btn('保存并结束',async()=>{if(session?.id!==id)throw Error('当前记录已变化，请重新打开');const payload={completion:completion.value,reason:reason.value,invalid_for_pace:invalid.checked,confirm_long_duration:confirm.checked};if(minutes.value!=='')payload.adjusted_active_minutes=Number(minutes.value);const r=await change('end',payload);d.close();const summary=r.session.outcome;showNotice(`本次记录已保存${summary.quiz_count?'，观察到 '+summary.quiz_count+' 次答题':''}。掌握判断仍依据独立学习结果。`);if(state.page==='dashboard')await MindOSUniverse.showDashboard();},true));
 }
 async function history(){const d=dialog('学习执行记录'),filter=node('div','','growth-form');d.append(node('p','记录保存在本机。时长与快慢都不代表知识掌握，也不评价自律或生产力。','muted'),filter);
  const from=node('input'),to=node('input');from.type=to.type='date';from.setAttribute('aria-label','开始日期');to.setAttribute('aria-label','结束日期');filter.append(from,to);const content=node('div');d.append(content);
  async function load(cursor=null,append=false){const params=new URLSearchParams();if(from.value)params.set('date_from',from.value);if(to.value)params.set('date_to',to.value);if(cursor)params.set('before',cursor);const r=await call('/api/study/sessions?'+params);if(!d.isConnected)return;if(!append)content.replaceChildren();
   if(!r.sessions.length)content.append(node('p','暂无主动开始的学习记录。','muted'));
   for(const s of r.sessions){const row=node('article','','study-history-row');row.dataset.sessionId=s.id;row.append(node('h3',s.title),node('p',`${new Date(s.started_at).toLocaleString('zh-CN')} · ${types[s.activity_type]} · ${statuses[s.status]}`),node('p',`记录约 ${Math.round(s.active_seconds/60)} 分钟 · 暂停约 ${Math.round(s.paused_seconds/60)} 分钟${s.adjusted_by_user?' · 已手动修正':''}${s.was_interrupted?' · 曾中断，不用于估时':''}`));
    if(!['active','paused','interrupted'].includes(s.status)){row.append(btn('修正时间',()=>edit(s,row)),btn('删除错误记录',async()=>{if(!confirm('删除这条执行记录？答题、课程与掌握记录会保留。'))return;await call('/api/study/sessions/'+s.id,{},'DELETE');await load();}));}
    if(s.outcome.quiz_count!==undefined)row.append(node('small',`关联答题 ${s.outcome.quiz_count} 次 · ${s.outcome.knowledge_state_changed?'已有学习结果使知识状态变化':'未观察到知识状态变化'}`,'muted'));content.append(row);
   }
   if(r.next_cursor)content.append(btn('更多记录',async()=>{content.lastChild.remove();await load(r.next_cursor,true);}));
  }
  function edit(s,row){row.querySelector('.study-edit')?.remove();const editor=node('div','','study-edit'),i=node('input');i.type='number';i.min=0;i.max=1440;i.step=.1;i.value=Math.round(s.active_seconds/6)/10;i.setAttribute('aria-label','修正分钟');editor.append(i,btn('保存修正',async()=>{await call('/api/study/sessions/'+s.id,{adjusted_active_minutes:Number(i.value)},'PATCH');await load();}));row.append(editor);}
  filter.append(btn('筛选记录',()=>load()));await load();const pace=await call('/api/study/pace');if(d.isConnected){const info=node('details');info.append(node('summary','当前个人估时'));for(const p of pace.summary)info.append(node('p',p.label+'：'+p.summary));d.append(info);}
 }
 function today(root,data){root.append(node('h2','今天学习'),btn('查看学习执行记录',history));if(!data.today?.length)root.append(node('p',data.today_remaining_minutes===0?'已记录的时间达到今日参考预算，可以下次继续。':'暂无可执行建议，可进入课程主动开始学习。','muted'));
  for(const t of data.today||[]){const row=node('article','','study-today-task');row.append(node('h3',t.title),node('p',t.split?`今天先学一段 · 约 ${Math.round(t.planned_minutes)} 分钟（完整任务约 ${t.predicted_minutes} 分钟）`:`预计约 ${t.predicted_minutes} 分钟`),node('small',t.estimate_source,'muted'),node('p',t.reason,'muted'));row.append(btn('打开建议任务',async()=>{if(t.session_id){await refresh();if(t.course_id)await openCourse(t.course_id);return;}if(t.goal_id&&t.task_id){await MindOSGrowth.startTask(t.goal_id,t.task_id);}else if(t.course_id){await openCourse(t.course_id);suggest({course_id:t.course_id,atom_id:t.atom_id,activity_type:t.activity_type,base_minutes:t.base_minutes,predicted_minutes:t.predicted_minutes,estimate_source:t.estimate_source,source:'today'});if(t.atom_id)await MindOSLearningLoop.check(t.course_id,t.atom_id,'review');}},true));root.append(row);}
  if(data.weekly_budget!==null&&data.weekly_budget!==undefined)root.append(node('p',`本周参考预算 ${data.weekly_budget} 分钟 · 已记录约 ${Math.round(data.weekly_actual_minutes)} 分钟`,'muted'));
  if(data.weekly?.length){const details=node('details');details.append(node('summary','本周优先安排'));for(const t of data.weekly)details.append(node('p',`${t.title} · 约 ${Math.round(t.planned_minutes)} 分钟${t.split?'（先进行一段）':''}`));root.append(details);}
  root.append(node('small',data.boundary,'muted'));
 }
 async function execution(root,g){const report=await call(`/api/goals/${g.id}/execution`);if(!root.isConnected)return;const box=node('section','','card study-execution');box.append(node('h2','计划与实际节奏'),node('p',`每周计划 ${report.weekly_planned_minutes??'未设置'} 分钟 · 本周已记录约 ${Math.round(report.weekly_actual_minutes)} 分钟`));
  if(g.deadline)box.append(node('p',`截止 ${g.deadline} · 剩余参考约 ${Math.round(report.deadline.remaining_minutes/60)} 小时`),node('p',report.deadline.summary),node('small',report.deadline.actual_capacity_minutes_per_week===null?'真实历史不足；预算只是计划，不代表实际容量。':`最近完整周主动记录约 ${report.deadline.actual_capacity_minutes_per_week} 分钟 / 周`,'muted'));
  const trend=node('details');trend.append(node('summary','最近各周的记录'));for(const w of report.weeks)trend.append(node('p',`${w.week_start} 起：约 ${Math.round(w.actual_minutes)} 分钟${w.complete_week?'':'（尚不是完整观察周）'}`));box.append(trend);
  if(report.replan_recommended){box.append(node('p','建议审查时间安排，再决定是否重新规划。不会自动删除课程内容。','notice'));for(const option of report.adjustment_options)box.append(node('p',option));box.append(btn('调整目标时间与预算',()=>root.querySelector('.growth-goal').querySelectorAll('button')[0].click()),btn('使用现有成长路线重新规划',()=>root.querySelector('.growth-route')?.querySelectorAll('.action-row button')[1]?.click()));}
  if(report.execution_friction.length)box.append(node('p','部分任务出现反复停止、延续到下次或用时偏差。可先拆小学习安排、修正估时，或检查前置知识。','muted'));
  box.append(node('small',report.boundary,'muted'));root.append(box);
 }
 document.addEventListener('DOMContentLoaded',()=>{bar=node('section','','study-session-bar');bar.id='study-session-bar';bar.setAttribute('aria-label','当前学习记录');bar.hidden=true;document.querySelector('.topbar').after(bar);entry=node('section','','study-entry');entry.id='study-entry';entry.hidden=true;document.querySelector('.content').prepend(entry);MindOSStore.subscribe((_,keys)=>{if(keys.some(k=>['page','courseId','data'].includes(k)))renderEntry();});refresh().catch(e=>showNotice(e.message));
  setInterval(()=>{if(!session)return;const timer=$('study-elapsed');if(timer&&!hidden())timer.textContent=time(elapsed());if(session.status==='active'&&++tick%30===0&&!pending){const id=session.id,token=serial;call(`/api/study/sessions/${id}/checkpoint`,{}).then(r=>{if(token===serial&&session?.id===id){session=r.session;render();}}).catch(()=>{/* Server will restore from the last successful checkpoint. */});}},1000);
 });
 window.MindOSStudy={refresh,suggest,clearSuggestion:()=>{suggestion=null;renderEntry();},suggestFor,course:renderEntry,history,today,execution};
})();
