const $ = id => document.getElementById(id);
const state = MindOSStore.create({ page: 'dashboard',courseView:'learn',starGalaxy:null,aiTutorState:{expanded:false,pending:false},courses: [], drafts: [], draft: null, profiles: [], selectedId: null,
  courseId: null, data: null, courseMode: 'course', atomDetail: null, atomMode: 'quick', busy: false, editingId: null, searchReady: false });

let navigationVersion=0;
const responseVersions=new WeakMap();
function invalidateNavigation(){navigationVersion++;showNotice('');}
function currentResponse(value){return !value || !responseVersions.has(value) || responseVersions.get(value)===navigationVersion;}

function node(tag, text = '', className = '') {
  const item = document.createElement(tag);
  if (className) item.className = className;
  item.textContent = text;
  return item;
}

function showNotice(message, success = false) {
  $('notice').hidden = !message;
  $('notice').textContent = message || '';
  $('notice').className = success ? 'notice success' : 'notice';
}

async function api(path, body) {
  const version=navigationVersion;
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if(version!==navigationVersion)throw new Error('页面已切换，本次结果已保存在原课程。');
  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试');
  for(const value of [data,data.course,data.draft])if(value&&typeof value==='object')responseVersions.set(value,version);
  return data;
}

async function action(button, message, work) {
  if (state.busy) return;
  state.busy = true;
  if (button) button.disabled = true;
  const version=navigationVersion;
  showNotice(message, true);
  try { await work(); if(version===navigationVersion)showNotice(''); }
  catch (error) { if(version===navigationVersion)showNotice(error.message); }
  finally { state.busy = false; if (button) button.disabled = false; }
}

function renderSidebar() {
  const list = $('course-list'); list.replaceChildren();
  state.courses.filter(course => (course.status || 'active') === 'active').forEach(course => {
    const button = node('button', course.title, 'course-link');
    button.type = 'button';
    if (course.id === state.courseId) button.classList.add('active');
    const small = node('small', `已到第 ${course.current_ordinal} 节`);
    button.append(small);
    button.addEventListener('click', () => openCourse(course.id,undefined,'overview'));
    list.append(button);
  });
}

function showWelcome() {
  if(typeof MindOSGrowth!=='undefined')MindOSGrowth.resetCreation();
  invalidateNavigation();
  if(typeof MindOSUniverse!=='undefined'){MindOSUniverse.hideStandalone();MindOSUniverse.navigation('create');}
  $('course-materials').value='';$('course-policy-field').hidden=true;
  document.querySelector('input[name="source-policy"][value="balanced"]').checked=true;
  $('course-level').value='零基础';
  for (const id of ['course-description','course-cover','course-tags']) $(id).value='';
  $('course-difficulty').value='入门';
  state.courseId = null; state.data = null; state.draft = null; state.atomDetail = null; state.courseMode = 'course';
  $('course-management').hidden = true;
  $('welcome').hidden = false; $('course-view').hidden = true; $('review-view').hidden = true;
  $('breadcrumb').textContent = '我的学习空间';
  renderSidebar(); renderDraftList();
  if (typeof CourseManager !== 'undefined') CourseManager.dashboard();
}

function renderDraftList() {
  const box = $('draft-list'); box.replaceChildren(); box.hidden = !state.drafts.length;
  if (!state.drafts.length) return;
  box.append(node('h3', '未确认的课程审查稿'));
  state.drafts.forEach(draft => {
    const button = node('button', draft.title, 'draft-button'); button.type = 'button';
    button.append(node('small', `第 ${draft.revision} 版 · 点击继续审查`));
    button.addEventListener('click', () => renderReview(draft));
    box.append(button);
  });
}

function draftSearchMode(draft) {
  return draft.search_mode || draft.sources.find(source => ['Brave', 'Tavily'].includes(source.provider || 'Brave'))
    ?.provider?.toLowerCase() || (draft.sources.some(source => !source.provider) ? 'brave' : 'public');
}

function fillSearchProfile() {
  const profile = state.searchProfiles.find(p => p.provider === $('search-provider').value);
  if (!profile) return;
  $('search-url').value = profile.api_url;
  $('search-key').value = '';
  $('search-key').placeholder = profile.has_key ? '留空保留已保存密钥；更换地址需重新填写' : '输入 API 密钥';
  $('search-status').textContent = profile.key_usable ? '配置已保存（尚未验证连接）' :
    profile.has_key ? '密钥无法解密，请重新填写' : '未配置；仍可使用免密钥公开资料检索';
}

