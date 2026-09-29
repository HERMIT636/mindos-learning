const ui = {
  courses: document.querySelector('#course-list'),
  breadcrumb: document.querySelector('#breadcrumb'),
  modelStatus: document.querySelector('#model-status'),
  changeMode: document.querySelector('#change-mode'),
  modeGate: document.querySelector('#mode-gate'),
  chooseMaterials: document.querySelector('#choose-materials'),
  chooseAi: document.querySelector('#choose-ai'),
  modeHelp: document.querySelector('#mode-help'),
  profileSelect: document.querySelector('#profile-select'),
  profileUse: document.querySelector('#profile-use'),
  profileTest: document.querySelector('#profile-test'),
  profileForm: document.querySelector('#profile-form'),
  profileName: document.querySelector('#profile-name'),
  profileUrl: document.querySelector('#profile-url'),
  profileChat: document.querySelector('#profile-chat'),
  profileEmbedding: document.querySelector('#profile-embedding'),
  profileKey: document.querySelector('#profile-key'),
  profileClearKey: document.querySelector('#profile-clear-key'),
  profileNew: document.querySelector('#profile-new'),
  profileDelete: document.querySelector('#profile-delete'),
  profileStatus: document.querySelector('#profile-status'),
  coursePicker: document.querySelector('#course-picker'),
  courseSelect: document.querySelector('#course-select'),
  courseConfirm: document.querySelector('#course-confirm'),
  courseHero: document.querySelector('#course-hero'),
  flowSteps: document.querySelector('#flow-steps'),
  stageTarget: document.querySelector('#stage-target'),
  stageDiagnostic: document.querySelector('#stage-diagnostic'),
  stageExplain: document.querySelector('#stage-explain'),
  stagePractice: document.querySelector('#stage-practice'),
  stageStatus: document.querySelector('#stage-status'),
  diagnosticComplete: document.querySelector('#diagnostic-complete'),
  lessonPanel: document.querySelector('#lesson-panel'),
  lessonTitle: document.querySelector('#lesson-title'),
  lessonContext: document.querySelector('#lesson-context'),
  lessonResult: document.querySelector('#lesson-result'),
  lessonRefresh: document.querySelector('#lesson-refresh'),
  lessonPosition: document.querySelector('#lesson-position'),
  lessonPrev: document.querySelector('#lesson-prev'),
  lessonNext: document.querySelector('#lesson-next'),
  goPractice: document.querySelector('#go-practice'),
  goStatus: document.querySelector('#go-status'),
  backExplain: document.querySelector('#back-explain'),
  setup: document.querySelector('#setup'),
  title: document.querySelector('#course-title'),
  audience: document.querySelector('#course-audience'),
  goals: document.querySelector('#course-goals'),
  chapterSelect: document.querySelector('#chapter-select'),
  conceptSelect: document.querySelector('#concept-select'),
  goalButton: document.querySelector('#goal-button'),
  goalCurrent: document.querySelector('#goal-current'),
  customGoalBox: document.querySelector('#custom-goal-box'),
  customGoal: document.querySelector('#custom-goal'),
  analyzeGoal: document.querySelector('#analyze-goal'),
  goalAnalysis: document.querySelector('#goal-analysis'),
  diagnosticBox: document.querySelector('#diagnostic-box'),
  diagnosticCount: document.querySelector('#diagnostic-count'),
  diagnosticPrompt: document.querySelector('#diagnostic-prompt'),
  diagnosticChoices: document.querySelector('#diagnostic-choices'),
  diagnosticSubmit: document.querySelector('#diagnostic-submit'),
  diagnosticSkip: document.querySelector('#diagnostic-skip'),
  diagnosticFeedback: document.querySelector('#diagnostic-feedback'),
  pathPanel: document.querySelector('#path-panel'),
  pathSummary: document.querySelector('#path-summary'),
  pathList: document.querySelector('#path-list'),
  metrics: document.querySelector('#metrics'),
  learningColumns: document.querySelector('#learning-columns'),
  nextPanel: document.querySelector('#next-panel'),
  workspace: document.querySelector('#workspace'),
  progressPanel: document.querySelector('#progress-panel'),
  askPanel: document.querySelector('#ask-panel'),
  historyPanel: document.querySelector('#history-panel'),
  total: document.querySelector('#metric-total'),
  retested: document.querySelector('#metric-retested'),
  needs: document.querySelector('#metric-needs'),
  evidence: document.querySelector('#metric-evidence'),
  nextReason: document.querySelector('#next-reason'),
  nextButton: document.querySelector('#next-button'),
  taskSelect: document.querySelector('#task-select'),
  practice: document.querySelector('#mode-practice'),
  independent: document.querySelector('#mode-independent'),
  modeNote: document.querySelector('#mode-note'),
  taskKind: document.querySelector('#task-kind'),
  taskConcept: document.querySelector('#task-concept'),
  taskPrompt: document.querySelector('#task-prompt'),
  answerField: document.querySelector('#answer-field'),
  submit: document.querySelector('#submit-button'),
  feedback: document.querySelector('#feedback'),
  progress: document.querySelector('#progress-list'),
  askDescription: document.querySelector('#ask-description'),
  askForm: document.querySelector('#ask-form'),
  askInput: document.querySelector('#ask-input'),
  askButton: document.querySelector('#ask-button'),
  askResult: document.querySelector('#ask-result'),
  aiQuizBox: document.querySelector('#ai-quiz-box'),
  quizGenerate: document.querySelector('#quiz-generate'),
  quizContent: document.querySelector('#quiz-content'),
  history: document.querySelector('#history-list'),
};

