/* AssistantButton, AssistantPanel, ChatMessage, ChatInput and DraggableAssistant. */
const CourseAssistant=(()=>{
 let courseId=null, contextKey='', generation=0, expanded=false, messages=[], hasMore=false, loadingHistory=false;
 let panelRect=null, panelPointer=null, observations=[], position=null, pointer=null, suppressClick=false,nextFeedback=null,nextContext=null;const pending=new Set(),positions=new Map();
 const root=$('course-assistant'),toggle=$('assistant-toggle'),panel=$('assistant-panel');
 async function request(cid,suffix,method='GET',body){
  const route=suffix.startsWith('history')?`/api/tutor/conversations?context_id=${encodeURIComponent(cid)}${suffix.includes('?')?'&'+suffix.split('?')[1]:''}`:suffix==='chat'?'/api/tutor/chat':`/api/courses/${encodeURIComponent(cid)}/assistant/${suffix}`;
  if(suffix==='chat')body={...body,context_id:cid};
  const response=await fetch(route,body===undefined?{method}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.error || '助教暂时不可用');return data;
 }
 function current(){
  if(state.page==='universe'){const s=state.universeSelection;return s?.star.unlocked?{section_ordinal:s.star.section_ordinal,knowledge_atom_id:s.star.atom_id}:null;}
  if(!state.data || !['course','dashboard','growth'].includes(state.page))return null;
  if(state.authenticTask?.course_id===state.courseId)return {authentic_task_id:state.authenticTask.id};
  const atom=state.courseMode==='map' && !$('atom-panel').hidden?state.atomDetail?.atom:null;
  return {section_ordinal:atom?.section || state.data.section.ordinal,knowledge_atom_id:atom?.id || null,atom_mode:state.atomMode || 'quick'};
 }
 function label(){
  if(state.page==='universe'&&state.universeSelection?.star.unlocked){const s=state.universeSelection;$('assistant-course').textContent='当前课程：'+s.course.name;$('assistant-context').textContent='当前星云：'+s.section.name+' · 知识点：'+s.star.name;$('assistant-insight').textContent=s.star.state_label+'。'+s.star.state_basis+'；导师每次提问重新读取实际证据。';return;}
  const c=current();if(!c){$('assistant-course').textContent='选择一门课程，导师才知道从哪里开始。';$('assistant-context').textContent='学习记忆按课程隔离。';$('assistant-insight').textContent='先进入课程，或从驾驶舱选择当前课程。不会在没有学习证据时推断你的能力。';return;}
  if(c.authentic_task_id){$('assistant-course').textContent=`当前课程：${state.data.course.title}`;$('assistant-context').textContent='开放能力检测 · 当前任务';$('assistant-insight').textContent='我会先引导你理解任务。求助会保存提示记录，本次不用于校准；不会改变掌握状态。';return;}
  const section=state.data.course.sections.find(s=>s.ordinal===c.section_ordinal);
  $('assistant-course').textContent=`当前课程：${state.data.course.title}`;
  const final=state.data.course_final;
  if(final?.plan?.status==='active'&&!final.plan.stale&&final.current_quiz){
   const target=state.data.knowledge.atoms.find(a=>a.id===final.current_quiz.item.atom_id);
   $('assistant-context').textContent='课程掌握检测 · 当前题：'+(target?.title||'当前知识点');
   $('assistant-insight').textContent='先试着独立思考，我可以给方向提示。向导师求助或查看解释会留下提示记录，这题按练习处理。';return;
  }
  $('assistant-context').textContent=`当前星云（小节）：${section.title}`+(c.knowledge_atom_id?` · 知识点：${state.atomDetail.atom.title}`:'');
  const weak=state.data.knowledge.atoms.filter(a=>a.unlocked&&a.rate!==null&&a.rate<60).slice(0,3);
  $('assistant-insight').textContent=weak.length?'独立测试线索：'+weak.map(a=>a.title).join('、')+'需要补强。可以让我换个例子，或补充前置知识。':'暂无需要补强的独立测试记录。你可以要求换一种说法、看个例子或看图理解。';
 }
 function error(text){$('assistant-error').textContent=text || '';toggle.title=text || '点击提问；拖动图标可调整位置';}
 function clamp(point){return {x:Math.max(8,Math.min(point.x,Math.max(8,innerWidth-64))),y:Math.max(8,Math.min(point.y,Math.max(8,innerHeight-64)))};}
 function DraggableAssistant(point){
  position=clamp(point);toggle.style.left=`${position.x}px`;toggle.style.top=`${position.y}px`;
  if(panelRect){placePanel();return;}
  const width=Math.min(430,innerWidth-16),height=Math.min(680,innerHeight-40);
  panel.style.width=`${width}px`;panel.style.height=`${height}px`;panel.style.maxHeight=`${height}px`;
  panel.style.left=`${Math.max(8,Math.min(position.x+56-width,innerWidth-width-8))}px`;
  panel.style.top=`${Math.max(8,Math.min(position.y-height-10,innerHeight-height-8))}px`;
 }
 async function savePosition(cid,point){
  if(!cid){localStorage.setItem('mindos-global-tutor-position',JSON.stringify(point));return;}
  positions.set(cid,point);
  try{await request(cid,'position','PUT',point);}catch(e){if(courseId===cid)error('助手位置未保存：'+e.message);}
 }
 function ChatMessage(message){
  const item=node('article','',`assistant-chat-message ${message.role}`);item.dataset.messageId=message.id;
  item.append(node('strong',message.role==='user'?'你的问题':'课程助教'));
  const text=node('div','','assistant-message-content');
  if(message.role==='assistant')MindOSTutor.render(text,message.blocks?.length?message.blocks:[{type:"paragraph",content:message.content}],{action:message.teaching_action,onFeedback:feedback=>{
   if($('assistant-question').disabled)return;
   $('assistant-question').value=feedback.question+' 请参考这段讲解：'+message.content.slice(0,900);nextFeedback=feedback.kind;
   nextContext=message.context?.section_ordinal?{section_ordinal:message.context.section_ordinal,knowledge_atom_id:message.context.knowledge_atom_id}:null;
   $('assistant-chat-form').requestSubmit();
  }});else text.textContent=message.content;item.append(text);
  if(message.role==='assistant'){
   if(message.context)item.append(node('p',`提问时：${message.context.section_title}${message.context.knowledge_title?' · '+message.context.knowledge_title:''}`,'muted'));
   const related=node('div','','assistant-related');
   (message.related_knowledge || []).forEach(atom=>{const button=node('button',atom.title,'atom-chip');button.type='button';button.dataset.atomId=atom.id;button.onclick=async()=>{const cid=courseId;expanded=false;AssistantButton();if(state.page==='universe'){await MindOSKnowledgeUniverse.selectByAtom(cid,atom.id);return;}if(state.page!=='course')await openCourse(cid,undefined,'stars');else setCourseMode('map');if(state.courseId!==cid)return;await openAtom(atom.id);};related.append(button);});
   if(related.childElementCount)item.append(node('p','相关知识点'),related);
   if(message.search?.note)item.append(node('p',message.search.note,'muted'));
   (message.search?.sources || []).forEach(source=>{const link=node('a',source.title || source.url,'assistant-source');link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';item.append(link,node('p',source.description,'muted'));});
  }
  return item;
 }
 function AssistantPanel(scroll=true){
  MindOSTutorQuality.render(courseId,messages.map(m=>m.id).join(","));
  renderObservations();
  const history=$('assistant-messages');history.replaceChildren(...messages.map(ChatMessage));
  if(!messages.length)history.append(node('p',courseId?'哪里没理解，直接问我。我会结合这门课程和当前小节解释。':'先选择一门课程，让导师带着课程和学习记录解释。','muted'));
  $('assistant-history-more').hidden=!hasMore;
  $('assistant-send').disabled=!courseId || pending.has(courseId) || loadingHistory;$('assistant-question').disabled=!courseId || pending.has(courseId) || loadingHistory;
  if(scroll)history.scrollTop=history.scrollHeight;
 }
 function AssistantButton(){
  root.hidden=false;
  $('assistant-select-course').hidden=Boolean(current());
  toggle.dataset.pending=String(Boolean(courseId&&pending.has(courseId)));
  const tutorState={expanded,pending:Boolean(courseId&&pending.has(courseId)),courseId};
  if(JSON.stringify(state.aiTutorState)!==JSON.stringify(tutorState))state.aiTutorState=tutorState;
  panel.hidden=!expanded;toggle.setAttribute('aria-expanded',String(expanded));label();
 }
 async function sync(){
  const c=current();if(!c){if(!position){let saved=null;try{saved=JSON.parse(localStorage.getItem('mindos-global-tutor-position'));}catch(_){}DraggableAssistant(saved&&Number.isFinite(saved.x)&&Number.isFinite(saved.y)?saved:{x:innerWidth-64,y:innerHeight-80});}if(courseId!==null){generation++;courseId=null;messages=[];observations=[];panelRect=null;hasMore=false;expanded=false;nextFeedback=null;nextContext=null;}loadingHistory=false;AssistantButton();AssistantPanel();return;}
  const cid=state.data.course.id;
  if(cid===courseId){contextKey=JSON.stringify(c);AssistantButton();return;}
  pointer=null;panelPointer=null;observations=[];courseId=cid;loadPanelRect(cid);const version=++generation;contextKey=JSON.stringify(c);expanded=false;messages=[];hasMore=false;loadingHistory=true;nextFeedback=null;nextContext=null;error('');$('assistant-question').value='';
  DraggableAssistant(positions.get(cid) || {x:innerWidth-80,y:innerHeight-80});AssistantButton();AssistantPanel();
  try{
   const result=await request(cid,'history');if(courseId!==cid || version!==generation)return;
   messages=result.messages;hasMore=result.has_more;if(state.page!=='universe')loadObservations(cid,version);
   if(result.position){positions.set(cid,result.position);DraggableAssistant(result.position);}
   AssistantPanel();
  }catch(e){if(courseId===cid && version===generation)error(e.message);}
  finally{if(courseId===cid && version===generation){loadingHistory=false;AssistantPanel();}}
 }
 toggle.addEventListener('click',()=>{if(suppressClick){suppressClick=false;return;}expanded=!expanded;AssistantButton();if(expanded){AssistantPanel();(courseId?$('assistant-question'):$('assistant-select-course')).focus();}});
 $('assistant-close').addEventListener('click',()=>{expanded=false;AssistantButton();toggle.focus();});
 toggle.addEventListener('pointerdown',event=>{if(event.button!==0)return;pointer={id:event.pointerId,cid:courseId,startX:event.clientX,startY:event.clientY,x:position.x,y:position.y,moved:false};toggle.setPointerCapture(event.pointerId);});
 toggle.addEventListener('pointermove',event=>{if(!pointer || pointer.id!==event.pointerId)return;
  const dx=event.clientX-pointer.startX,dy=event.clientY-pointer.startY;
  if(Math.hypot(dx,dy)>5)pointer.moved=true;
  if(pointer.moved){event.preventDefault();DraggableAssistant({x:pointer.x+dx,y:pointer.y+dy});}
 });
 toggle.addEventListener('pointerup',event=>{if(!pointer || pointer.id!==event.pointerId)return;const drag=pointer;pointer=null;suppressClick=drag.moved;if(drag.moved){DraggableAssistant({x:position.x+28<innerWidth/2?8:innerWidth-64,y:position.y});savePosition(drag.cid,position);}});
 toggle.addEventListener('pointercancel',()=>{pointer=null;suppressClick=false;});
 toggle.addEventListener('keydown',event=>{if(!event.altKey || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();const dx=event.key==='ArrowLeft'?-20:event.key==='ArrowRight'?20:0;const dy=event.key==='ArrowUp'?-20:event.key==='ArrowDown'?20:0;DraggableAssistant({x:position.x+dx,y:position.y+dy});savePosition(courseId,position);});
 panel.addEventListener('keydown',event=>{if(event.key==='Escape'){expanded=false;AssistantButton();toggle.focus();}});
 async function ChatInput(event){
  event.preventDefault();const cid=courseId,c=nextContext||current(),question=$('assistant-question').value.trim();if(!cid || !c || !question || pending.has(cid) || loadingHistory)return;
  const version=generation,requestId=crypto.randomUUID();pending.add(cid);AssistantButton();error('');$('assistant-send').textContent='正在解释…';AssistantPanel(false);
  try{
   const feedback=nextFeedback;nextFeedback=null;nextContext=null;
   const result=await request(cid,'chat','POST',{message:question,request_id:requestId,current_context:c,...(feedback?{feedback}: {})});
   if(cid===courseId && version===generation){messages.push(...result.messages);observations=result.observations||[];$('tutor-memory-indicator').textContent=result.memory_note||'只保留学习相关问答；疑似误区待检测。';$('assistant-question').value='';AssistantPanel();renderObservations();}
  }catch(e){if(cid===courseId && version===generation)error(e.message);}
  finally{pending.delete(cid);AssistantButton();if(cid===courseId){$('assistant-send').textContent='发送问题';AssistantPanel(false);$('assistant-question').focus();}}
 }
 $('assistant-question').addEventListener('input',()=>{nextFeedback=null;nextContext=null;});
 $('assistant-chat-form').addEventListener('submit',ChatInput);
 $('assistant-history-more').addEventListener('click',async()=>{
  const cid=courseId,version=generation;const first=messages.find(m=>Number.isInteger(m.id));if(!first)return;
  try{const result=await request(cid,'history?before='+first.id);if(cid!==courseId || version!==generation)return;messages=[...result.messages,...messages];hasMore=result.has_more;AssistantPanel(false);}catch(e){if(courseId===cid)error(e.message);}
 });
 function loadPanelRect(cid){try{panelRect=JSON.parse(localStorage.getItem('mindos-tutor-panel-'+cid));if(!panelRect||!['x','y','width','height'].every(k=>Number.isFinite(panelRect[k])))panelRect=null;}catch(_){panelRect=null;}}
 function placePanel(){if(!panelRect)return;const width=Math.min(Math.max(320,panelRect.width),innerWidth-16),height=Math.min(Math.max(420,panelRect.height),innerHeight-16);const x=Math.max(8,Math.min(panelRect.x,innerWidth-width-8)),y=Math.max(8,Math.min(panelRect.y,innerHeight-height-8));Object.assign(panel.style,{left:x+'px',top:y+'px',width:width+'px',height:height+'px',maxHeight:height+'px'});}
 function rememberPanel(){if(courseId&&panelRect)localStorage.setItem('mindos-tutor-panel-'+courseId,JSON.stringify(panelRect));}
 function startPanel(event,resize){if(event.button!==0||(!resize&&event.target.closest('button')))return;const r=panel.getBoundingClientRect();panelRect={x:r.x,y:r.y,width:r.width,height:r.height};panelPointer={id:event.pointerId,x:event.clientX,y:event.clientY,rect:{...panelRect},resize};event.currentTarget.setPointerCapture(event.pointerId);}
 for(const [id,resize]of [['assistant-drag-handle',false],['assistant-resize-handle',true]]){
  const handle=$(id);handle.addEventListener('pointerdown',e=>startPanel(e,resize));handle.addEventListener('pointermove',e=>{if(!panelPointer||panelPointer.id!==e.pointerId)return;const p=panelPointer,dx=e.clientX-p.x,dy=e.clientY-p.y;panelRect={...p.rect,...(p.resize?{width:p.rect.width+dx,height:p.rect.height+dy}:{x:p.rect.x+dx,y:p.rect.y+dy})};placePanel();});
  handle.addEventListener('pointerup',()=>{panelPointer=null;const r=panel.getBoundingClientRect();panelRect={x:r.x,y:r.y,width:r.width,height:r.height};rememberPanel();});handle.addEventListener('pointercancel',()=>{panelPointer=null;});
  handle.addEventListener('keydown',e=>{if(!e.altKey||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const r=panel.getBoundingClientRect(),dx=e.key==='ArrowLeft'?-20:e.key==='ArrowRight'?20:0,dy=e.key==='ArrowUp'?-20:e.key==='ArrowDown'?20:0;panelRect=resize?{x:r.x,y:r.y,width:r.width+dx,height:r.height+dy}:{x:r.x+dx,y:r.y+dy,width:r.width,height:r.height};placePanel();rememberPanel();});
 }
 async function tutorRequest(path,body){const response=await fetch('/api/tutor/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.error||'导师建议暂不可用');return data;}
 async function loadObservations(cid,version){try{const result=await tutorRequest('observations?context_id='+encodeURIComponent(cid));if(courseId===cid&&generation===version){observations=result.observations;renderObservations();}}catch(e){if(courseId===cid)error(e.message);}}
 function renderObservations(){const root=$('tutor-observations');root.replaceChildren();const candidate=observations.find(o=>o.status==='candidate'&&(!o.verification?.quiz_id||o.verification?.outcome==='practice_only')&&['possible_gap','possible_misconception','confusion_signal'].includes(o.observation_type));if(!candidate){const checked=observations.find(o=>o.verification?.outcome);if(checked)root.append(node('p',checked.verification.outcome==='check_passed'?'独立短检测已通过，候选线索不会当作已确认误区。':checked.verification.outcome==='practice_only'?'这次有求助记录，只作练习；可重新进行独立短检测。':'独立短检测仍有困难，建议回看这个知识点；错误不能直接确认导师猜测的具体误区。','muted'));return;}const card=node('div','','tutor-observation-card');card.append(node('strong','待验证的学习线索'),node('p',candidate.description),node('p','这是导师建议，不是确认的误区。','muted'));const verify=node('button','做一个独立短检测','button secondary'),dismiss=node('button','忽略这条建议','icon-button');verify.type=dismiss.type='button';const cid=courseId,version=generation;verify.onclick=async()=>{verify.disabled=true;try{const r=await tutorRequest('observations/'+candidate.id+'/verify',{});if(courseId!==cid||generation!==version)return;if(r.quiz?.available===false){error(r.note);return;}if(r.quiz)showVerification(root,r,cid,version);else error(r.note);}catch(e){if(courseId===cid)error(e.message);}finally{verify.disabled=false;}};dismiss.onclick=async()=>{try{await tutorRequest('observations/'+candidate.id+'/dismiss',{});await loadObservations(cid,version);}catch(e){if(courseId===cid)error(e.message);}};card.append(verify,dismiss);for(const suggestion of candidate.recommendations||[]){const button=node('button',suggestion.kind==='recommend_replan'?'查看成长路线':'查看开放练习','button secondary');button.type='button';button.onclick=async()=>{try{expanded=false;AssistantButton();if(suggestion.kind==='recommend_replan'){await MindOSGrowth.show(suggestion.goal_id);return;}if(state.page!=='course')await openCourse(cid);if(state.courseId!==cid)return;let host=$('tutor-authentic-practice');if(!host){host=node('section');host.id='tutor-authentic-practice';$('course-view').append(host);}host.replaceChildren();await MindOSAuthentic.render(host,null,cid);const select=host.querySelector('select');if(select)select.value=suggestion.atom_id;host.scrollIntoView({block:'start'});}catch(e){showNotice(e.message);}};card.append(button,node('p',suggestion.note,'muted'));}root.append(card);}
 function showVerification(root,result,cid,version){const quiz=result.quiz;root.replaceChildren();const box=node('div','','tutor-verification');box.append(node('h3','先独立回答'),node('p','只有本次答题结果进入原有学习检测，导师猜测不会进入掌握记录。','muted'));const form=node('form');quiz.questions.forEach((q,i)=>{const group=node('fieldset');group.append(node('legend',q.prompt));for(const[value,text]of Object.entries(q.choices)){const label=node('label','','option'),input=document.createElement('input');input.type='radio';input.name='tutor-answer-'+i;input.value=value;input.required=true;label.append(input,document.createTextNode(text));group.append(label);}MindOSLearningLoop.answerInputs(group,i,quiz,cid);form.append(group);});const submit=node('button','提交独立回答','button primary');submit.type='submit';form.append(submit);form.onsubmit=async e=>{e.preventDefault();const answers=quiz.questions.map((_,i)=>form.querySelector(`[name="tutor-answer-${i}"]:checked`)?.value);if(answers.some(a=>!a))return;submit.disabled=true;try{await api('/api/quizzes/submit',{course_id:cid,quiz_id:quiz.id,answers,...MindOSLearningLoop.answerMetadata(form,answers.length)});if(courseId!==cid||generation!==version)return;await loadObservations(cid,version);if(state.page==='universe'){await MindOSKnowledgeUniverse.refresh();error('短检测已保存，星图已读取新状态。');return;}const data=await api('/api/course?'+new URLSearchParams({course_id:cid,ordinal:current()?.section_ordinal||state.data.section.ordinal}));if(courseId!==cid||generation!==version)return;if(state.page==='course')renderCourse(data);else state.data=data;error('短检测已保存。需要复习时，可从课程学习建议继续。');}catch(err){if(courseId===cid)error(err.message);}finally{submit.disabled=false;}};box.append(form);root.append(box);}
 $('tutor-clear-history').onclick=async()=>{if(!courseId||pending.has(courseId))return;const cid=courseId,version=generation;try{const response=await fetch('/api/tutor/conversations',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({context_id:cid})});const r=await response.json();if(!response.ok)throw Error(r.error);if(courseId===cid&&generation===version){messages=[];observations=[];hasMore=false;AssistantPanel();$('tutor-memory-indicator').textContent=r.note;}}catch(e){if(courseId===cid)error(e.message);}};
 let scheduled=false;const observer=new MutationObserver(()=>{if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;sync();});});
 for(const id of ['course-view','welcome','review-view','course-management','chapter-mode','map-mode','atom-panel'])observer.observe($(id),{attributes:true,attributeFilter:['hidden']});
 for(const id of ['section-title','atom-title','course-title'])observer.observe($(id),{childList:true,subtree:true});
 let lastWidth=innerWidth;
 window.addEventListener('resize',()=>{if(position){const right=position.x+28>lastWidth/2;DraggableAssistant({x:right?innerWidth-64:8,y:position.y});}lastWidth=innerWidth;});
 $('assistant-select-course').onclick=()=>{expanded=false;AssistantButton();CourseManager.show();};
 MindOSStore.subscribe((_,keys)=>{if(keys.some(k=>['page','data','courseMode','atomDetail','atomMode','universeSelection'].includes(k)))sync();});
 sync();
 return {sync,open(){expanded=true;AssistantButton();AssistantPanel();$('assistant-question').focus();}};
})();