function renderReview(draft) {
  if(!currentResponse(draft))return;
  MindOSUniverse.hideStandalone();MindOSUniverse.navigation('review');
  invalidateNavigation();
  state.draft = draft; state.courseId = null;
  $('course-management').hidden = true;
  $('welcome').hidden = true; $('course-view').hidden = true; $('review-view').hidden = false;
  $('breadcrumb').textContent = `${draft.title} / 审查课程方向`;
  $('review-title').textContent = draft.title;
  $('review-revision').textContent = `· 第 ${draft.revision} 版`;
  $('review-overview').textContent = draft.plan.overview;
  $('review-title-input').value = draft.title;
  $('review-goal-input').value = draft.goal;
  $('review-feedback').value = '';
  $('review-search-mode').value = draftSearchMode(draft);
  for (const [id, items] of [['review-outcomes', draft.plan.outcomes],
                              ['review-directions', draft.plan.directions]]) {
    const list = $(id); list.replaceChildren(...items.map(item => node('li', item)));
  }
  const sections = $('review-sections'); sections.replaceChildren();
  draft.plan.sections.forEach(item => {
    const row = node('li'); row.append(node('strong', item.title), node('span', item.objective));
    sections.append(row);
  });
  const report = draft.search_report;
  const labels = {ok: '有结果', partial: '结果不完整', unavailable: '暂时不可用', empty: '未找到结果'};
  $('review-search-report').textContent = report?.mode === 'public'
    ? `免密钥检索：保留 ${report.result_count} 条资料。` + report.sources.map(item =>
      `${item.provider}：${labels[item.status] || item.status}（${item.count} 条）；搜索词：${item.queries.join(' / ')}${item.issues.length ? '；' + item.issues.join('、') : ''}`).join('。')
    : report?.mode==='uploaded_materials' ? report.note+'。来源偏好：'+(draft.source_policy==='user_material_first'?'以我的资料为准':'综合资料')+'；水平：'+draft.learner_level : '';
  if (report?.discovery_plan) {
    const discovery = report.discovery_plan;
    $('review-search-report').textContent += ` 来源偏好：${draft.source_policy==='user_material_first'?'以我的资料为准':'综合资料'}；已分析 ${discovery.requirements.length} 项知识需求，安排 ${discovery.search_tasks.length} 项资料任务。`;
    if (discovery.search_tasks.some(task=>task.generation_origin!=='llm')) $('review-search-report').textContent += ' 模型规划不完整的部分已使用课程需求补充检索，仍需核对。';
  }
  const sources = $('review-sources'); sources.replaceChildren();
  draft.sources.forEach((source, index) => {
    const row = node('div', '', 'source-item');
    const link = node('a', `${index + 1}. ${source.title || source.url}`);
    link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    row.append(link, node('p', `${source.provider ? source.provider + ' · ' : ''}${source.description || '无摘要'}`)); sources.append(row);
  });
  renderSidebar(); window.scrollTo(0, 0);
}

function fillProfile(id) {
  const profile = state.profiles.find(p => p.id === id);
  state.editingId = profile?.id || null;
  $('profile-name').value = profile?.name || '';
  $('profile-url').value = profile?.base_url || '';
  $('profile-chat').value = profile?.chat_model || '';
  $('profile-key').value = '';
  $('profile-clear-key').checked=false;
  $('profile-key').placeholder = profile?.has_key ? '留空保留旧密钥；更换地址需重新填写' : '请输入 API 密钥';
  $('profile-delete').disabled = !profile;
}

function renderProfiles(data) {
  state.profiles = data.profiles;
  state.selectedId = data.selected_id;
  state.searchProfiles = data.search_profiles;
  fillSearchProfile();
  const select = $('profile-select'); select.replaceChildren();
  if (data.env_available) {
    const option = node('option', '环境变量配置'); option.value = 'env'; select.append(option);
  }
  data.profiles.forEach(profile => {
    const suffix = profile.key_usable ? '' : ' · 需重填密钥';
    const option = node('option', `${profile.name} · ${profile.chat_model}${suffix}`);
    option.value = profile.id; select.append(option);
  });
  select.value = data.selected_id || select.options[0]?.value || '';
  fillProfile(select.value);
  $('profile-test').disabled = !data.selected_id;
  $('profile-use').disabled = !select.options.length;
  const active = data.profiles.find(p => p.id === data.selected_id);
  $('profile-status').textContent = active?.key_usable === false
    ? '当前配置的旧密钥无法在本机解密。请重新输入密钥并保存，再测试连接。'
    : data.model_ready ? '模型已选用。建议先测试连接。' : '添加或选用模型后即可创建课程。';
}

function renderMarkdown(target, value) {
  target.replaceChildren();
  const lines = value.split('\n'); let code = null, list = null;
  const flush = () => { list = null; };
  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      flush();
      if (code) { target.append(code); code = null; }
      else code = node('pre');
      continue;
    }
    if (code) { code.textContent += line + '\n'; continue; }
    if (!line.trim()) { flush(); continue; }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) { flush(); target.append(node(heading[1].length <= 2 ? 'h2' : 'h3', heading[2])); continue; }
    const bullet = line.match(/^\s*(?:[-*]|\d+[.)])\s+(.+)$/);
    if (bullet) {
      if (!list) { list = node('ul'); target.append(list); }
      list.append(node('li', bullet[1])); continue;
    }
    flush(); target.append(node('p', line));
  }
  if (code) target.append(code);
}