const state = { courses: [], dashboard: null, courseId: '', taskId: '', mode: 'practice',
  learningMode: null, chatReady: false, analysis: null, quiz: null, stage: 'target',
  lessonCache: null, lessonLoadingKey: null, lessonConceptId: null, busy: false,
  profiles: [], selectedProfileId: null, editingProfileId: null, envAvailable: false };
const typeNames = { single_choice: '单选题', numeric: '数值题', short_answer: '简答题', code: '代码题' };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: options.body ? { 'Content-Type': 'application/json' } : {},
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试。');
  return data;
}

function fillModelForm(id) {
  const profile = state.profiles.find(item => item.id === id);
  state.editingProfileId = profile?.id || null;
  ui.profileName.value = profile?.name || '';
  ui.profileUrl.value = profile?.base_url || '';
  ui.profileChat.value = profile?.chat_model || '';
  ui.profileEmbedding.value = profile?.embedding_model || '';
  ui.profileKey.value = '';
  ui.profileKey.placeholder = profile?.has_key
    ? '密钥已加密保存；留空表示保持原值' : '输入 API 密钥；本地模型可不填';
  ui.profileClearKey.checked = false;
  ui.profileDelete.disabled = !profile;
}

function renderModelProfiles(data) {
  state.profiles = data.profiles;
  state.selectedProfileId = data.selected_id;
  state.envAvailable = data.env_available;
  const options = [];
  if (data.env_available) {
    const option = element('option', '', '环境变量配置');
    option.value = 'env'; options.push(option);
  }
  data.profiles.forEach(profile => {
    const option = element('option', '', `${profile.name} · ${profile.chat_model}${profile.has_key ? ' · 已设密钥' : ''}${profile.key_usable === false ? ' · 需重填密钥' : ''}`);
    option.value = profile.id; options.push(option);
  });
  ui.profileSelect.replaceChildren(...options);
  ui.profileSelect.value = data.selected_id || options[0]?.value || '';
  ui.profileUse.disabled = !options.length;
  const selected = data.profiles.find(profile => profile.id === data.selected_id);
  state.chatReady = Boolean(data.selected_id && selected?.key_usable !== false);
  ui.profileTest.disabled = !data.selected_id;
  ui.chooseAi.disabled = !state.chatReady;
  fillModelForm(ui.profileSelect.value);
  ui.modeHelp.textContent = selected?.key_usable === false
    ? '已保存的密钥在当前运行环境无法解密。请选中该配置，在下方重新输入 API 密钥并保存，然后测试连接。'
    : state.chatReady
    ? '模型配置已就绪。可以开始 AI 教学；新配置建议先测试连接。'
    : '先在下方添加模型 API 地址和名称。密钥只保存在本机服务端。';
}

function currentTask() {
  return state.dashboard?.course.tasks.find(task => task.id === state.taskId);
}

function showFeedback(message, needs = false) {
  ui.feedback.hidden = false;
  ui.feedback.className = needs ? 'feedback needs' : 'feedback';
  ui.feedback.textContent = message;
}

function showEntry(showGate = false) {
  const gate = showGate || !state.learningMode;
  const active = !gate && Boolean(state.courseId);
  ui.modeGate.hidden = !gate;
  ui.coursePicker.hidden = gate || Boolean(state.courseId);
  ui.courses.hidden = gate;
  ui.changeMode.hidden = gate;
  ui.courseHero.hidden = !active;
  ui.flowSteps.hidden = !active;
  ui.setup.hidden = !active;
  if (!active) {
    [ui.stageTarget, ui.stageDiagnostic, ui.stageExplain, ui.stagePractice, ui.stageStatus]
      .forEach(page => { page.hidden = true; });
  } else {
    renderStages();
  }
  ui.modelStatus.textContent = state.learningMode === 'ai' && !gate ? 'AI 教师已连接' : '等待连接 AI';
}

function organizeStages() {
  ui.stageTarget.append(ui.setup);
  ui.stageDiagnostic.append(ui.diagnosticBox);
  ui.stageExplain.insertBefore(ui.askPanel, ui.stageExplain.querySelector('.stage-actions'));
  ui.stagePractice.insertBefore(ui.workspace, ui.stagePractice.querySelector('.stage-actions'));
  ui.askPanel.append(ui.aiQuizBox);
  ui.stageExplain.insertBefore(ui.lessonPanel.querySelector('.lesson-navigation'),
    ui.stageExplain.querySelector('.stage-actions'));
  ui.stageStatus.append(ui.pathPanel, ui.metrics, ui.progressPanel, ui.nextPanel, ui.historyPanel);
  ui.learningColumns.remove();
}

