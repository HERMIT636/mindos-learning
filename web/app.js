const ui = {
  courses: document.querySelector('#course-list'),
  breadcrumb: document.querySelector('#breadcrumb'),
  modelStatus: document.querySelector('#model-status'),
  changeMode: document.querySelector('#change-mode'),
  modeGate: document.querySelector('#mode-gate'),
  chooseMaterials: document.querySelector('#choose-materials'),
  chooseAi: document.querySelector('#choose-ai'),
  modeHelp: document.querySelector('#mode-help'),
  coursePicker: document.querySelector('#course-picker'),
  courseSelect: document.querySelector('#course-select'),
  courseConfirm: document.querySelector('#course-confirm'),
  courseHero: document.querySelector('#course-hero'),
  flowSteps: document.querySelector('#flow-steps'),
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
  diagnosticFeedback: document.querySelector('#diagnostic-feedback'),
  pathPanel: document.querySelector('#path-panel'),
  pathSummary: document.querySelector('#path-summary'),
  pathList: document.querySelector('#path-list'),
  metrics: document.querySelector('#metrics'),
  learningColumns: document.querySelector('#learning-columns'),
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
  learningMode: null, chatReady: false, analysis: null, quiz: null, busy: false };
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
    ui.pathPanel.hidden = true;
    ui.metrics.hidden = true;
    ui.learningColumns.hidden = true;
  }
  ui.modelStatus.textContent = state.learningMode === 'ai' && !gate ? '大模型模式' :
    state.learningMode === 'materials' && !gate ? '资料模式' : '选择学习方式';
}