function renderOutline(data) {
  const list = $('section-list'); list.replaceChildren();
  $('outline-count').textContent = `${data.course.sections.length} 节`;
  data.course.sections.forEach(section => {
    const button = node('button', section.title, 'outline-item'); button.type = 'button';
    button.prepend(node('span', `第 ${section.ordinal} 节 · ${data.mastery.sections[section.ordinal - 1].label}`));
    button.disabled = section.ordinal > data.course.current_ordinal;
    if (section.ordinal === data.section.ordinal) button.classList.add('active');
    button.addEventListener('click', () => openCourse(data.course.id, section.ordinal));
    list.append(button);
  });
}

function renderConversation(turns) {
  const box = $('conversation'); box.replaceChildren();
  const context={courseId:state.courseId,ordinal:state.data.section.ordinal};
  // The first assistant turn is the saved lesson already shown above.
  turns.slice(1).forEach((turn,index) => {
    const item = node('div', '', `conversation-turn ${turn.role}`);
    item.append(node('strong', turn.role === 'user' ? '你的问题' : 'AI 教师'));
    if(turn.role==='assistant'){
      const content=node('div');MindOSTeaching.render(content,turn.blocks?.length?turn.blocks:MindOSTeaching.fromText(turn.content),{action:turn.teaching_action,onFeedback:feedback=>respondToTeaching({...feedback,...context,referenceTurn:index+1})});item.append(content);
    }else item.append(node('p',turn.content));
    box.append(item);
  });
}

function renderQuiz(data) {
  const history = $('quiz-history'); history.replaceChildren();
  const completed = data.quizzes.filter(quiz => quiz.submitted_at);
  $('quiz-count').textContent = `已测 ${completed.length} 次`;
  completed.forEach((quiz, index) => {
    const details = node('details', '', 'history-item');
    details.append(node('summary', `第 ${index + 1} 次小测 · ${quiz.score}/${quiz.questions.length} 题正确`));
    quiz.questions.forEach((question, qIndex) => {
      const result = quiz.results[qIndex];
      const wrap = node('div', '', 'quiz-result');
      if (quiz.user_answers[qIndex] !== result.answer) wrap.classList.add('needs');
      wrap.append(node('h3', `${qIndex + 1}. ${question.prompt}`));
      wrap.append(node('p', `你的选择：${quiz.user_answers[qIndex].toUpperCase()}　正确选择：${result.answer.toUpperCase()}`));
      wrap.append(node('p', result.explanation));
      details.append(wrap);
    });
    history.append(details);
  });
  const active = data.quizzes.find(quiz => !quiz.submitted_at);
  const box = $('quiz-active'); box.replaceChildren();
  $('quiz-new').textContent = completed.length ? '继续测试本节掌握度' : '生成本节小测';
  $('quiz-new').hidden = Boolean(active);
  if (!active) return;
  const form = node('form'); form.id = 'quiz-form';
  active.questions.forEach((question, index) => {
    const group = node('div', '', 'quiz-question');
    group.append(node('h3', `${index + 1}. ${question.prompt}`));
    Object.entries(question.choices).forEach(([key, text]) => {
      const label = node('label', '', 'option');
      const input = document.createElement('input');
      input.type = 'radio'; input.name = `question-${index}`; input.value = key; input.required = true;
      label.append(input, document.createTextNode(`${key.toUpperCase()}. ${text}`)); group.append(label);
    });
    MindOSLearningLoop.answerInputs(group,index,active,data.course.id);
    form.append(group);
  });
  const submit = node('button', '提交小测并更新掌握记录', 'button primary'); submit.type = 'submit';
  form.append(submit);
  form.addEventListener('submit', event => {
    event.preventDefault();
    const answers = active.questions.map((_, index) => form.querySelector(`input[name="question-${index}"]:checked`)?.value);
    if (answers.some(value => !value)) { showNotice('请完成全部 4 道题后提交'); return; }
    action(submit, '正在保存测试结果…', async () => {
      await api('/api/quizzes/submit', { course_id: data.course.id, quiz_id: active.id, answers,...MindOSLearningLoop.answerMetadata(form,active.questions.length) });
      await openCourse(data.course.id, data.section.ordinal);
    });
  });
  box.append(form);
}

function renderContentHistory(target,history,lesson=false){
 target.replaceChildren();
 for(const version of history){
  const box=node('details','','history-item');box.append(node('summary',`旧版讲解 · 依据第 ${version.revision} 版课程`));
  const content=node('div');const snapshot=version.snapshot;
  let blocks=[];if(lesson){try{blocks=JSON.parse(snapshot.lesson_blocks_json||'[]');}catch(_){}}
  MindOSTeaching.render(content,blocks.length?blocks:MindOSTeaching.fromText(snapshot.lesson||snapshot.content||''));box.append(content);target.append(box);
 }
}

