/* Knowledge Universe: projections of existing APIs, never a second learner model. */
const MindOSUniverse=(()=>{
 const sv=(tag,attrs={},text='')=>{const item=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))item.setAttribute(key,String(value));item.textContent=text;return item;};
 const button=(text,callback,style='button secondary')=>{const b=node('button',text,style);b.type='button';b.onclick=callback;return b;};
 const title=(eyebrow,heading,description='')=>{const box=node('div','','universe-heading');box.append(node('p',eyebrow,'eyebrow'),node('h2',heading));if(description)box.append(node('p',description,'muted'));return box;};
 const short=(text,n=16)=>Array.from(text||'').length>n?Array.from(text).slice(0,n).join('')+'…':text;
 const date=value=>value?new Date(value).toLocaleString('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'尚未学习';
 function hideStandalone(){window.MindOSMission?.hide();window.MindOSKnowledgeUniverse?.hide();for(const id of ['learning-dashboard','growth-profile','growth-roadmap'])$(id).hidden=true;}
 function navigation(page){state.page=page;document.querySelectorAll('.primary-nav button').forEach(b=>b.classList.toggle('active',b.id===(page==='growth-roadmap'?'growth-roadmap-open':page==='growth'?'growth-open':page==='dashboard'?'dashboard-open':'')));$('course-manager-open').classList.toggle('active',page==='courses');}
 async function showDashboard(page='dashboard',cid){
  invalidateNavigation();hideStandalone();const version=navigationVersion;navigation(page);
  for(const id of ['welcome','review-view','course-view','course-management'])$(id).hidden=true;
  $('learning-dashboard').hidden=page!=='dashboard';$('growth-profile').hidden=page!=='growth';
  $('breadcrumb').textContent=page==='growth'?'成长档案':'学习驾驶舱';state.data=null;state.courseId=null;state.atomDetail=null;
  const root=$(page==='growth'?'growth-profile':'learning-dashboard');root.replaceChildren(node('p','正在读取学习记录…','muted'));root.setAttribute('aria-busy','true');
  try{
   const result=await api('/api/dashboard'+(cid?'?course_id='+encodeURIComponent(cid):''));
   state.dashboard=result;state.courses=result.courses;state.data=result.context;state.courseId=result.current?.course_id||null;
   state.courseMode='course';renderSidebar();page==='growth'?GrowthTimeline(root,result):LearningDashboard(root,result);
  }catch(error){if(version===navigationVersion)root.replaceChildren(node('p',error.message,'notice'),button('重新读取',()=>showDashboard(page,cid)));}
  finally{if(version===navigationVersion)root.setAttribute('aria-busy','false');}
 }
 function OrbitIllustration(){
  const drawing=sv('svg',{viewBox:'0 0 420 320',class:'orbit-illustration','aria-hidden':'true'});
  for(const [rx,ry,rotation]of [[150,75,-25],[150,75,35],[150,75,90]])drawing.append(sv('ellipse',{cx:210,cy:160,rx,ry,transform:`rotate(${rotation} 210 160)`,class:'orbit-ring'}));
  drawing.append(sv('circle',{cx:210,cy:160,r:53,class:'orbit-core'}),sv('circle',{cx:210,cy:160,r:40,class:'orbit-inner'}),sv('text',{x:210,y:173,'text-anchor':'middle',class:'orbit-symbol'},'✦'));
  for(const [x,y,r]of [[82,201,7],[330,109,9],[220,16,5],[294,252,5],[168,221,4],[79,84,3]])drawing.append(sv('circle',{cx:x,cy:y,r,class:'orbit-star'}));return drawing;
 }
 function CognitiveStatus(data){
  const section=node('section','','card cognitive-status');section.append(title('当前课程 · 独立题目记录','你的知识状态','只看当前课程最近8次已提交测验，不将不同课程的能力混在一起。'));
  const grid=node('div','','cognitive-grid');const dims=data.learning_state?.assessment_dimensions||{};
  for(const [label,key]of [['概念理解','concept'],['知识应用','application'],['迁移能力','transfer']]){
   const d=dims[key];const card=node('div','','cognitive-metric');card.dataset.dimension=key;
   const measured=d&&d.attempts>0;card.append(node('span',label),node('strong',measured?Math.round(d.rate*100)+'%':'尚未测量'));
   const meter=node('div','','metric-track');if(measured){const bar=node('span');bar.style.width=Math.round(d.rate*100)+'%';meter.append(bar);}card.append(meter,node('small',measured?`${d.correct}/${d.attempts} 道题答对` : key==='transfer'?'当前尚无独立迁移测验':'完成对应题型后再显示'));grid.append(card);
  }
  section.append(grid);return section;
 }
 function CoursePicker(data,page){const label=node('label','查看课程 ','course-picker');const select=node('select');select.setAttribute('aria-label','查看课程状态');select.append(node('option','选择课程'));select.firstChild.value='';for(const c of data.courses){const o=node('option',c.title);o.value=c.id;select.append(o);}select.value=data.current?.course_id||'';select.onchange=()=>{if(select.value)showDashboard(page,select.value);};label.append(select);return label;}
 function LearningDashboard(root,data){
  root.replaceChildren();const hero=node('section','','dashboard-hero');const copy=node('div','','hero-copy');copy.append(node('p','KNOWLEDGE UNIVERSE · 学习驾驶舱','eyebrow'),node('h1','让知识连成\n你的宇宙。'),node('p','从一个问题开始，沿着清晰的路线理解、练习，再把知识留在自己的星图里。','hero-description'));
  const actions=node('div','','action-row');actions.append(button(data.current?'继续探索 →':'创建第一门课程 →',()=>data.current?openCourse(data.current.course_id,undefined,'learn'):showWelcome(),'button primary'),button('查看我的课程',()=>CourseManager.show()));copy.append(actions);hero.append(copy,OrbitIllustration());root.append(hero);
  const stats=node('div','','dashboard-stats');for(const [label,value,note]of [['课程空间',data.courses.length,'包含暂停与归档课程'],['正在探索',data.courses.filter(c=>c.status==='active').length,'学习中的课程'],['当前小节',data.current?`${data.current.section_ordinal} / ${data.current.section_count}`:'尚未开始','由你决定何时前进']]){const item=node('div');item.append(node('small',label),node('strong',String(value)),node('span',note));stats.append(item);}root.append(stats);
  const grid=node('div','','dashboard-grid');const current=node('section','','card current-journey');current.append(title('CONTINUE YOUR JOURNEY','继续上次的探索'),CoursePicker(data,'dashboard'));
  if(data.current){current.append(node('h3',data.current.course_title),node('p',`第 ${data.current.section_ordinal} 星云 · ${data.current.section_title}`),node('p',data.current.goal||'从基础开始，循序渐进。','muted'));const p=node('progress');p.max=100;p.value=data.current.progress;p.setAttribute('aria-label','课程学习进度');current.append(p,node('p',`学习进度 ${data.current.progress}% · 不代表掌握率`,'muted'),button('进入课程宇宙 ↗',()=>openCourse(data.current.course_id,undefined,'overview')));}else current.append(node('p','还没有学习中的课程。创建一门课程，或在“我的课程”中恢复探索。','muted'),button('新建课程',showWelcome));
  const next=node('section','','card recommendation-card');next.append(title('NEXT STEP','下一步，往哪里走？','根据当前课程的测试、阅读和复习记录给出建议。'));
  for(const r of data.recommendations){const row=node('div','','recommendation');row.append(node('h3',r.title),node('p',r.reason,'muted'),button(r.atom_id?'查看这颗知识星辰 →':'进入当前学习空间 →',async()=>{await openCourse(r.course_id,undefined,r.atom_id?'stars':'learn');if(r.atom_id&&state.courseId===r.course_id){await openAtom(r.atom_id);}}));next.append(row);}if(!data.current)next.append(node('p','尚无学习证据。先告诉 MindOS 你想学什么，以及你目前的基础。','muted'));next.append(node('small','规则建议 · 不自动解锁章节，不推断未测能力。','muted'));
  grid.append(current,next);root.append(grid,CognitiveStatus(data));
  if(data.final_attention?.length){const final=node('section','','card');final.append(node('h2','内容学完后，看看掌握了哪些知识'));for(const item of data.final_attention)final.append(button(item.course_title+' · '+item.label,async()=>{await openCourse(item.course_id,undefined,'learn');$('course-final-panel').scrollIntoView({block:'start'});}));root.append(final);}
  if(data.today_reviews?.length){const reviews=node('section','','card');reviews.append(node('h2','今日复习 · 先试着回忆'));for(const r of data.today_reviews)reviews.append(button(`${r.course_title} · ${r.title} · 约${r.minutes}分钟`,async()=>{await openCourse(r.course_id,undefined,'learn');if(state.courseId===r.course_id)await MindOSLearningLoop.check(r.course_id,r.atom_id,'review');}));root.append(reviews);}
  if(window.MindOSMission)MindOSMission.dashboard(root).catch(e=>showNotice(e.message));
  if(typeof MindOSGrowth!=='undefined'){const growth=node('section','','card');growth.append(button('管理我的学习目标',()=>MindOSGrowth.show()));if(window.MindOSStudy)MindOSStudy.today(growth,data.growth||{});root.append(growth);}
  const activity=node('section','','card');activity.append(title('RECENT ACTIVITY','最近留下的学习足迹'));Timeline(activity,data.timeline.slice(0,5));root.append(activity);
 }
 function Timeline(root,events){const list=node('ol','','growth-timeline');const labels={lesson:'生成小节讲解',quiz:'完成独立小测',reading:'记录阅读 / 复习',tutor:'向课程导师提问'};
  if(!events.length)root.append(node('p','还没有学习记录。阅读和聊天会留下足迹，独立小测才形成掌握证据。','muted'));
  for(const event of events){const row=node('li');row.dataset.kind=event.kind;row.append(node('span','',`timeline-dot ${event.kind}`));const body=node('div');body.append(node('strong',labels[event.kind]),node('p',event.course_title+(event.section_title?' · '+event.section_title:''),'muted'));if(event.kind==='quiz')body.append(node('span',`${event.score}/${event.question_count} 题答对`,'badge'));row.append(body,node('time',date(event.at)));list.append(row);}root.append(list);
 }
 function ProgressVisualization(events){const tests=events.filter(e=>e.kind==='quiz').reverse();const wrap=node('div','','progress-visualization');
  if(!tests.length){wrap.append(node('p','完成独立小测后，这里会展示每次作答的正确率。','muted'));return wrap;}
  const drawing=sv('svg',{viewBox:'0 0 700 200',role:'img','aria-label':'当前课程每次测验正确率，不是能力认证'});
  for(const n of [0,50,100]){const y=170-n*1.35;drawing.append(sv('line',{x1:42,y1:y,x2:678,y2:y,class:'chart-grid'}),sv('text',{x:5,y:y+4,class:'chart-label'},n+'%'));}
  const points=tests.map((t,i)=>({x:tests.length===1?360:52+i*615/(tests.length-1),y:170-(t.score/t.question_count)*135,t}));drawing.append(sv('polyline',{points:points.map(p=>`${p.x},${p.y}`).join(' '),class:'chart-line'}));for(const p of points){const dot=sv('circle',{cx:p.x,cy:p.y,r:5,class:'chart-point'});dot.append(sv('title',{},`${date(p.t.at)} · ${p.t.score}/${p.t.question_count}题答对`));drawing.append(dot);}wrap.append(drawing,node('p','每个点是一次已提交测验。题型和难度可能不同，折线不表示经过标准化测量的能力增长。','muted'));return wrap;
 }
 function GrowthTimeline(root,data){root.replaceChildren(title('YOUR LEARNING FOOTPRINT','成长档案','每一次理解、提问和练习，都有迹可循。'),CoursePicker(data,'growth'),CognitiveStatus(data));const chart=node('section','','card');chart.append(title('独立测验','看见每一次练习'),ProgressVisualization(data.timeline.filter(e=>e.course_id===data.current?.course_id)));const history=node('section','','card');history.append(title('真实活动记录','学习时间线'));Timeline(history,data.timeline);root.append(chart,history);}
 function galaxyStatus(data,section){const m=data.mastery.sections[section.ordinal-1];return section.ordinal>data.course.current_ordinal?'locked':section.ordinal===data.course.current_ordinal?'current':m.label==='较稳固'?'strong':'visited';}
 function GalaxyMap(data){const drawing=sv('svg',{viewBox:`0 0 800 ${Math.ceil(data.course.sections.length/3)*148+54}`,role:'group','aria-label':'课程小节星云，虚线为审查稿中的学习顺序'});const positions=[];
  data.course.sections.forEach((section,i)=>positions.push({x:140+(i%3)*260,y:88+Math.floor(i/3)*148}));
  for(let i=1;i<positions.length;i++){const a=positions[i-1],b=positions[i];drawing.append(sv('path',{d:a.y===b.y?`M ${a.x+44} ${a.y} L ${b.x-44} ${b.y}`:`M ${a.x} ${a.y+34} C ${a.x} ${a.y+90},${b.x} ${b.y-90},${b.x} ${b.y-34}`,class:'galaxy-order-line'}));}
  data.course.sections.forEach((section,i)=>{const p=positions[i],status=galaxyStatus(data,section);const g=sv('g',{class:`galaxy-node ${status}`,role:'button',tabindex:0,'aria-label':`第${section.ordinal}星云 ${section.title} ${status==='locked'?'尚未开放':'进入学习'}`});g.append(sv('circle',{cx:p.x,cy:p.y,r:34,class:'galaxy-halo'}),sv('circle',{cx:p.x,cy:p.y,r:21,class:'galaxy-core'}),sv('text',{x:p.x,y:p.y+5,'text-anchor':'middle',class:'galaxy-number'},String(section.ordinal)),sv('text',{x:p.x,y:p.y+62,'text-anchor':'middle',class:'galaxy-title'},short(section.title,15)),sv('text',{x:p.x,y:p.y+83,'text-anchor':'middle',class:'galaxy-status'},status==='locked'?'待进入':status==='current'?'当前学习':data.mastery.sections[i].label));g.append(sv('title',{},section.title+' · '+section.objective));const activate=()=>{if(status==='locked'){showNotice('这是后续小节。请在当前学习空间主动点击“进入下一小节”，系统不会自动推进。');return;}openCourse(data.course.id,section.ordinal,'learn');};g.onclick=activate;g.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();activate();}};drawing.append(g);});return drawing;}
 function CourseUniverse(data){const root=$('course-universe');root.replaceChildren();const summary=node('div','','universe-summary');summary.append(title('COURSE UNIVERSE','沿着星云，一节一节学会','每个星云对应一个小节，星辰对应知识点。虚线展示学习顺序，不代表已认证的知识依赖。'),button('进入当前学习空间 →',()=>{state.courseMode='course';viewCourse('learn');},'button primary'));root.append(summary);const map=node('section','','card galaxy-map');map.append(GalaxyMap(data));root.append(map);const cards=node('div','','galaxy-cards');data.course.sections.forEach(section=>{const item=node('article','','card galaxy-card '+galaxyStatus(data,section));const count=data.knowledge.atoms.filter(a=>a.section===section.ordinal).length;item.append(node('p',`第 ${section.ordinal} 星云 · 小节`,'eyebrow'),node('h3',section.title),node('p',section.objective,'muted'),node('small',`${count} 个知识点 · ${section.ordinal>data.course.current_ordinal?'尚未进入':data.mastery.sections[section.ordinal-1].label}`));cards.append(item);});root.append(cards);}
 function LearningSpace(data){const root=$('learning-support');root.replaceChildren(title('学习导航','留在当前目标'),node('h3',data.section.title),node('p',data.section.objective,'muted'));const action=data.next_teaching_action;if(action)root.append(node('small','下一次讲解的依据','eyebrow'),node('p',action.reason,'muted'));const weak=data.knowledge.atoms.filter(a=>a.unlocked&&a.rate!==null&&a.rate<60).slice(0,3);if(weak.length){root.append(node('h3','可以补强的知识'));for(const a of weak)root.append(button(a.title,()=>{setCourseMode('map');openAtom(a.id);}));}else root.append(node('p','暂无需要补强的独立测试记录。阅读和追问不会自动提高掌握率。','muted'));root.append(node('div','','divider'),node('p','点击悬浮的 ✦ AI，带着当前课程、章节和知识点继续提问。','muted'));}
 function viewCourse(view){state.courseMode=view==='stars'?'map':'course';state.courseView=view;navigation('course');for(const [key,id]of Object.entries({overview:'course-universe',learn:'chapter-mode',stars:'map-mode',feedback:'course-feedback',history:'course-history'}))$(id).hidden=key!==view;
  for(const [key,id]of Object.entries({overview:'mode-overview',learn:'mode-course',stars:'mode-map',feedback:'mode-feedback',history:'mode-history'})){$(id).className=key===view?'active':'';$(id).setAttribute('aria-current',key===view?'page':'false');}
  // Reuse the same quiz component and submission handlers in either view.
  if(view==='feedback')$('course-feedback').append($('quiz-card'));else if(view==='learn')$('chapter-mode').querySelector('.study-column').insertBefore($('quiz-card'),$('chapter-mode').querySelector('.next-card'));
  $('quiz-empty').hidden=Boolean(state.data?.section.lesson);
  if(view==='history')loadCourseHistory();
 }
 async function loadCourseHistory(){const cid=state.courseId;const root=$('course-history');root.replaceChildren(title('COURSE MEMORY','这门课程的学习记录'));try{const result=await api('/api/dashboard?course_id='+encodeURIComponent(cid));if(state.courseId!==cid||state.courseView!=='history')return;root.append(ProgressVisualization(result.timeline));Timeline(root,result.timeline);}catch(error){if(state.courseId===cid)root.append(node('p',error.message,'muted'));}}
 function renderCourse(data){CourseUniverse(data);LearningSpace(data);viewCourse(state.courseView||'learn');}
 function KnowledgeStar(atom){const s=atom.knowledge_state?.state;if(s)return ({unknown:'new',introduced:'learning',learning:'learning',unstable:'weak',mastered:'strong',review_due:'review-due',misconception:'misconception',prerequisite_gap:'prerequisite-gap'})[s]||'new';return atom.status==='较稳固'?'strong':atom.rate!==null&&atom.rate<60?'weak':atom.read||atom.rate!==null?'learning':'new';}
 function renderStarMap(knowledge){
  const root=$('knowledge-map');root.replaceChildren();const filters=$('star-galaxy-filter');filters.replaceChildren();const selected=state.starGalaxy||null;
  for(const [ordinal,label]of [[null,'全部星云'],...state.data.course.sections.map(s=>[s.ordinal,`第 ${s.ordinal} 星云 · ${s.title}`])]){const b=button(label,()=>{state.starGalaxy=ordinal;renderStarMap(knowledge);},'galaxy-filter'+(selected===ordinal?' active':''));b.setAttribute('aria-pressed',String(selected===ordinal));filters.append(b);}
  if(!knowledge.ready){root.append(node('p','尚未生成知识索引。你可以先在学习空间开始本节，也可以生成课程索引查看星辰之间的联系。','empty-map'));return;}
  const atoms=knowledge.atoms.filter(a=>!selected||a.section===selected);const columns=3,rows=Math.ceil(atoms.length/columns),height=Math.max(300,rows*116+90);const drawing=sv('svg',{viewBox:`0 0 820 ${height}`,role:'group','aria-label':'知识星辰网络；实线为知识关系，状态来自独立测试和阅读记录'});const positions=new Map();atoms.forEach((a,i)=>positions.set(a.id,{x:145+(i%columns)*265,y:70+Math.floor(i/columns)*116}));
  const arrow='star-arrow-'+crypto.randomUUID();const defs=sv('defs'),marker=sv('marker',{id:arrow,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto'});marker.append(sv('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'currentColor'}));defs.append(marker);drawing.append(defs);
  for(const edge of knowledge.edges){const a=positions.get(edge.from),b=positions.get(edge.to);if(!a||!b)continue;const line=sv('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,class:'star-connection','marker-end':`url(#${arrow})`});line.append(sv('title',{},relationTypes[edge.type]||edge.type));drawing.append(line);}
  for(const atom of atoms){const p=positions.get(atom.id),status=KnowledgeStar(atom),stateLabel=MindOSLearningLoop.labels[atom.knowledge_state?.state]||atom.status;const group=sv('g',{class:`map-node knowledge-star ${status}${atom.unlocked?'':' locked'}`,role:'button',tabindex:0,'aria-label':atom.title+' · '+stateLabel+(atom.unlocked?'':' · 后续小节')});group.dataset.atomId=atom.id;group.append(sv('title',{},atom.title+' · '+atom.summary),sv('circle',{cx:p.x,cy:p.y,r:28,class:'knowledge-star-halo'}),sv('circle',{cx:p.x,cy:p.y,r:9,class:'knowledge-star-core'}),sv('text',{x:p.x,y:p.y+48,'text-anchor':'middle',class:'star-title'},short(atom.title,17)),sv('text',{x:p.x,y:p.y+68,'text-anchor':'middle',class:'map-state'},atom.unlocked?({review_due:'◷ ',misconception:'! ',prerequisite_gap:'↩ '}[atom.knowledge_state?.state]||'')+stateLabel:'待进入对应小节'));
   const activate=()=>{if(!atom.unlocked){showNotice('这个知识点属于后续小节，请在当前学习空间主动进入下一小节。');return;}openAtom(atom.id);};group.onclick=activate;group.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();activate();}};drawing.append(group);
  }root.append(drawing);
 }
 document.addEventListener('DOMContentLoaded',()=>{
  $('dashboard-open').onclick=()=>showDashboard();$('growth-open').onclick=()=>showDashboard('growth',state.courseId||undefined);
  $('mode-overview').onclick=()=>viewCourse('overview');$('mode-feedback').onclick=()=>viewCourse('feedback');$('mode-history').onclick=()=>viewCourse('history');
 });
 return {showDashboard,hideStandalone,navigation,renderCourse,viewCourse,renderStarMap,KnowledgeStar};
})();