function renderStages() {
  if (!state.dashboard) return;
  const target = state.dashboard.target;
  const pending = state.dashboard.diagnostic.some(item => item.result === null);
  const complete = Boolean(target) && (state.dashboard.diagnostic_skipped || !pending);
  if (state.stage === 'diagnostic' && !target) state.stage = 'target';
  if (['explain', 'practice', 'status'].includes(state.stage) && !complete) {
    state.stage = target ? 'diagnostic' : 'target';
  }
  const pages = { target: ui.stageTarget, diagnostic: ui.stageDiagnostic,
    explain: ui.stageExplain, practice: ui.stagePractice, status: ui.stageStatus };
  Object.entries(pages).forEach(([name, page]) => { page.hidden = state.stage !== name; });
  ui.setup.hidden = state.stage !== 'target';
  ui.diagnosticBox.hidden = state.stage !== 'diagnostic' || !pending;
  ui.diagnosticComplete.hidden = state.stage !== 'diagnostic' || pending;
  ui.pathPanel.hidden = state.stage !== 'status';
  ui.metrics.hidden = state.stage !== 'status';
  ui.aiQuizBox.hidden = state.stage !== 'explain' || state.learningMode !== 'ai';
  ui.flowSteps.querySelectorAll('button[data-stage]').forEach(button => {
    const name = button.dataset.stage;
    button.disabled = name === 'diagnostic' ? !target :
      ['explain', 'practice', 'status'].includes(name) && !complete;
    button.setAttribute('aria-current', state.stage === name ? 'step' : 'false');
  });
  if (state.stage === 'explain' && complete) {
    renderLessonNavigation();
    loadLesson();
  }
}

function lessonRoute() { return state.dashboard?.plan || []; }

function currentLessonId() {
  const route = lessonRoute();
  if (!route.some(item => item.concept_id === state.lessonConceptId)) {
    state.lessonConceptId = route[0]?.concept_id || null;
  }
  return state.lessonConceptId;
}

function renderLessonNavigation() {
  const route = lessonRoute();
  const index = route.findIndex(item => item.concept_id === currentLessonId());
  ui.lessonPosition.textContent = index < 0 ? '' : `第 ${index + 1} / ${route.length} 讲 · ${route[index].title}`;
  ui.lessonPrev.disabled = index <= 0;
  ui.lessonNext.textContent = index === route.length - 1 ? '完成讲解，去练习' : '下一讲';
}