function renderCourse(data) {
  if(!currentResponse(data))return;
  if (state.courseId !== data.course.id) { state.courseMode = 'course'; state.atomDetail = null;state.starGalaxy=null; }
  MindOSUniverse.hideStandalone();MindOSUniverse.navigation('course');
  state.data = data; state.courseId = data.course.id;
  state.courses = state.courses.map(course => course.id === data.course.id
    ? { ...course, current_ordinal: data.course.current_ordinal } : course);
  $('course-management').hidden = true;
  $('welcome').hidden = true; $('course-view').hidden = false; $('review-view').hidden = true;
  $('breadcrumb').textContent = `${data.course.title} / 第 ${data.section.ordinal} 节`;
  $('course-title').textContent = data.course.title;
  $('course-goal').textContent = data.course.goal || '从基础开始，循序渐进地学习';
  $('course-counter').textContent = `· 已到第 ${data.course.current_ordinal} 节`;
  $('course-rate').textContent = data.mastery.overall_rate === null ? '未测试' : `${data.mastery.overall_rate}%`;
  $('course-coverage').textContent = `已测小节 ${data.mastery.coverage} · 仅依据当前小测`;
  $('section-number').textContent = `第 ${data.section.ordinal} 节 / 共 ${data.course.sections.length} 节`;
  $('section-title').textContent = data.section.title;
  $('section-objective').textContent = data.section.objective;
  $('section-mastery').textContent = data.mastery.sections[data.section.ordinal - 1].label;
  $('lesson-generate').hidden = Boolean(data.section.lesson) && !data.section.lesson_stale;
  $('lesson-generate').textContent=data.section.lesson_stale?'按更新后的目标和资料重新生成':'生成本节详细讲解';
  $('lesson-version-note').textContent=data.section.lesson_stale?'课程目标、难度或资料已更新。这份讲解基于旧版；重新生成会保留历史记录。':'';
  renderContentHistory($('lesson-history'),data.lesson_history||[],true);
  $('ask-area').hidden = !data.section.lesson;
  $('quiz-card').hidden = !data.section.lesson;
  if (data.section.lesson) MindOSTeaching.render($('lesson-content'),data.section.lesson_blocks?.length?data.section.lesson_blocks:MindOSTeaching.fromText(data.section.lesson),{action:data.section.teaching_action,onFeedback:feedback=>respondToTeaching({...feedback,courseId:data.course.id,ordinal:data.section.ordinal,referenceTurn:0})});
  else $('lesson-content').textContent = '本节讲解尚未生成。点击下方按钮，AI 会从基础开始讲解。';
  renderConversation(data.turns); renderQuiz(data); renderOutline(data); renderSidebar(); renderKnowledge(data);
  const preferences=data.learning_state?.preferences||{};
  $('teaching-math-level').value=preferences.math_level||'unknown';$('teaching-style').value=preferences.preferred_style?.[0]||'';
  const isCurrent = data.section.ordinal === data.course.current_ordinal;
  const last = data.course.current_ordinal === data.course.sections.length;
  $('next-section').hidden = !isCurrent || last;
  $('next-section').disabled = !data.section.lesson;
  $('next-hint').textContent = !isCurrent ? '你正在回看旧小节。点击学习路线中的当前小节继续。'
    : last ? '这门课程的小节已全部开放，你仍可以回看和继续复测。'
    : data.section.lesson ? '准备好了再由你选择进入下一节；系统不会自动跳转。'
    : '先学习当前小节，再决定是否进入下一节。';
  MindOSUniverse.renderCourse(data);
  MindOSLearningLoop.render(data);
  MindOSCourseFinal.render(data);
}

function respondToTeaching({kind,question,button,referenceTurn,selfExplanation,checkQuestion,courseId=state.courseId,ordinal=state.data?.section.ordinal}){
 const cid=courseId;
 const candidates=(state.data?.knowledge.atoms||[]).filter(a=>a.section===ordinal&&a.quality_status!=='deprecated');
 const named=candidates.filter(a=>checkQuestion?.includes(a.title));
 const target=named.length===1?named[0]:candidates.length===1?candidates[0]:null;
 if(state.courseId!==cid||state.data?.section.ordinal!==ordinal)return;
 action(button,'正在换一种讲法…',async()=>{
  const data=await api('/api/sections/ask',{course_id:cid,ordinal,question,feedback:kind,reference_turn:referenceTurn});
  if(state.courseId===cid&&state.data?.section.ordinal===ordinal)renderCourse(data);
  if(selfExplanation&&target&&state.courseId===cid){
   try{await api(`/api/courses/${encodeURIComponent(cid)}/loop/self-explanation`,{atom_id:target.id,answer:selfExplanation});
    if(state.courseId===cid&&state.data?.section.ordinal===ordinal)renderCourse(await api('/api/course?'+new URLSearchParams({course_id:cid,ordinal})));
   }catch(_){/* Candidate analysis must not undo the saved explanation. */}
  }
 });
}

document.addEventListener('DOMContentLoaded',()=>{
 $('teaching-preferences-save').addEventListener('click',event=>{
  const cid=state.courseId,math=$('teaching-math-level').value,style=$('teaching-style').value;
  action(event.currentTarget,'正在保存讲解偏好…',async()=>{
   const response=await fetch(`/api/courses/${cid}/teaching-preferences`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({math_level:math,preferred_style:style?[style]:[]})});
   const result=await response.json();if(!response.ok)throw new Error(result.error);
   if(state.courseId===cid)state.data.learning_state.preferences=result.preferences;
  });
 });
});

