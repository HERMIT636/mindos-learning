const $ = id => document.getElementById(id);
const state = { courses: [], profiles: [], selectedId: null, courseId: null, data: null, busy: false, editingId: null };

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
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试');
  return data;
}

async function action(button, message, work) {
  if (state.busy) return;
  state.busy = true;
  if (button) button.disabled = true;
  showNotice(message, true);
  try { await work(); showNotice(''); }
  catch (error) { showNotice(error.message); }
  finally { state.busy = false; if (button) button.disabled = false; }
}

function renderSidebar() {
  const list = $('course-list'); list.replaceChildren();
  state.courses.forEach(course => {
    const button = node('button', course.title, 'course-link');
    button.type = 'button';
    if (course.id === state.courseId) button.classList.add('active');
    const small = node('small', `已到第 ${course.current_ordinal} 节`);
    button.append(small);
    button.addEventListener('click', () => openCourse(course.id));
    list.append(button);
  });
}

function showWelcome() {
  state.courseId = null; state.data = null;
  $('welcome').hidden = false; $('course-view').hidden = true;
  $('breadcrumb').textContent = '我的学习空间';
  renderSidebar();
}

function fillProfile(id) {
  const profile = state.profiles.find(p => p.id === id);
  state.editingId = profile?.id || null;
  $('profile-name').value = profile?.name || '';
  $('profile-url').value = profile?.base_url || '';
  $('profile-chat').value = profile?.chat_model || '';
  $('profile-key').value = '';
  $('profile-key').placeholder = profile?.has_key ? '留空保留旧密钥' : '请输入 API 密钥';
  $('profile-delete').disabled = !profile;
}

function renderProfiles(data) {
  state.profiles = data.profiles;
  state.selectedId = data.selected_id;
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
  // The first assistant turn is the saved lesson already shown above.
  turns.slice(1).forEach(turn => {
    const item = node('div', '', `conversation-turn ${turn.role}`);
    item.append(node('strong', turn.role === 'user' ? '你的问题' : 'AI 教师'));
    item.append(node('p', turn.content));
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
    form.append(group);
  });
  const submit = node('button', '提交小测并更新掌握记录', 'button primary'); submit.type = 'submit';
  form.append(submit);
  form.addEventListener('submit', event => {
    event.preventDefault();
    const answers = active.questions.map((_, index) => form.querySelector(`input[name="question-${index}"]:checked`)?.value);
    if (answers.some(value => !value)) { showNotice('请完成全部 4 道题后提交'); return; }
    action(submit, '正在保存测试结果…', async () => {
      await api('/api/quizzes/submit', { course_id: data.course.id, quiz_id: active.id, answers });
      await openCourse(data.course.id, data.section.ordinal);
    });
  });
  box.append(form);
}

function renderCourse(data) {
  state.data = data; state.courseId = data.course.id;
  state.courses = state.courses.map(course => course.id === data.course.id
    ? { ...course, current_ordinal: data.course.current_ordinal } : course);
  $('welcome').hidden = true; $('course-view').hidden = false;
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
  $('lesson-generate').hidden = Boolean(data.section.lesson);
  $('ask-area').hidden = !data.section.lesson;
  $('quiz-card').hidden = !data.section.lesson;
  if (data.section.lesson) renderMarkdown($('lesson-content'), data.section.lesson);
  else $('lesson-content').textContent = '本节讲解尚未生成。点击下方按钮，AI 会从基础开始讲解。';
  renderConversation(data.turns); renderQuiz(data); renderOutline(data); renderSidebar();
  const isCurrent = data.section.ordinal === data.course.current_ordinal;
  const last = data.course.current_ordinal === data.course.sections.length;
  $('next-section').hidden = !isCurrent || last;
  $('next-section').disabled = !data.section.lesson;
  $('next-hint').textContent = !isCurrent ? '你正在回看旧小节。点击学习路线中的当前小节继续。'
    : last ? '这门课程的小节已全部开放，你仍可以回看和继续复测。'
    : data.section.lesson ? '准备好了再由你选择进入下一节；系统不会自动跳转。'
    : '先学习当前小节，再决定是否进入下一节。';
}

async function openCourse(id, ordinal) {
  try {
    const query = new URLSearchParams({ course_id: id });
    if (ordinal) query.set('ordinal', String(ordinal));
    renderCourse(await api(`/api/course?${query}`));
  } catch (error) { showNotice(error.message); }
}

async function bootstrap() {
  try {
    const data = await api('/api/bootstrap');
    state.courses = data.courses; renderProfiles(data); renderSidebar();
    if (!data.model_ready) { $('settings').hidden = false; showNotice('先配置并测试 AI 模型，再创建课程。'); }
    showWelcome();
  } catch (error) { showNotice(error.message); }
}

$('home-link').addEventListener('click', event => { event.preventDefault(); showWelcome(); });
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
      chat_model: $('profile-chat').value, api_key: $('profile-key').value,
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
$('course-form').addEventListener('submit', event => {
  event.preventDefault();
  action($('course-create'), 'AI 正在规划课程小节，请稍候…', async () => {
    const result = await api('/api/courses/create', {
      title: $('course-title-input').value, goal: $('course-goal-input').value,
    });
    state.courses = (await api('/api/bootstrap')).courses;
    renderCourse(result.course);
  });
});
$('lesson-generate').addEventListener('click', () => {
  const data = state.data;
  action($('lesson-generate'), 'AI 正在深入讲解这一节，请稍候…', async () => {
    renderCourse(await api('/api/sections/lesson', { course_id: data.course.id, ordinal: data.section.ordinal }));
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
bootstrap();