function moveLesson(direction) {
  const route = lessonRoute();
  const index = route.findIndex(item => item.concept_id === currentLessonId());
  const next = index + direction;
  if (next >= route.length) { showStage('practice'); return; }
  if (next < 0) return;
  state.lessonConceptId = route[next].concept_id;
  ui.askResult.replaceChildren();
  ui.quizContent.replaceChildren();
  state.quiz = null;
  renderLessonNavigation();
  loadLesson();
  ui.lessonPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function showStage(stage) {
  if (stage === 'explain') {
    state.mode = 'practice';
    renderMode();
  }
  state.stage = stage;
  renderStages();
  ui.flowSteps.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function lessonBody(markdown) {
  const body = element('div', 'lesson-body');
  const lines = markdown.split('\n');
  let paragraph = [];
  let list = null;
  let code = null;
  function inline(node, value) {
    const pattern = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https:\/\/[^\s)]+)\)/g;
    let offset = 0;
    for (const match of value.matchAll(pattern)) {
      node.append(document.createTextNode(value.slice(offset, match.index)));
      if (match[1]) node.append(element('strong', '', match[1]));
      else if (match[2]) node.append(element('code', 'inline-code', match[2]));
      else {
        const link = element('a', '', match[3]);
        link.href = match[4]; link.target = '_blank'; link.rel = 'noopener noreferrer';
        node.append(link);
      }
      offset = match.index + match[0].length;
    }
    node.append(document.createTextNode(value.slice(offset)));
  }
  function flushParagraph() {
    if (paragraph.length) {
      const p = element('p');
      inline(p, paragraph.join(' '));
      body.append(p);
    }
    paragraph = [];
  }
  for (const line of lines) {
    if (line.startsWith('```')) {
      flushParagraph(); list = null;
      if (code) { body.append(element('pre', 'lesson-code', code.join('\n'))); code = null; }
      else code = [];
    } else if (code) {
      code.push(line);
    } else if (/^#{1,3} /.test(line)) {
      flushParagraph(); list = null;
      const level = line.match(/^#+/)[0].length;
      const heading = element(level === 1 ? 'h3' : 'h4');
      inline(heading, line.slice(level + 1));
      body.append(heading);
    } else if (/^(?:- |\d+\. )/.test(line)) {
      flushParagraph();
      const ordered = /^\d+\. /.test(line);
      if (!list || list.tagName !== (ordered ? 'OL' : 'UL')) {
        list = element(ordered ? 'ol' : 'ul'); body.append(list);
      }
      const item = element('li');
      inline(item, line.replace(/^(?:- |\d+\. )/, ''));
      list.append(item);
    } else if (!line.trim()) {
      flushParagraph(); list = null;
    } else {
      list = null;
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  if (code) body.append(element('pre', 'lesson-code', code.join('\n')));
  return body;
}

function renderLesson(result) {
  ui.lessonTitle.textContent = result.title;
  ui.lessonContext.textContent = 'AI 按课程目标和当前学习状态组织这一节；有疑问可随时打断，回答会延续本节对话。';
  const wrapper = element('div');
  wrapper.append(lessonBody(result.answer));
  ui.lessonResult.replaceChildren(wrapper);
  ui.askResult.replaceChildren();
  (result.turns || []).forEach(turn => {
    const item = element('div', turn.role === 'user' ? 'tutor-question' : 'tutor-answer');
    item.append(element('strong', '', turn.role === 'user' ? '你问：' : 'AI 回答：'));
    item.append(turn.role === 'user' ? element('p', '', turn.content) : lessonBody(turn.content));
    ui.askResult.append(item);
  });
}

async function loadLesson(force = false) {
  const dashboard = state.dashboard;
  if (!dashboard?.target) return;
  const conceptId = currentLessonId();
  if (!conceptId) return;
  const key = [state.courseId, dashboard.course.version, dashboard.target.concept_id, conceptId,
    state.learningMode, dashboard.valid_evidence_count,
    dashboard.diagnostic.map(item => item.result).join(',')].join('|');
  if (!force && state.lessonCache?.key === key) {
    renderLesson(state.lessonCache.result);
    return;
  }
  if (!force && state.lessonLoadingKey === key) return;
  state.lessonLoadingKey = key;
  ui.lessonResult.textContent = '正在准备当前知识点的讲解…';
  if (force) { ui.quizContent.replaceChildren(); state.quiz = null; }
  ui.lessonRefresh.disabled = true;
  try {
    const result = await api('/api/tutor/start', { method: 'POST', body: JSON.stringify({ course_id: state.courseId, concept_id: conceptId, reset: force }) });
    if (state.courseId !== dashboard.course.id || state.dashboard.target?.concept_id !== dashboard.target.concept_id || currentLessonId() !== conceptId) return;
    state.lessonCache = { key, result };
    renderLesson(result);
  } catch (error) { ui.lessonResult.textContent = error.message; }
  finally { if (state.lessonLoadingKey === key) state.lessonLoadingKey = null;
    ui.lessonRefresh.disabled = false; }
}

function renderCourses() {
  ui.courses.replaceChildren();
  state.courses.forEach(course => {
    const button = element('button', `course-button${course.id === state.courseId ? ' active' : ''}`);
    button.type = 'button';
    button.setAttribute('aria-current', course.id === state.courseId ? 'page' : 'false');
    const courseIcons = { 'machine-learning': 'ML', 'hpc-foundations': 'HPC', 'ascend-c-operators': 'C', 'python-foundations': 'Py', 'linear-algebra': '∑' };
    button.append(element('span', 'course-icon', courseIcons[course.id] || '课'));
    const text = element('span');
    text.append(element('span', 'course-name', course.title.split('：')[0]));
    text.append(element('span', 'course-subtitle', course.title.split('：')[1] || '基础课程'));
    button.append(text);
    button.addEventListener('click', () => selectCourse(course.id));
    ui.courses.append(button);
  });
}

function renderProgress() {
  const rows = state.dashboard.progress;
  ui.progress.replaceChildren();
  rows.forEach(item => {
    const row = element('div', 'progress-item');
    const title = element('div');
    title.append(element('strong', '', item.concept_title));
    title.append(element('small', '', `${item.dimension_label} · ${item.evidence_count} 份独立作答证据${item.diagnostic_result === null ? '' : ` · 短诊断${item.diagnostic_result ? '通过' : '待补强'}`}`));
    row.append(title, element('span', `state-badge ${item.state}`, item.state_label));
    ui.progress.append(row);
  });
  ui.total.textContent = String(rows.length);
  ui.retested.textContent = String(rows.filter(item => item.state === 'retested').length);
  ui.needs.textContent = String(rows.filter(item => ['needs_work', 'recheck'].includes(item.state)).length);
  ui.evidence.textContent = String(state.dashboard.valid_evidence_count);
}

function renderHistory() {
  ui.history.replaceChildren();
  const rows = state.dashboard.recent;
  if (!rows.length) {
    ui.history.append(element('p', 'empty', '尚无作答记录。'));
    return;
  }
  rows.forEach(item => {
    const task = state.dashboard.course.tasks.find(candidate => candidate.id === item.task_id);
    const row = element('div', 'history-row');
    row.append(element('strong', '', task?.prompt || item.task_id));
    const result = item.correct === null ? '待人工审核' : item.correct ? '正确' : '未通过';
    row.append(element('small', '', `${item.mode === 'independent' ? '独立作答' : '辅助练习'} · ${result}${item.counts_for_state ? ' · 已计入状态' : ''}`));
    ui.history.append(row);
  });
}

function renderTask() {
  const task = currentTask();
  if (!task) return;
  const pack = state.dashboard.course;
  ui.taskKind.textContent = typeNames[task.task_type] || '练习';
  ui.taskConcept.textContent = task.concept_ids.map(id => pack.concepts.find(concept => concept.id === id)?.title || id).join(' · ');
  ui.taskPrompt.textContent = task.prompt;
  ui.answerField.replaceChildren();
  if (task.task_type === 'single_choice') {
    const list = element('div', 'choice-list');
    task.choices.forEach(choice => {
      const label = element('label', 'choice');
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'choice';
      input.value = choice.id;
      label.append(input, element('span', '', choice.text));
      list.append(label);
    });
    ui.answerField.append(list);
  } else if (task.task_type === 'numeric') {
    const input = element('input', 'answer-input');
    input.id = 'answer-input';
    input.type = 'text';
    input.inputMode = 'decimal';
    input.placeholder = '输入计算结果';
    input.setAttribute('aria-label', '计算结果');
    ui.answerField.append(input);
  } else {
    const input = element('textarea', `answer-input${task.task_type === 'code' ? ' code-input' : ''}`);
    input.id = 'answer-input';
    input.rows = task.task_type === 'code' ? 5 : 4;
    input.maxLength = 2000;
    input.placeholder = task.task_type === 'code' ? '在这里写下代码。本地原型不会执行它。' : '写下你的解释。';
    input.setAttribute('aria-label', '作答内容');
    ui.answerField.append(input);
  }
  ui.feedback.hidden = true;
}

function renderMode() {
  const independent = state.mode === 'independent';
  ui.practice.classList.toggle('active', !independent);
  ui.independent.classList.toggle('active', independent);
  ui.practice.setAttribute('aria-pressed', String(!independent));
  ui.independent.setAttribute('aria-pressed', String(independent));
  ui.modeNote.textContent = independent
    ? '请独立完成本题。不同题目的正确作答才能形成复测证据；已练习或求助的同题不会计入。'
    : '可以查看资料并试答；练习结果不会计入独立掌握证据。';
  ui.askForm.hidden = independent;
  ui.aiQuizBox.hidden = independent || state.learningMode !== 'ai';
  ui.askButton.firstChild.textContent = '向 AI 追问 ';
  ui.askDescription.textContent = independent
    ? '独立作答期间暂停 AI 追问。返回讲解页后可以继续对话。'
    : '可以随时问不懂的步骤，AI 会接着本节对话解释。';
  if (independent) ui.askResult.replaceChildren();
}

function renderConceptOptions(preferred = '') {
  const course = state.dashboard.course;
  const chapter = course.chapters.find(item => item.id === ui.chapterSelect.value) || course.chapters[0];
  ui.conceptSelect.replaceChildren(...chapter.concept_ids.map((id, index) => {
    const concept = course.concepts.find(item => item.id === id);
    const chapterNumber = course.chapters.indexOf(chapter) + 1;
    const option = element('option', '', `${chapterNumber}.${index + 1} ${concept.title}`);
    option.value = id;
    return option;
  }));
  if (chapter.concept_ids.includes(preferred)) ui.conceptSelect.value = preferred;
}

function renderFlow() {
  const { course, target, diagnostic, plan } = state.dashboard;
  ui.chapterSelect.replaceChildren(...course.chapters.map((item, index) => {
    const option = element('option', '', `第 ${index + 1} 章 · ${item.title}`);
    option.value = item.id;
    return option;
  }));
  ui.chapterSelect.value = target?.chapter_id || course.chapters[0].id;
  renderConceptOptions(target?.concept_id);
  ui.customGoalBox.hidden = state.learningMode !== 'ai';
  const targetConcept = course.concepts.find(item => item.id === target?.concept_id);
  ui.goalCurrent.textContent = target
    ? `当前目标：${targetConcept?.title || target.concept_id}${target.custom_text ? `（你的描述：${target.custom_text}）` : ''}`
    : '请按编号选择想学到的知识点，然后做或跳过学前小测。';
  const pending = diagnostic.find(item => item.result === null);
  const complete = Boolean(target) && (state.dashboard.diagnostic_skipped || !pending);
  ui.diagnosticBox.hidden = !target || !pending;
  if (target && pending) {
    ui.diagnosticCount.textContent = `第 ${diagnostic.length - diagnostic.filter(item => item.result === null).length + 1} / ${diagnostic.length} 题`;
    ui.diagnosticPrompt.textContent = pending.prompt;
    ui.diagnosticChoices.replaceChildren(...pending.choices.map(choice => {
      const label = element('label', 'choice');
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'diagnostic-choice';
      input.value = choice.id;
      label.append(input, element('span', '', choice.text));
      return label;
    }));
  }
  if (complete) {
    const weak = plan.filter(item => item.status === '优先补强');
    ui.pathSummary.textContent = weak.length
      ? `当前证据提示先补强：${weak.map(item => item.title).join('、')}。下方按先修顺序安排资料、练习和复测。`
      : state.dashboard.diagnostic_skipped ? '已跳过学前小测，先从路线第一讲学起；当前还没有诊断结论。' :
        '当前目标仍可通过独立变式题继续验证。下方按先修顺序安排。';
    ui.pathList.replaceChildren(...plan.map((item, index) => {
      const row = element('div', 'path-item');
      row.append(element('strong', '', `${index + 1}. ${item.title}`), element('span', '', item.status));
      row.append(element('p', '', `${item.prerequisites.length ? `先修：${item.prerequisites.join('、')}。` : '本路线的起点。'}${item.reason}`));
      return row;
    }));
  }
}

function renderDashboard() {
  const { course, recommendation } = state.dashboard;
  ui.breadcrumb.textContent = course.title.split('：')[0];
  ui.title.textContent = course.title;
  ui.audience.textContent = `适合：${course.audience}。课程内容尚待教师审核。`;
  ui.goals.replaceChildren(...course.learning_goals.map(goal => element('span', 'hero-tag', goal)));
  renderFlow();
  ui.nextReason.textContent = recommendation?.reason || '当前路线没有新的可独立评分题；可继续查阅资料或选择其他知识点。';
  ui.nextButton.disabled = !recommendation;
  const last = state.dashboard.recent[0];
  const readyForVariant = last && Boolean(last.correct);
  ui.nextButton.firstChild.textContent = readyForVariant ? '做独立变式复测 ' : '先做补强练习 ';
  renderProgress();
  renderHistory();
  const routeConcepts = new Set(state.dashboard.plan.map(item => item.concept_id));
  const availableTasks = state.dashboard.target
    ? course.tasks.filter(task => task.concept_ids.some(id => routeConcepts.has(id)))
    : course.tasks;
  ui.taskSelect.replaceChildren(...availableTasks.map(task => {
    const option = element('option', '', task.prompt.slice(0, 52));
    option.value = task.id;
    return option;
  }));
  if (!availableTasks.some(task => task.id === state.taskId)) {
    state.taskId = recommendation?.task_id || availableTasks[0]?.id || '';
  }
  ui.taskSelect.value = state.taskId;
  renderTask();
  renderMode();
  renderCourses();
  showEntry();
}

async function selectCourse(courseId) {
  if (!state.learningMode || !state.courses.some(course => course.id === courseId)) return;
  state.courseId = courseId;
  state.taskId = '';
  state.mode = 'practice';
  ui.diagnosticFeedback.textContent = '';
  ui.askResult.replaceChildren();
  ui.askInput.value = '';
  ui.customGoal.value = '';
  ui.goalAnalysis.textContent = '';
  ui.quizContent.replaceChildren();
  state.analysis = null;
  state.quiz = null;
  state.lessonCache = null;
  state.lessonConceptId = null;
  try {
    state.dashboard = await api(`/api/dashboard?course_id=${encodeURIComponent(courseId)}`);
    state.stage = !state.dashboard.target ? 'target' :
      !state.dashboard.diagnostic_skipped && state.dashboard.diagnostic.some(item => item.result === null) ? 'diagnostic' : 'explain';
    renderDashboard();
    const url = new URL(window.location.href);
    url.searchParams.set('course', courseId);
    window.history.replaceState({}, '', url);
  } catch (error) {
    showFeedback(error.message, true);
  }
}

async function chooseLearningMode(mode) {
  if (state.busy) return;
  state.busy = true;
  try {
    const result = await api('/api/mode', { method: 'POST', body: JSON.stringify({ mode }) });
    state.learningMode = result.mode;
    state.lessonCache = null;
    showEntry();
    if (state.dashboard) renderDashboard();
  } catch (error) { ui.modeHelp.textContent = error.message; }
  finally { state.busy = false; }
}

ui.chooseAi.addEventListener('click', () => chooseLearningMode('ai'));
ui.changeMode.addEventListener('click', () => showEntry(true));
ui.profileSelect.addEventListener('change', () => fillModelForm(ui.profileSelect.value));
ui.profileNew.addEventListener('click', () => { fillModelForm(null); ui.profileStatus.textContent = '填写新模型配置后保存。'; });
ui.profileForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (state.busy) return;
  state.busy = true;
  ui.profileStatus.textContent = '正在保存模型配置…';
  try {
    const result = await api('/api/models/save', { method: 'POST', body: JSON.stringify({
      id: state.editingProfileId, name: ui.profileName.value, base_url: ui.profileUrl.value,
      chat_model: ui.profileChat.value, embedding_model: ui.profileEmbedding.value,
      api_key: ui.profileKey.value, clear_key: ui.profileClearKey.checked,
    }) });
    renderModelProfiles(result);
    state.lessonCache = null;
    ui.profileStatus.textContent = '已保存并选用。密钥不会回显；可先测试连接，再开始学习。';
  } catch (error) { ui.profileStatus.textContent = error.message; }
  finally { state.busy = false; }
});
ui.profileUse.addEventListener('click', async () => {
  if (state.busy || !ui.profileSelect.value) return;
  state.busy = true;
  try {
    renderModelProfiles(await api('/api/models/select', { method: 'POST',
      body: JSON.stringify({ id: ui.profileSelect.value }) }));
    state.lessonCache = null;
    ui.profileStatus.textContent = '已切换模型。已有对话仍保留；可在讲解页点击“重新讲解本节”。';
  } catch (error) { ui.profileStatus.textContent = error.message; }
  finally { state.busy = false; }
});
ui.profileTest.addEventListener('click', async () => {
  if (state.busy) return;
  state.busy = true;
  ui.profileStatus.textContent = '正在向当前选用的模型发送一条短测试消息…';
  try {
    await api('/api/models/test', { method: 'POST', body: '{}' });
    ui.profileStatus.textContent = '连接成功，模型返回了有效响应。';
  } catch (error) { ui.profileStatus.textContent = error.message; }
  finally { state.busy = false; }
});
ui.profileDelete.addEventListener('click', async () => {
  if (state.busy || !state.editingProfileId) return;
  state.busy = true;
  try {
    renderModelProfiles(await api('/api/models/delete', { method: 'POST',
      body: JSON.stringify({ id: state.editingProfileId }) }));
    if (!state.chatReady) { state.learningMode = null; showEntry(true); }
    ui.profileStatus.textContent = '配置已删除。';
  } catch (error) { ui.profileStatus.textContent = error.message; }
  finally { state.busy = false; }
});
ui.courseConfirm.addEventListener('click', () => selectCourse(ui.courseSelect.value));
ui.flowSteps.querySelectorAll('button[data-stage]').forEach(button => {
  button.addEventListener('click', () => showStage(button.dataset.stage));
});
ui.lessonRefresh.addEventListener('click', () => loadLesson(true));
ui.lessonPrev.addEventListener('click', () => moveLesson(-1));
ui.lessonNext.addEventListener('click', () => moveLesson(1));
ui.goPractice.addEventListener('click', () => showStage('practice'));
ui.goStatus.addEventListener('click', () => showStage('status'));
ui.backExplain.addEventListener('click', () => showStage('explain'));
ui.chapterSelect.addEventListener('change', () => {
  renderConceptOptions();
  state.analysis = null;
  ui.goalAnalysis.textContent = '';
});
ui.conceptSelect.addEventListener('change', () => { state.analysis = null; });
ui.customGoal.addEventListener('input', () => {
  state.analysis = null;
  ui.goalAnalysis.textContent = '';
});
ui.analyzeGoal.addEventListener('click', async () => {
  if (state.busy) return;
  const text = ui.customGoal.value.trim();
  if (text.length < 4) { ui.goalAnalysis.textContent = '请具体描述想达到的目标。'; return; }
  state.busy = true;
  ui.goalAnalysis.textContent = '正在对照课程目录分析…';
  try {
    const result = await api('/api/analyze-goal', {
      method: 'POST', body: JSON.stringify({ course_id: state.courseId, custom_text: text }),
    });
    if (!result.concept_id) {
      state.analysis = null;
      ui.goalAnalysis.textContent = `当前课程尚不覆盖这个目标：${result.rationale}`;
    } else {
      ui.chapterSelect.value = result.chapter_id;
      renderConceptOptions(result.concept_id);
      state.analysis = { text, conceptId: result.concept_id };
      ui.goalAnalysis.textContent = `建议定位到「${ui.conceptSelect.selectedOptions[0]?.textContent}」。${result.rationale}确认后再开始诊断。`;
    }
  } catch (error) { ui.goalAnalysis.textContent = error.message; }
  finally { state.busy = false; }
});