async function openCourse(id, ordinal,view='learn') {
  state.courseView=view;
  invalidateNavigation();
  const version=navigationVersion;
  state.page='loading';state.data=null;state.courseId=null;$('course-view').hidden=true;
  try {
    const query = new URLSearchParams({ course_id: id });
    if (ordinal) query.set('ordinal', String(ordinal));
    const data=await api(`/api/course?${query}`);
    if(version!==navigationVersion)return;
    const returning=await api(`/api/courses/${encodeURIComponent(id)}/loop/enter`,{return_context:{section_ordinal:data.section.ordinal,view,scroll_y:0}});
    if(version!==navigationVersion)return;
    if(returning?.status==='pending'){data.knowledge.learning_loop=data.knowledge.learning_loop||{};data.knowledge.learning_loop.returning_session=returning;}
    renderCourse(data);
  } catch (error) { if(version===navigationVersion)showNotice(error.message); }
}

async function bootstrap() {
  try {
    const data = await api('/api/bootstrap');
    state.courses = data.courses; state.drafts = data.drafts;
    renderProfiles(data); renderSidebar();
    if (!data.model_ready) {
      $('settings').hidden = false;
      showNotice('创建课程审查稿需要先配置 AI 模型；默认资料检索无需额外密钥。');
    }
    await MindOSUniverse.showDashboard();
  } catch (error) { showNotice(error.message); }
}

$('home-link').addEventListener('click', event => { event.preventDefault(); MindOSUniverse.showDashboard(); });
$('new-course-side').addEventListener('click', () => { showWelcome(); $('course-title-input').focus(); });
$('settings-toggle').addEventListener('click', () => { $('settings').hidden = !$('settings').hidden; });
$('settings-close').addEventListener('click', () => { $('settings').hidden = true; });
$('profile-select').addEventListener('change', () => fillProfile($('profile-select').value));
$('profile-new').addEventListener('click', () => fillProfile(null));
$('profile-form').addEventListener('submit', event => {
  event.preventDefault();
  action($('profile-form').querySelector('button[type="submit"]'), '正在保存模型配置…', async () => {
    const result = await api('/api/models/save', {
      id: state.editingId, name: $('profile-name').value, base_url: $('profile-url').value,
      chat_model: $('profile-chat').value, clear_key:$('profile-clear-key').checked, api_key: $('profile-key').value,
    });
    renderProfiles(result); showNotice('模型配置已保存，请测试连接。', true);
  });
});
$('profile-use').addEventListener('click', () => action($('profile-use'), '正在切换模型…', async () => {
  renderProfiles(await api('/api/models/select', { id: $('profile-select').value }));
}));
$('profile-test').addEventListener('click', () => action($('profile-test'), '正在测试模型连接…', async () => {
  await api('/api/models/test', {}); $('profile-status').textContent = '连接成功，可以开始创建课程。';
}));
$('profile-delete').addEventListener('click', () => action($('profile-delete'), '正在删除配置…', async () => {
  renderProfiles(await api('/api/models/delete', { id: state.editingId }));
}));
$('search-provider').addEventListener('change', fillSearchProfile);
$('search-clear').addEventListener('click', () => action($('search-clear'), '正在清除密钥…', async () => {
  renderProfiles(await api('/api/search/save', { provider: $('search-provider').value, clear: true }));
}));
$('search-form').addEventListener('submit', event => {
  event.preventDefault();
  action($('search-form').querySelector('button'), '正在保存网页搜索配置…', async () => {
    renderProfiles(await api('/api/search/save', { provider: $('search-provider').value,
      api_url: $('search-url').value, api_key: $('search-key').value }));
  });
});
$('course-form').addEventListener('submit', event => {
  event.preventDefault();
  action($('course-create'), '正在解析资料并拟定课程方向…', async () => {
    const result = await api('/api/courses/draft', {
      ...(typeof MindOSGrowth!=='undefined'?MindOSGrowth.creationContext():{}),
      title: $('course-title-input').value, goal: $('course-goal-input').value,
      description:$('course-description').value, cover:$('course-cover').value, level:$('course-difficulty').value,
      tags:$('course-tags').value.split(/[、,，]/).map(s=>s.trim()).filter(Boolean),
      search_mode: $('course-search-mode').value, learner_level:$('course-level').value,
      source_policy:document.querySelector('input[name="source-policy"]:checked').value, uploads:await prepareCourseUploads(),
    });
    state.drafts = (await api('/api/bootstrap')).drafts;
    renderReview(result.draft);
  });
});
$('review-form').addEventListener('submit', event => {
  event.preventDefault(); const draft = state.draft;
  action($('review-revise'), '正在按你的修改意见重新搜索并调整方向…', async () => {
    const result = await api('/api/courses/draft', {
      ...(typeof MindOSGrowth!=='undefined'?MindOSGrowth.creationContext():{}),
      draft_id: draft.id, revision: draft.revision,
      title: $('review-title-input').value, goal: $('review-goal-input').value,
      feedback: $('review-feedback').value, search_mode: $('review-search-mode').value,
      source_policy:draft.source_policy,learner_level:draft.learner_level,
    });
    state.drafts = (await api('/api/bootstrap')).drafts;
    renderReview(result.draft);
  });
});
$('review-confirm').addEventListener('click', () => {
  const draft = state.draft;
  if ($('review-title-input').value.trim() !== draft.title ||
      $('review-goal-input').value.trim() !== draft.goal || $('review-feedback').value.trim() ||
      $('review-search-mode').value !==
        draftSearchMode(draft)) {
    showNotice('还有未应用的修改，请先点“按修改意见重新调研”。'); return;
  }
  action($('review-confirm'), '正在保存你确认的课程…', async () => {
    const result = await api('/api/courses/confirm', { draft_id: draft.id, revision: draft.revision });
    if(typeof MindOSGrowth!=='undefined')await MindOSGrowth.courseCreated(result.course.course.id);
    const latest = await api('/api/bootstrap');
    state.courses = latest.courses; state.drafts = latest.drafts;
    renderCourse(result.course);
  });
});
$('review-back').addEventListener('click', showWelcome);
$('lesson-generate').addEventListener('click', () => {
  const data = state.data;
  action($('lesson-generate'), 'AI 正在深入讲解这一节，请稍候…', async () => {
    renderCourse(await api('/api/sections/lesson', { course_id: data.course.id, ordinal: data.section.ordinal,regenerate:Boolean(data.section.lesson_stale) }));
  });
});
$('ask-form').addEventListener('submit', event => {
  event.preventDefault(); const data = state.data; const question = $('ask-input').value.trim();
  if (!question) return;
  action($('ask-form').querySelector('button'), 'AI 正在回答你的问题…', async () => {
    renderCourse(await api('/api/sections/ask', { course_id: data.course.id,
      ordinal: data.section.ordinal, question }));
    $('ask-input').value = '';
  });
});
$('quiz-new').addEventListener('click', () => {
  const data = state.data;
  action($('quiz-new'), '正在生成新的独立小测…', async () => {
    renderCourse(await api('/api/sections/quiz', { course_id: data.course.id, ordinal: data.section.ordinal }));
  });
});
$('next-section').addEventListener('click', () => {
  const data = state.data;
  action($('next-section'), '正在进入下一小节…', async () => {
    renderCourse(await api('/api/sections/advance', { course_id: data.course.id,
      expected_ordinal: data.course.current_ordinal }));
  });
});
document.addEventListener('DOMContentLoaded',bootstrap);