function renderCourses() {
  ui.courses.replaceChildren();
  state.courses.forEach(course => {
    const button = element('button', `course-button${course.id === state.courseId ? ' active' : ''}`);
    button.type = 'button';
    button.setAttribute('aria-current', course.id === state.courseId ? 'page' : 'false');
    button.append(element('span', 'course-icon', course.id === 'python-foundations' ? 'Py' : '∑'));
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
  ui.askButton.firstChild.textContent = state.learningMode === 'ai' ? '向 AI 提问 / 获取提示 ' : '查看固定课程资料 ';
  ui.askDescription.textContent = independent
    ? '独立作答期间暂停资料助手。切换回辅助练习即可继续查阅。'
    : state.learningMode === 'ai'
      ? 'AI 会结合当前诊断和作答状态，依据课程资料即时回复问题；下方可按需生成练习小测验。'
      : '只展示资料库中的固定讲解和原文片段，不会生成新的解释或题目。查过资料的同题不再计入独立证据。';
  if (independent) ui.askResult.replaceChildren();
}

function renderConceptOptions(preferred = '') {
  const course = state.dashboard.course;
  const chapter = course.chapters.find(item => item.id === ui.chapterSelect.value) || course.chapters[0];
  ui.conceptSelect.replaceChildren(...chapter.concept_ids.map(id => {
    const concept = course.concepts.find(item => item.id === id);
    const option = element('option', '', concept.title);
    option.value = id;
    return option;
  }));
  if (chapter.concept_ids.includes(preferred)) ui.conceptSelect.value = preferred;
}

function renderFlow() {
  const { course, target, diagnostic, plan } = state.dashboard;
  ui.chapterSelect.replaceChildren(...course.chapters.map(item => {
    const option = element('option', '', item.title);
    option.value = item.id;
    return option;
  }));
  ui.chapterSelect.value = target?.chapter_id || course.chapters[0].id;
  renderConceptOptions(target?.concept_id);
  ui.customGoalBox.hidden = state.learningMode !== 'ai';
  const targetConcept = course.concepts.find(item => item.id === target?.concept_id);
  ui.goalCurrent.textContent = target
    ? `当前目标：${targetConcept?.title || target.concept_id}${target.custom_text ? `（你的描述：${target.custom_text}）` : ''}`
    : '请按章节选择目标知识点，再完成两道短诊断题。';
  const pending = diagnostic.find(item => item.result === null);
  const complete = Boolean(target) && !pending;
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
  ui.pathPanel.hidden = !complete;
  ui.metrics.hidden = !complete;
  ui.learningColumns.hidden = !complete;
  if (complete) {
    const weak = plan.filter(item => item.status === '优先补强');
    ui.pathSummary.textContent = weak.length
      ? `短诊断提示先补强：${weak.map(item => item.title).join('、')}。下方按先修顺序安排资料、练习和复测。`
      : '短诊断暂未发现明显薄弱点；仍需独立变式题验证。下方按先修顺序继续。';
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
  ui.nextReason.textContent = recommendation?.reason || '本示例没有新的可独立评分题；可继续查阅资料或选择其他练习。';
  ui.nextButton.disabled = !recommendation;
  const last = state.dashboard.recent[0];
  const readyForVariant = last && Boolean(last.correct);
  ui.nextButton.firstChild.textContent = readyForVariant ? '做独立变式复测 ' : '先做补强练习 ';
  renderProgress();
  renderHistory();
  ui.taskSelect.replaceChildren(...course.tasks.map(task => {
    const option = element('option', '', task.prompt.slice(0, 52));
    option.value = task.id;
    return option;
  }));
  if (!course.tasks.some(task => task.id === state.taskId)) {
    state.taskId = recommendation?.task_id || course.tasks[0]?.id || '';
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
  try {
    state.dashboard = await api(`/api/dashboard?course_id=${encodeURIComponent(courseId)}`);
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
    showEntry();
    if (state.dashboard) renderDashboard();
  } catch (error) { ui.modeHelp.textContent = error.message; }
  finally { state.busy = false; }
}

ui.chooseMaterials.addEventListener('click', () => chooseLearningMode('materials'));
ui.chooseAi.addEventListener('click', () => chooseLearningMode('ai'));
ui.changeMode.addEventListener('click', () => showEntry(true));
ui.courseConfirm.addEventListener('click', () => selectCourse(ui.courseSelect.value));
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
    renderDashboard();
    ui.diagnosticFeedback.textContent = '目标已保存。请完成短诊断。';
  } catch (error) { ui.diagnosticFeedback.textContent = error.message; }
  finally { state.busy = false; }
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
      ui.pathPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
  document.querySelector('#workspace').scrollIntoView({ behavior: 'smooth', block: 'start' });
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
  ui.askResult.textContent = '正在查找课程资料…';
  try {
    const task = currentTask();
    const result = await api('/api/ask', {
      method: 'POST',
      body: JSON.stringify({ course_id: state.courseId, task_id: task?.id,
        concept_id: state.dashboard.target?.concept_id || task?.concept_ids[0], question,
        hint_level: Number(document.querySelector('input[name="hint-level"]:checked')?.value || 1), mode: state.mode }),
    });
    const wrapper = element('div');
    wrapper.append(element('p', '', result.answer));
    wrapper.append(element('small', '', `检索方式：${result.retrieval_mode}${result.notice ? ` · ${result.notice}` : ''}`));
    result.sources.forEach((source, index) => {
      const card = element('div', 'source-card');
      const link = element('a', '', `[${index + 1}] ${source.title} ↗`);
      link.href = source.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      card.append(link, element('small', '', source.provenance));
      const details = element('details');
      details.append(element('summary', '', '查看引用原文'), element('pre', '', source.content));
      card.append(details);
      wrapper.append(card);
    });
    ui.askResult.replaceChildren(wrapper);
  } catch (error) {
    ui.askResult.textContent = error.message;
  } finally {
    state.busy = false;
    ui.askButton.disabled = false;
  }
});

ui.quizGenerate.addEventListener('click', async () => {
  if (state.busy || state.mode === 'independent') return;
  const conceptId = state.dashboard?.target?.concept_id;
  if (!conceptId) { ui.quizContent.textContent = '请先确认目标知识点。'; return; }
  state.busy = true;
  ui.quizGenerate.disabled = true;
  ui.quizContent.textContent = '正在依据课程资料生成练习题…';
  try {
    const quiz = await api('/api/quiz', {
      method: 'POST', body: JSON.stringify({ course_id: state.courseId, concept_id: conceptId }),
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
    const source = element('a', '', `出题依据：${quiz.source_title} ↗`);
    source.href = quiz.source_url; source.target = '_blank'; source.rel = 'noopener noreferrer';
    ui.quizContent.replaceChildren(question, source, submit, feedback);
  } catch (error) { ui.quizContent.textContent = error.message; }
  finally { state.busy = false; ui.quizGenerate.disabled = false; }
});

async function initialize() {
  try {
    const response = await api('/api/courses');
    state.courses = response.courses.sort((left, right) =>
      Number(right.id === 'python-foundations') - Number(left.id === 'python-foundations'));
    state.chatReady = response.chat_ready;
    state.learningMode = response.learning_mode === 'ai' && !response.chat_ready
      ? null : response.learning_mode;
    ui.chooseAi.disabled = !response.chat_ready;
    ui.modeHelp.textContent = response.chat_ready
      ? '服务端已配置大模型。你可以任选一种方式，之后仍可切换。'
      : '服务端尚未配置大模型。可直接进入资料模式；若要使用 AI，请在本机 .env 填写模型配置并重启服务。不要在网页输入密钥。';
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

initialize();