ui.taskSelect.addEventListener('change', () => {
  state.taskId = ui.taskSelect.value;
  ui.askResult.replaceChildren();
  renderTask();
});
ui.goalButton.addEventListener('click', async () => {
  if (state.busy) return;
  const customText = ui.customGoal.value.trim();
  if (customText && (state.learningMode !== 'ai' || state.analysis?.text !== customText ||
      state.analysis?.conceptId !== ui.conceptSelect.value)) {
    ui.goalAnalysis.textContent = '请先让 AI 分析当前自定义目标，再确认它定位的知识点；或清空描述后手动选择。';
    return;
  }
  state.busy = true;
  try {
    const response = await api('/api/target', { method: 'POST', body: JSON.stringify({
      course_id: state.courseId, chapter_id: ui.chapterSelect.value, concept_id: ui.conceptSelect.value,
      custom_text: customText,
    }) });
    state.dashboard = response.dashboard;
    state.lessonConceptId = null;
    renderDashboard();
    ui.diagnosticFeedback.textContent = '目标已保存。可以做学前小测，也可以从零开始讲解。';
    state.lessonCache = null;
    showStage(!state.dashboard.diagnostic_skipped && state.dashboard.diagnostic.some(item => item.result === null) ? 'diagnostic' : 'explain');
  } catch (error) { ui.diagnosticFeedback.textContent = error.message; }
  finally { state.busy = false; }
});
ui.diagnosticSkip.addEventListener('click', async () => {
  if (state.busy) return;
  state.busy = true;
  ui.diagnosticSkip.disabled = true;
  try {
    const response = await api('/api/skip-diagnostics', {
      method: 'POST', body: JSON.stringify({ course_id: state.courseId }),
    });
    state.dashboard = response.dashboard;
    state.lessonConceptId = null;
    state.lessonCache = null;
    renderDashboard();
    showStage('explain');
  } catch (error) { ui.diagnosticFeedback.textContent = error.message; }
  finally { state.busy = false; ui.diagnosticSkip.disabled = false; }
});
ui.diagnosticSubmit.addEventListener('click', async () => {
  if (state.busy) return;
  const task = state.dashboard?.diagnostic.find(item => item.result === null);
  const answer = document.querySelector('input[name="diagnostic-choice"]:checked')?.value;
  if (!task || !answer) { ui.diagnosticFeedback.textContent = '请先选择一个选项。'; return; }
  state.busy = true;
  try {
    const response = await api('/api/diagnose', { method: 'POST', body: JSON.stringify({ course_id: state.courseId, task_id: task.id, answer }) });
    state.dashboard = response.dashboard;
    renderDashboard();
    ui.diagnosticFeedback.textContent = response.result.correct ? '已记录。继续下一题。' : '已记录。稍后会把这个知识点列入补强路线。';
    if (state.dashboard.diagnostic.every(item => item.result !== null)) {
      state.lessonCache = null;
      showStage('explain');
    }
  } catch (error) { ui.diagnosticFeedback.textContent = error.message; }
  finally { state.busy = false; }
});
ui.practice.addEventListener('click', () => { state.mode = 'practice'; renderMode(); });
ui.independent.addEventListener('click', () => { state.mode = 'independent'; renderMode(); });
ui.nextButton.addEventListener('click', () => {
  const recommended = state.dashboard?.recommendation;
  if (!recommended) return;
  state.taskId = recommended.task_id;
  state.mode = state.dashboard.recent[0]?.correct ? 'independent' : 'practice';
  ui.taskSelect.value = state.taskId;
  renderTask();
  renderMode();
  showStage('practice');
});