const atomTypes = {concept:'概念', mechanism:'机制', operation:'操作', relation:'关系', reason:'原因', rule:'规则', skill:'技能'};
const relationTypes = {implements:'实现', extends:'扩展', prerequisite:'前置', part_of:'组成', related:'相关', causes:'因果', similar:'相似', contrasts:'对比', applied_in:'应用'};
const depthLabels = ['','认识','理解','推理','应用','创造'];

function setCourseMode(mode) {
  state.courseMode=mode;
  MindOSUniverse.viewCourse(mode==='map'?'stars':'learn');
}

function atomButton(atom, text) {
  const button = node('button', text || `${atom.title} · ${atom.status}`, 'atom-chip'); button.type = 'button';
  button.addEventListener('click', () => {
    if (!atom.unlocked) { showNotice('这个知识点属于未来小节，请先在章节讲解模式中主动进入对应小节。'); return; }
    setCourseMode('map'); openAtom(atom.id);
  });
  return button;
}

function renderKnowledge(data) {
  refreshProduction(data.course.id);
  const knowledge = data.knowledge;

  $('graph-build').hidden = knowledge.ready && knowledge.structure_complete;
  $('graph-build').textContent=knowledge.ready?'补全课程索引':'生成课程索引';
  $('diagnostic-new').disabled = !knowledge.ready || !knowledge.atoms.some(a=>a.section===1);
  $('knowledge-progress').textContent = knowledge.ready
    ? `已审查知识 ${knowledge.reviewed_count||0} 个 · 待核对索引 ${knowledge.index_count||0} 个 · 阅读记录 ${knowledge.read_count}/${knowledge.total} 个知识点 · 已测 ${knowledge.tested_count}/${knowledge.total} · 原子近期平均正确率 ${knowledge.overall_rate === null ? '未测' : knowledge.overall_rate + '%'}（仅统计已测知识点，不代表整门课程已掌握）`
    : '可生成这门课程的知识地图，把章节中的知识点连起来；也可以直接开始章节讲解。';
  $('section-read').hidden = !data.section.lesson || !knowledge.ready || !knowledge.atoms.some(a=>a.section===data.section.ordinal);
  const chips = $('section-atoms'); chips.replaceChildren();
  knowledge.atoms.filter(a => a.section === data.section.ordinal).forEach(a => chips.append(atomButton(a)));
  const grouped = $('knowledge-sections'); grouped.replaceChildren();
  if (knowledge.ready) data.course.sections.forEach(section => {
    const box = node('div'); box.append(node('h3', `第 ${section.ordinal} 节 · ${section.title}`));
    const list = node('div', '', 'atom-chips');
    knowledge.atoms.filter(a => a.section === section.ordinal).forEach(a => list.append(atomButton(a,
      `${a.title} · ${a.read ? '已读' : '未记录阅读'} · ${a.rate === null ? '未测' : a.rate + '%'}${a.unlocked ? '' : ' · 待进入'}`)));
    box.append(list); grouped.append(box);
  });
  drawKnowledgeMap(knowledge);
  const queue = $('learning-queue'); queue.replaceChildren();
  if (!knowledge.ready) queue.append(node('p', '生成知识地图后，才能按知识点给出建议。', 'muted'));
  else if (!knowledge.queue.length) queue.append(node('p', '当前没有待处理的建议，可以回看章节或选择知识点继续测试。', 'muted'));
  knowledge.queue.forEach(item => {
    const a = knowledge.atoms.find(atom => atom.id === item.atom_id);
    const row = node('div', '', 'queue-item'); row.append(atomButton(a), node('p', item.reason, 'muted')); queue.append(row);
  });
  renderKnowledgeTests($('diagnostic-tests'), knowledge.diagnostics || [], async () => {
    renderCourse(await api(`/api/course?course_id=${encodeURIComponent(data.course.id)}`));
  });
  if (state.atomDetail && knowledge.atoms.some(a => a.id === state.atomDetail.atom.id)) renderAtom(state.atomDetail);
  else $('atom-panel').hidden = true;
}

