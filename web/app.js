const ui = {
  courses: document.querySelector('#course-list'),
  breadcrumb: document.querySelector('#breadcrumb'),
  modelStatus: document.querySelector('#model-status'),
  title: document.querySelector('#course-title'),
  audience: document.querySelector('#course-audience'),
  goals: document.querySelector('#course-goals'),
  goalSelect: document.querySelector('#goal-select'),
  goalButton: document.querySelector('#goal-button'),
  goalCurrent: document.querySelector('#goal-current'),
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
  history: document.querySelector('#history-list'),
};

const state = { courses: [], dashboard: null, courseId: '', taskId: '', mode: 'practice', busy: false };
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
  ui.askDescription.textContent = independent
    ? '独立作答期间暂停资料助手。切换回辅助练习即可继续查阅。'
    : '从当前课程的公开资料寻找相关段落，并显示出处。查过资料的同题不再计入独立证据。';
  if (independent) ui.askResult.replaceChildren();
}

function renderFlow() {
  const { course, goal, diagnostic, plan } = state.dashboard;
  ui.goalSelect.replaceChildren(...course.learning_goals.map(item => {
    const option = element('option', '', item);
    option.value = item;
    return option;
  }));
  ui.goalSelect.value = goal || course.learning_goals[0];
  ui.goalCurrent.textContent = goal ? `当前目标：${goal}` : '请选择一个目标，再完成两道短诊断题。';
  const pending = diagnostic.find(item => item.result === null);
  const complete = Boolean(goal) && !pending;
  ui.diagnosticBox.hidden = !goal || !pending;
  if (goal && pending) {
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
}

async function selectCourse(courseId) {
  if (!state.courses.some(course => course.id === courseId)) return;
  state.courseId = courseId;
  state.taskId = '';
  state.mode = 'practice';
  ui.diagnosticFeedback.textContent = '';
  ui.askResult.replaceChildren();
  ui.askInput.value = '';
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

ui.taskSelect.addEventListener('change', () => {
  state.taskId = ui.taskSelect.value;
  ui.askResult.replaceChildren();
  renderTask();
});
ui.goalButton.addEventListener('click', async () => {
  if (state.busy) return;
  state.busy = true;
  try {
    const response = await api('/api/goal', { method: 'POST', body: JSON.stringify({ course_id: state.courseId, goal: ui.goalSelect.value }) });
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
      body: JSON.stringify({ course_id: state.courseId, task_id: task?.id, concept_id: task?.concept_ids[0], question, hint_level: Number(document.querySelector('input[name="hint-level"]:checked')?.value || 1), mode: state.mode }),
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

async function initialize() {
  try {
    const response = await api('/api/courses');
    state.courses = response.courses.sort((left, right) =>
      Number(right.id === 'python-foundations') - Number(left.id === 'python-foundations'));
    ui.modelStatus.textContent = response.chat_ready ? '模型讲解已接通' : '本地课程资料可用';
    const requested = new URL(window.location.href).searchParams.get('course');
    await selectCourse(state.courses.some(course => course.id === requested) ? requested : state.courses[0].id);
  } catch (error) {
    ui.modelStatus.textContent = '本地服务未就绪';
    ui.nextReason.textContent = error.message;
  }
}

initialize();