ui.submit.addEventListener('click', async () => {
  if (state.busy) return;
  const task = currentTask();
  if (!task) return;
  const answer = task.task_type === 'single_choice'
    ? document.querySelector('input[name="choice"]:checked')?.value || ''
    : document.querySelector('#answer-input')?.value || '';
  if (!answer.trim()) { showFeedback('请先填写或选择答案。', true); return; }
  state.busy = true;
  ui.submit.disabled = true;
  try {
    const response = await api('/api/submit', {
      method: 'POST',
      body: JSON.stringify({ course_id: state.courseId, task_id: task.id, answer, mode: state.mode }),
    });
    state.dashboard = response.dashboard;
    renderDashboard();
    showFeedback(response.result.message, response.result.correct === false);
  } catch (error) {
    showFeedback(error.message, true);
  } finally {
    state.busy = false;
    ui.submit.disabled = false;
  }
});

ui.askForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (state.busy || state.mode === 'independent') return;
  const question = ui.askInput.value.trim();
  if (question.length < 2) { ui.askResult.textContent = '请写下更具体的问题。'; return; }
  state.busy = true;
  ui.askButton.disabled = true;
  const pending = element('p', 'panel-intro', 'AI 正在接着本节回答…');
  ui.askResult.append(pending);
  try {
    const result = await api('/api/tutor/ask', {
      method: 'POST',
      body: JSON.stringify({ course_id: state.courseId, concept_id: currentLessonId(), question }),
    });
    pending.remove();
    const asked = element('div', 'tutor-question');
    asked.append(element('strong', '', '你问：'), element('p', '', question));
    const replied = element('div', 'tutor-answer');
    replied.append(element('strong', '', 'AI 回答：'), lessonBody(result.answer));
    ui.askResult.append(asked, replied);
    ui.askInput.value = '';
    state.lessonCache = null;
  } catch (error) {
    pending.textContent = error.message;
  } finally {
    state.busy = false;
    ui.askButton.disabled = false;
  }
});