function drawKnowledgeMap(knowledge) {MindOSUniverse.renderStarMap(knowledge);}

async function openAtom(id) {
  invalidateNavigation();
  const version=navigationVersion;
  try {
    const courseId = state.data.course.id;
    const result = await api(`/api/atom?${new URLSearchParams({course_id:courseId,atom_id:id})}`);
    const context = await api(`/api/courses/${encodeURIComponent(courseId)}/learning-state?${new URLSearchParams({ordinal:result.atom.section,atom_id:id})}`);
    result.learning_state = context.learning_state;
    if (state.data?.course.id !== courseId) return;
    state.atomMode = result.content.quick ? 'quick' : result.content.deep ? 'deep' : 'quick';
    renderAtom(result); $('atom-panel').scrollIntoView({behavior:'smooth',block:'start'});
    refreshProduction(courseId);
  } catch(error) { if(version===navigationVersion)showNotice(error.message); }
}

function renderAtom(detail) {
  if(!currentResponse(detail))return;
  state.atomDetail = detail; const atom=detail.atom;
  renderSourceReferences($('atom-sources'), atom.source_reference || []);
  const sourceIds=new Set((atom.source_reference||[]).map(r=>r.document_id));
  (state.data.course.source_conflicts || []).filter(c=>sourceIds.has(c.source_a)||sourceIds.has(c.source_b)||c.content.topic===atom.title).forEach(c=>$('atom-sources').append(node('p',`${c.confirmed?'用户已确认教学表达':'外部资料存在不同表述/事实冲突'}：${c.teaching_expression}。原定义与引用保留供追溯，确认不代表事实认证。`)));
  const current=state.data.knowledge.atoms.find(a=>a.id===atom.id);
  $('atom-panel').hidden=false; $('atom-title').textContent=atom.title;
  $('atom-meta').textContent=`第 ${atom.section} 节 · ${atomTypes[atom.type]} · 要求深度：${depthLabels[atom.depth]}`;
  if(Object.values(detail.content_metadata||{}).some(m=>m.stale))$('atom-meta').textContent+=' · 讲解依据已更新，可重新生成；历史记录保留';
  $('atom-summary').textContent=atom.summary; $('atom-why').textContent=`为什么需要：${atom.why}`;
  MindOSLearningLoop.stateDetail(state.courseId,atom.id);
  window.MindOSPersonal?.atom(state.courseId,atom.id);
  $('atom-state').textContent=current ? `${MindOSLearningLoop.labels[current.knowledge_state?.state]||current.status} · ${current.evidence_count} 道已提交题目的记录` : '未测';
  const relations=$('atom-relations'); relations.replaceChildren();
  state.data.knowledge.edges.filter(e=>e.from===atom.id||e.to===atom.id).forEach(e=>{
    const other=state.data.knowledge.atoms.find(a=>a.id===(e.from===atom.id?e.to:e.from));
    relations.append(atomButton(other, `${relationTypes[e.type]}：${e.from===atom.id?'→':'←'} ${other.title}`));
  });
  MindOSTeaching.render($('atom-content'),MindOSTeaching.fromText(detail.content[state.atomMode] || '可直接回到章节继续学习；需要复习这个知识点时，再选择快速复习或深入理解。'));
  renderContentHistory($('atom-history'),detail.content_history?.[state.atomMode]||[]);
  for(const mode of ['quick','deep'])$('atom-'+mode).textContent=(detail.content_metadata?.[mode]?.stale?'重新生成':'')+(mode==='quick'?'快速复习':'深入理解');
  const conversation=$('atom-conversation'); conversation.replaceChildren();
  detail.turns.forEach(turn=>{const el=node('div','',`conversation-turn ${turn.role}`); el.append(node('strong',turn.role==='user'?'你的问题':'AI 教师'),node('p',turn.content));conversation.append(el);});
  renderKnowledgeTests($('atom-tests'), detail.quizzes, async()=>{
    const id=atom.id; const latest=await api(`/api/course?course_id=${encodeURIComponent(state.data.course.id)}`);
    state.atomDetail=null; renderCourse(latest); await openAtom(id);
  });
}

function renderKnowledgeTests(target, tests, refresh) {
  target.replaceChildren();
  tests.filter(t=>t.submitted_at).forEach(test=>{
    const details=node('details','', 'quiz-result'); details.append(node('summary',`测试 ${test.score}/${test.questions.length} · ${test.submitted_at.slice(0,10)}`));
    test.questions.forEach((q,index)=>{
      const result=test.results[index]; details.append(node('p',`${index+1}. ${q.prompt} · ${test.user_answers[index]===result.answer?'答对':'答错'} · 正确选项 ${result.answer.toUpperCase()}：${result.explanation}`));
    }); target.append(details);
  });
  const active=tests.find(t=>!t.submitted_at); if(!active)return;
  const form=node('form');
  active.questions.forEach((q,index)=>{
    const group=node('fieldset','', 'quiz-question'); group.append(node('legend',`${index+1}. ${q.prompt}`));
    Object.entries(q.choices).forEach(([key,text])=>{const label=node('label','', 'option'); const input=document.createElement('input');
      input.type='radio'; input.name=`answer-${index}`; input.value=key; input.required=true; label.append(input,document.createTextNode(`${key.toUpperCase()}. ${text}`));group.append(label);});
    MindOSLearningLoop.answerInputs(group,index,active,state.courseId);form.append(group);
  });
  const button=node('button','提交测试，保存证据','button primary');button.type='submit';form.append(button);
  form.addEventListener('submit',event=>{event.preventDefault();const answers=active.questions.map((_,i)=>form.querySelector(`input[name="answer-${i}"]:checked`)?.value);
    if(answers.some(a=>!a)){showNotice('请完成全部题目。');return;}
    action(button,'正在保存测试证据…',async()=>{await api('/api/quizzes/submit',{course_id:state.data.course.id,quiz_id:active.id,answers,...MindOSLearningLoop.answerMetadata(form,active.questions.length)});await refresh();});
  });target.append(form);
}

$('mode-course').addEventListener('click',()=>setCourseMode('course'));
$('mode-map').addEventListener('click',()=>setCourseMode('map'));
$('graph-build').addEventListener('click',()=>action($('graph-build'),'正在拆分课程知识点与关系…',async()=>{renderCourse(await api('/api/knowledge/build',{course_id:state.data.course.id}));}));
$('section-read').addEventListener('click',()=>action($('section-read'),'正在记录本节阅读…',async()=>{renderCourse(await api('/api/sections/read',{course_id:state.data.course.id,ordinal:state.data.section.ordinal}));}));
$('diagnostic-new').addEventListener('click',()=>action($('diagnostic-new'),'正在生成基础摸底题…',async()=>{renderCourse(await api('/api/knowledge/diagnostic',{course_id:state.data.course.id}));}));
for (const mode of ['quick','deep']) $('atom-'+mode).addEventListener('click',()=>action($('atom-'+mode),'正在讲解这个知识点…',async()=>{
  state.atomMode=mode;renderAtom(await api('/api/atoms/lesson',{course_id:state.data.course.id,atom_id:state.atomDetail.atom.id,mode,regenerate:Boolean(state.atomDetail.content_metadata?.[mode]?.stale)}));
}));
$('atom-test').addEventListener('click',()=>action($('atom-test'),'正在生成知识点独立小测…',async()=>{renderAtom(await api('/api/atoms/quiz',{course_id:state.data.course.id,atom_id:state.atomDetail.atom.id}));}));
$('atom-read').addEventListener('click',()=>action($('atom-read'),'正在保存阅读记录…',async()=>{
  await api('/api/atoms/read',{course_id:state.data.course.id,atom_id:state.atomDetail.atom.id});
  renderCourse(await api(`/api/course?course_id=${encodeURIComponent(state.data.course.id)}`));
}));
$('atom-return').addEventListener('click',()=>{setCourseMode('course');openCourse(state.data.course.id,state.atomDetail.atom.section);});
$('atom-ask-form').addEventListener('submit',event=>{event.preventDefault();action($('atom-ask-form').querySelector('button'),'正在回答知识点疑问…',async()=>{
  renderAtom(await api('/api/atoms/ask',{course_id:state.data.course.id,atom_id:state.atomDetail.atom.id,question:$('atom-question').value}));$('atom-question').value='';
});});