ui.quizGenerate.addEventListener('click', async () => {
  if (state.busy || state.mode === 'independent') return;
  const conceptId = currentLessonId();
  if (!conceptId) { ui.quizContent.textContent = '请先确认目标知识点。'; return; }
  state.busy = true;
  ui.quizGenerate.disabled = true;
  ui.quizContent.textContent = '正在根据本节讲解生成小测…';
  try {
    const quiz = await api('/api/quiz', {
      method: 'POST', body: JSON.stringify({ course_id: state.courseId, concept_id: conceptId, tutor: true }),
    });
    state.quiz = quiz;
    const question = element('div', 'question-box');
    question.append(element('h3', '', quiz.prompt));
    const choices = element('div', 'choice-list');
    quiz.choices.forEach(choice => {
      const label = element('label', 'choice');
      const input = document.createElement('input');
      input.type = 'radio'; input.name = 'quiz-choice'; input.value = choice.id;
      label.append(input, element('span', '', choice.text));
      choices.append(label);
    });
    question.append(choices);
    const submit = element('button', 'button button-secondary', '提交小测验');
    submit.type = 'button';
    const feedback = element('p', 'panel-intro');
    submit.addEventListener('click', async () => {
      const answer = document.querySelector('input[name="quiz-choice"]:checked')?.value;
      if (!answer) { feedback.textContent = '请先选一个答案。'; return; }
      submit.disabled = true;
      try {
        const result = await api('/api/quiz-answer', { method: 'POST', body: JSON.stringify({
          course_id: state.courseId, quiz_id: quiz.id, answer,
        }) });
        feedback.textContent = `${result.correct ? '本题答对了。' : '本题未答对。'}${result.explanation}（AI 练习题不计入掌握证据。）`;
      } catch (error) { feedback.textContent = error.message; submit.disabled = false; }
    });
    ui.quizContent.replaceChildren(question, submit, feedback);
  } catch (error) { ui.quizContent.textContent = error.message; }
  finally { state.busy = false; ui.quizGenerate.disabled = false; }
});

async function initialize() {
  try {
    const response = await api('/api/courses');
    state.courses = response.courses;
    renderModelProfiles(await api('/api/models'));
    state.learningMode = response.learning_mode === 'ai' && state.chatReady ? 'ai' : null;
    ui.courseSelect.replaceChildren(...state.courses.map(course => {
      const option = element('option', '', course.title);
      option.value = course.id;
      return option;
    }));
    showEntry();
    const requested = new URL(window.location.href).searchParams.get('course');
    if (state.learningMode && state.courses.some(course => course.id === requested)) await selectCourse(requested);
  } catch (error) {
    ui.modelStatus.textContent = '本地服务未就绪';
    ui.modeHelp.textContent = error.message;
  }
}

organizeStages();
initialize();
