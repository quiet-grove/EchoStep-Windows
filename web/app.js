'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const LETTERS = 'ABCDEF';
const PREFS_KEY = 'echostep:prefs';
const ICONS = {
  play: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 4.3v11.4L15.6 10 6 4.3Z" fill="currentColor"/></svg>',
  pause: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5.6 4h3.1v12H5.6V4Zm5.7 0h3.1v12h-3.1V4Z" fill="currentColor"/></svg>',
};

const state = {
  booted: false,
  view: 'home',
  debug: false,
  config: null,
  engines: [],
  catalog: null,
  cache: { files: 0, bytes: 0 },
  resolved: { engine: 'piper', voice: '' },
  grade: '八年级',
  book: '上册',
  unitId: '',
  webSearch: true,
  playback: { engine: 'piper', voice: '', speed: 1, soundcheck: true },
  test: null,
  result: null,
  answers: {},
  exited: false,
  seconds: 0,
  timerId: null,
  timerStarted: false,
  audioLocked: false,
  fullPlayer: null,
  toastTimer: null,
  loadingTimer: null,
  confirmResolver: null,
  modalOpen: '',
};

function escapeHTML(value) {
  const div = document.createElement('div');
  div.textContent = String(value == null ? '' : value);
  return div.innerHTML;
}

function escapeAttr(value) {
  return escapeHTML(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const total = Math.floor(seconds);
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 MB';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function setRangeFill(el) {
  if (!el) return;
  const min = Number(el.min || 0);
  const max = Number(el.max || 100);
  const value = Number(el.value || 0);
  const pct = max === min ? 0 : ((value - min) / (max - min)) * 100;
  el.style.background = `linear-gradient(90deg, var(--green-3) 0%, var(--green-3) ${pct}%, #ded8c8 ${pct}%)`;
}

function showToast(message, type = '', duration = 4400) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.className = `toast show ${type}`.trim();
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { toast.className = 'toast'; }, duration);
}

function openModal(id) {
  $$('.modal').forEach((modal) => modal.classList.add('hidden'));
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.classList.remove('hidden');
  state.modalOpen = id;
  document.body.style.overflow = 'hidden';
}

function closeModal(id = '') {
  const target = id ? document.getElementById(id) : $('.modal:not(.hidden)');
  if (target) target.classList.add('hidden');
  const remaining = $('.modal:not(.hidden)');
  state.modalOpen = remaining?.id || '';
  document.body.style.overflow = remaining ? 'hidden' : '';
}

function confirmDialog({ title = '确认操作？', message = '', confirmText = '确认', cancelText = '取消' } = {}) {
  $('#confirmTitle').textContent = title;
  $('#confirmMessage').textContent = message;
  $('#confirmOk').textContent = confirmText;
  $('#confirmCancel').textContent = cancelText;
  $('#confirmModal').classList.remove('hidden');
  state.modalOpen = 'confirmModal';
  document.body.style.overflow = 'hidden';
  return new Promise((resolve) => { state.confirmResolver = resolve; });
}

function resolveConfirm(value) {
  if (!state.confirmResolver) return;
  const resolve = state.confirmResolver;
  state.confirmResolver = null;
  closeModal('confirmModal');
  resolve(value);
}

async function api(path, { method = 'GET', body = null, timeout = 120000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      credentials: 'same-origin',
    });
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch { throw new Error(`服务器返回了无法解析的内容（HTTP ${response.status}）`); }
    if (!response.ok) {
      const error = new Error(data?.error?.message || `请求失败（HTTP ${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时了，请稍后重试');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/* --------------------------------------------------------------- local data */
function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY) || '{}') || {}; } catch { return {}; }
}

function savePrefs() {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify({ grade: state.grade, book: state.book, unitId: state.unitId })); } catch { /* ignore */ }
}

function answersKey(testId) { return `echostep:answers:${testId}`; }
function audioLockKey(testId) { return `echostep:audio-started:${testId}`; }

function loadAnswers(testId) {
  try {
    const value = JSON.parse(localStorage.getItem(answersKey(testId)) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch { return {}; }
}

function saveAnswers() {
  if (!state.test) return;
  try { localStorage.setItem(answersKey(state.test.id), JSON.stringify(state.answers)); } catch { /* ignore */ }
}

/* ------------------------------------------------------------------- state */
function applyServerState(data, { first = false } = {}) {
  state.config = data.config;
  state.engines = data.engines || [];
  state.catalog = data.catalog;
  state.cache = data.cache || { files: 0, bytes: 0 };
  state.resolved = data.tts_resolved || state.resolved;
  state.debug = Boolean(data.debug);
  if (first) {
    const prefs = loadPrefs();
    const grades = state.catalog?.grades || [];
    state.grade = grades.some((g) => g.id === prefs.grade) ? prefs.grade : '八年级';
    const gradeMeta = grades.find((g) => g.id === state.grade) || grades[0];
    if (gradeMeta) state.book = gradeMeta.books.includes(prefs.book) ? prefs.book : gradeMeta.books[0];
    const units = unitsFor();
    state.unitId = units.some((u) => u.id === prefs.unitId) ? prefs.unitId : (units[0]?.id || '');
    state.playback = {
      engine: state.resolved.engine || 'piper',
      voice: state.resolved.voice || '',
      speed: Number(state.config.speed) || 1,
      soundcheck: state.config.soundcheck !== false,
    };
    state.webSearch = Boolean(state.config.web_search);
  }
}

function unitsFor(grade = state.grade, book = state.book) {
  return state.catalog?.books?.[`${grade}${book}`]?.units || [];
}

function currentUnit() { return unitsFor().find((u) => u.id === state.unitId) || null; }
function currentGradeMeta() { return state.catalog?.grades?.find((g) => g.id === state.grade) || null; }
function availableEngines() { return (state.engines || []).filter((e) => e.available && e.voices?.length); }
function engineById(id) { return state.engines.find((e) => e.id === id) || null; }
function voiceById(engineId, voiceId) { return engineById(engineId)?.voices?.find((v) => v.id === voiceId) || null; }

function updateApiPill() {
  const pill = $('#apiPill');
  if (!pill) return;
  const label = pill.querySelector('span');
  if (state.config?.has_key) {
    pill.className = 'api-pill ok';
    label.textContent = 'DeepSeek 就绪';
    pill.title = state.config.key_from_env ? '使用环境变量中的密钥' : `密钥 ${state.config.key_masked}`;
  } else {
    pill.className = 'api-pill warn';
    label.textContent = '未配置 API';
  }
  const debug = $('#debugPill');
  if (debug) debug.classList.toggle('hidden', !state.debug);
}

/* -------------------------------------------------------------------- home */
function renderHome() {
  if (!state.catalog) return;
  renderGradeGrid();
  renderBookSelect();
  renderUnitSelect();
  renderScopeNote();
  renderVoiceSelect();
  const speed = $('#speedRange');
  if (speed) {
    speed.value = String(state.playback.speed);
    $('#speedValue').textContent = `${Number(state.playback.speed).toFixed(2).replace(/0$/, '')}×`;
    setRangeFill(speed);
  }
  const web = $('#webSearchToggle');
  if (web) web.checked = Boolean(state.webSearch);
  const soundcheck = $('#soundcheckToggle');
  if (soundcheck) soundcheck.checked = Boolean(state.playback.soundcheck);
  updateApiPill();
  renderApiCard();
  renderTtsCard();
}

function renderGradeGrid() {
  const grid = $('#gradeGrid');
  if (!grid) return;
  grid.innerHTML = (state.catalog?.grades || []).map((grade) => `
    <button type="button" class="grade-card ${grade.id === state.grade ? 'active' : ''}" data-grade="${escapeAttr(grade.id)}">
      <span class="grade-check">✓</span><span class="g-short">${escapeHTML(grade.short)}</span>
      <strong>${escapeHTML(grade.label)}</strong><small>${escapeHTML(grade.tagline)}</small>
    </button>`).join('');
}

function renderBookSelect() {
  const meta = currentGradeMeta();
  const select = $('#bookSelect');
  if (!meta || !select) return;
  if (!meta.books.includes(state.book)) state.book = meta.books[0];
  select.innerHTML = meta.books.map((book) => `<option value="${escapeAttr(book)}" ${book === state.book ? 'selected' : ''}>${escapeHTML(book)}</option>`).join('');
}

function renderUnitSelect() {
  const select = $('#unitSelect');
  if (!select) return;
  const units = unitsFor();
  if (!units.some((u) => u.id === state.unitId)) state.unitId = units[0]?.id || '';
  select.innerHTML = units.map((u) => `<option value="${escapeAttr(u.id)}" ${u.id === state.unitId ? 'selected' : ''}>${escapeHTML(u.title)}</option>`).join('');
}

function renderScopeNote() {
  const note = $('#scopeNote');
  const grade = currentGradeMeta();
  if (!note || !grade) return;
  note.innerHTML = `<strong>本卷知识边界</strong>${escapeHTML(grade.scope)}`;
}

function renderVoiceSelect() {
  const select = $('#voiceSelect');
  if (!select) return;
  const engines = availableEngines();
  if (!engines.length) { select.innerHTML = '<option value="">没有可用语音</option>'; return; }
  let selected = `${state.playback.engine}::${state.playback.voice}`;
  const exists = engines.some((e) => e.voices.some((v) => `${e.id}::${v.id}` === selected));
  if (!exists) {
    selected = `${engines[0].id}::${engines[0].voices[0].id}`;
    state.playback.engine = engines[0].id;
    state.playback.voice = engines[0].voices[0].id;
  }
  select.innerHTML = engines.map((engine) => `
    <optgroup label="${escapeAttr(engine.name)}${engine.offline ? ' · 离线' : ' · 需联网'}">
      ${engine.voices.map((voice) => `<option value="${escapeAttr(engine.id)}::${escapeAttr(voice.id)}" ${`${engine.id}::${voice.id}` === selected ? 'selected' : ''}>${escapeHTML(voice.name)}</option>`).join('')}
    </optgroup>`).join('');
}

function renderApiCard() {
  const card = $('#apiCard');
  if (!card) return;
  if (state.config?.has_key) {
    card.className = 'panel api-card ok';
    card.innerHTML = `<div class="api-kicker"><span>DEEPSEEK API</span><i class="api-status-dot"></i></div>
      <h3>已就绪，可以出卷</h3>
      <p>密钥仅保存在这台电脑上。当前模型 <b>${escapeHTML(state.config.model)}</b>。</p>
      <div class="key-preview"><span>${escapeHTML(state.config.key_masked)}</span><span>LOCAL</span></div>
      <button type="button" class="primary-btn" id="editKeyBtn">管理密钥与模型</button>`;
    $('#editKeyBtn')?.addEventListener('click', openSettings);
  } else {
    card.className = 'panel api-card';
    card.innerHTML = `<div class="api-kicker"><span>DEEPSEEK API</span><i class="api-status-dot"></i></div>
      <h3>先填入你的 API Key</h3><p>使用 DeepSeek 官方 API 按模板 A 自主出卷。密钥保存在本机。</p>
      <button type="button" class="primary-btn" id="setupKeyBtn">填写密钥</button>`;
    $('#setupKeyBtn')?.addEventListener('click', () => { openSettings(); setTimeout(() => $('#settingKey')?.focus(), 80); });
  }
}

function renderTtsCard() {
  const card = $('#ttsCard');
  if (!card) return;
  const engine = engineById(state.playback.engine) || availableEngines()[0];
  const voice = engine ? voiceById(engine.id, state.playback.voice) : null;
  if (!engine) { card.innerHTML = '<div class="mini-title">TTS VOICE</div><h3>没有可用语音</h3><p>请检查 TTS 引擎。</p>'; return; }
  const size = engine.id === 'piper' ? `${engine.size_mb} MB` : engine.id === 'edge' ? 'ONLINE' : 'SYSTEM';
  card.innerHTML = `<div class="tts-head"><span class="mini-title">TTS VOICE</span><span class="size-chip">${escapeHTML(size)}</span></div>
    <div class="tts-visual">${[32,55,78,44,68,38,84,52,72,35,60,88,46,66,30,58,74,42].map((h) => `<i style="height:${h}%"></i>`).join('')}</div>
    <div class="tts-row"><div><strong>${escapeHTML(voice?.name || engine.name)}</strong><span>${escapeHTML(engine.name)} · ${engine.offline ? '离线' : '需联网'}</span></div></div>
    <p class="fineprint" style="text-align:left;margin-top:8px">${escapeHTML(engine.detail)}</p>
    <p class="fineprint" style="text-align:left;margin-top:4px">模板音频会朗读中文节指令与英文材料；题干默认不朗读。</p>`;
}

/* --------------------------------------------------------------- generation */
function showLoading() {
  const messages = ['正在按模板 A 命题…', state.webSearch ? '正在联网检索素材…' : '正在整理教材单元…', '正在生成 30 题、5 节的音频文本…', '正在校验题号、选项和答案…'];
  let index = 0;
  $('#loadingText').textContent = messages[0];
  $('#loadingOverlay').classList.remove('hidden');
  clearInterval(state.loadingTimer);
  state.loadingTimer = setInterval(() => { index = (index + 1) % messages.length; $('#loadingText').textContent = messages[index]; }, 3200);
}

function hideLoading() {
  clearInterval(state.loadingTimer);
  state.loadingTimer = null;
  $('#loadingOverlay').classList.add('hidden');
}

async function generateTest() {
  if (!state.config?.has_key) {
    showToast('请先填写 DeepSeek API Key', 'warn');
    openSettings();
    setTimeout(() => $('#settingKey')?.focus(), 80);
    return;
  }
  const unit = currentUnit();
  if (!unit) { showToast('请选择教材单元', 'warn'); return; }
  const payload = {
    grade: state.grade,
    book: state.book,
    unit_id: state.unitId,
    topic: ($('#topicInput')?.value || '').trim(),
    web_search: $('#webSearchToggle')?.checked ?? state.webSearch,
  };
  showLoading();
  try {
    const data = await api('/api/generate', { method: 'POST', body: payload, timeout: 300000 });
    state.test = data.test;
    state.result = null;
    state.exited = false;
    state.answers = loadAnswers(data.test.id);
    hideLoading();
    showExam();
    if (data.meta?.search_warning) showToast(data.meta.search_warning, 'warn', 6500);
    else if (data.meta?.search_count) showToast(`已联网参考 ${data.meta.search_count} 条素材`, 'ok', 3000);
  } catch (error) {
    hideLoading();
    showToast(error.message || '生成失败，请重试', 'err', 7000);
    if (error.status === 401 || error.status === 402) openSettings();
  }
}

/* -------------------------------------------------------------------- exam */
function showExam() {
  if (!state.test) return;
  stopAudio();
  stopTimer();
  state.view = 'exam';
  state.result = null;
  state.exited = false;
  state.seconds = 0;
  state.timerStarted = false;
  updateTimer();
  state.audioLocked = !state.debug && localStorage.getItem(audioLockKey(state.test.id)) === '1';
  $('#examKicker').textContent = `${state.test.grade}${state.test.book} · ${state.test.unit_title} · 30 题 / 30 分`;
  $('#examTitle').textContent = state.test.title || '英语听力试卷';
  $('#examSpeedLabel').textContent = `${Number(state.playback.speed).toFixed(2).replace(/0$/, '')}×`;
  renderSearchNote();
  renderSections();
  renderAnswerGrid();
  updateAnswered();
  setupFullAudio();
  showViewOnly('exam');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showViewOnly(name) {
  for (const view of ['home', 'exam', 'result']) $(`#${view}View`)?.classList.toggle('hidden', view !== name);
}

function showView(name) {
  if (name !== 'exam') { stopTimer(); stopAudio(); }
  state.view = name;
  showViewOnly(name);
  if (name === 'home') renderHome();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderSearchNote() {
  const note = $('#searchNote');
  if (!note) return;
  const sources = state.test?.search_sources || [];
  const warning = state.test?.search_warning || '';
  if (!sources.length && !warning) { note.classList.add('hidden'); return; }
  note.classList.remove('hidden');
  note.className = `search-note ${!sources.length ? 'warn' : ''}`;
  if (sources.length) {
    note.innerHTML = `已联网参考 <b>${sources.length}</b> 条素材。` + sources.slice(0, 3).map((s, i) => {
      try {
        const u = new URL(s.url);
        if (!['http:', 'https:'].includes(u.protocol)) return '';
        return `<a href="${escapeAttr(u.href)}" target="_blank" rel="noopener noreferrer">[${i + 1}] ${escapeHTML(s.site_name || s.title || '来源')}</a>`;
      } catch { return ''; }
    }).join(' ') + (warning ? ` <span>（${escapeHTML(warning)}）</span>` : '');
  } else {
    note.textContent = warning;
  }
}

function sectionHeader(section) {
  const typeLabel = { word_choice: '辨音', word_match: '辨音', short_dialogue: '短对话', long_dialogue: '长对话', passage: '短文', table_fill: '填词' }[section.type] || '';
  return `<div class="section-heading"><span class="section-no">${String(section.index).padStart(2, '0')}</span>
    <div><h2>第 ${section.index} 节 <span class="section-template-tag">${typeLabel}</span></h2><p>${escapeHTML(section.instruction)}</p></div>
    <span class="q-total">${section.questions.length} 题</span></div>`;
}

function renderSections() {
  const list = $('#sectionList');
  list.innerHTML = state.test.sections.map((section) => {
    let body = '';
    if (section.type === 'table_fill') body = fillBody(section);
    else body = choiceBody(section);
    return `<article class="section-block" data-section-id="${escapeAttr(section.id)}">${sectionHeader(section)}${body}</article>`;
  }).join('');
  bindFillInputs();
  restoreAnswers();
}

function wordMatchBody(section) {
  const bank = `<div class="word-bank">${section.word_bank.map((word, i) => `<div class="word-chip"><b>${LETTERS[i]}</b><span>${escapeHTML(word)}</span></div>`).join('')}</div>`;
  const rows = section.questions.map((q) => `<div class="match-row" data-qid="${escapeAttr(q.id)}">
    <span class="match-number">${q.number}</span>
    <div class="match-options">${LETTERS.split('').map((letter, i) => `<button type="button" class="match-letter" data-index="${i}">${letter}</button>`).join('')}</div>
  </div>`).join('');
  return `${bank}<div class="match-list">${rows}</div>`;
}

function choiceBody(section) {
  let lastMaterial = null;
  return section.questions.map((q) => {
    let cue = '';
    if (section.type === 'long_dialogue' && q.material_index !== lastMaterial) {
      lastMaterial = q.material_index;
      const group = section.questions.filter((x) => x.material_index === q.material_index);
      const first = group[0].number;
      const last = group[group.length - 1].number;
      cue = `<div class="material-cue">听下面一段对话，回答第 ${first}${last !== first ? ` 至 ${last}` : ''} 题。</div>`;
    }
    return `${cue}${choiceQuestion(q)}`;
  }).join('');
}

function choiceQuestion(q) {
  return `<div class="question-card" id="${escapeAttr(q.id)}" data-qid="${escapeAttr(q.id)}">
    <div class="question-head"><span class="q-no">${q.number}</span><p class="question-text"><span class="question-zh">${escapeHTML(q.question)}</span></p></div>
    <div class="options three">${q.options.map((option, i) => `<button type="button" class="option" data-index="${i}"><span class="letter">${LETTERS[i]}</span><span class="text">${escapeHTML(option)}</span></button>`).join('')}</div>
  </div>`;
}

function fillBody(section) {
  const table = section.table;
  const questionByNumber = new Map(section.questions.map((q) => [q.number, q]));
  const rows = table.rows.map((row) => {
    const q = questionByNumber.get(row.number);
    if (!q) return '';
    return `<tr data-qid="${escapeAttr(q.id)}"><td class="fill-label">${escapeHTML(row.label)}</td>
      <td><div class="fill-line"><span class="fill-prefix">${escapeHTML(row.prefix)}</span>
      <input class="fill-input" data-qid="${escapeAttr(q.id)}" value="${escapeAttr(state.answers[q.id] || '')}" maxlength="24" autocomplete="off" spellcheck="false" aria-label="第 ${q.number} 题">
      <span class="fill-suffix">${escapeHTML(row.suffix)}</span></div></td></tr>`;
  }).join('');
  return `<div class="fill-title">${escapeHTML(table.title)}</div><table class="fill-table"><tbody>${rows}</tbody></table>`;
}

function bindFillInputs() {
  $$('#sectionList .fill-input').forEach((input) => {
    input.addEventListener('input', () => {
      state.answers[input.dataset.qid] = input.value;
      saveAnswers();
      updateAnswered();
      renderAnswerGrid();
    });
  });
}

function setChoice(qid, index) {
  if (!state.test || state.view !== 'exam') return;
  state.answers[qid] = index;
  saveAnswers();
  const row = document.querySelector(`[data-qid="${CSS.escape(qid)}"]`);
  if (row) $$('.match-letter, .option', row).forEach((item) => item.classList.toggle('selected', Number(item.dataset.index) === index));
  updateAnswered();
  renderAnswerGrid();
}

function restoreAnswers() {
  for (const [qid, value] of Object.entries(state.answers || {})) {
    const row = document.querySelector(`[data-qid="${CSS.escape(qid)}"]`);
    if (!row) continue;
    if (row.classList.contains('match-row')) {
      $$('.match-letter', row).forEach((item) => item.classList.toggle('selected', Number(item.dataset.index) === Number(value)));
    } else if (row.classList.contains('question-card')) {
      $$('.option', row).forEach((item) => item.classList.toggle('selected', Number(item.dataset.index) === Number(value)));
    }
  }
}

function isAnswered(q) {
  const value = state.answers[q.id];
  if (q.type === 'fill') return String(value == null ? '' : value).trim() !== '';
  return value !== null && value !== '' && Number.isInteger(Number(value));
}

function allQuestions() { return state.test ? state.test.sections.flatMap((s) => s.questions) : []; }
function answeredTotal() { return allQuestions().filter(isAnswered).length; }

function updateAnswered() {
  if (!state.test) return;
  const total = allQuestions().length;
  const count = answeredTotal();
  $('#answeredCount').textContent = `${count} / ${total}`;
  $('#submitTopBtn').textContent = count ? `交卷 · ${count}/${total}` : '交卷';
}

function renderAnswerGrid() {
  const grid = $('#answerGrid');
  if (!grid || !state.test) return;
  grid.innerHTML = allQuestions().map((q) => `<button type="button" class="${isAnswered(q) ? 'done' : ''}" data-qid="${escapeAttr(q.id)}">${q.number}</button>`).join('');
}

function scrollToQuestion(qid, prefix = '') {
  const node = document.getElementById(`${prefix}${qid}`) || document.querySelector(`[data-qid="${CSS.escape(qid)}"]`);
  if (!node) return;
  node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  const input = $('input.fill-input', node);
  if (input) setTimeout(() => input.focus(), 300);
}

/* ------------------------------------------------------------------- audio */
function audioParams() {
  return new URLSearchParams({
    engine: state.playback.engine,
    voice: state.playback.voice,
    speed: String(state.playback.speed),
    soundcheck: state.playback.soundcheck ? '1' : '0',
  });
}

function examAudioUrl() {
  return `/api/exam-audio/${encodeURIComponent(state.test.id)}?${audioParams().toString()}`;
}

function setupFullAudio() {
  const panel = $('#fullAudioPanel');
  if (!panel || !state.test) return;
  const button = $('#fullPlayBtn');
  const progress = $('#fullProgress');
  const range = $('#fullRange');
  const status = $('#fullAudioStatus');
  const time = $('#fullAudioTime');
  const duration = $('#fullDuration');
  const tip = $('#fullAudioTip');
  const rule = $('#audioRule');
  const audio = new Audio();
  audio.preload = 'auto';
  const player = { audio, button, progress, range, status, time, duration, tip, rule, ready: false };
  state.fullPlayer = player;
  progress.style.width = '0%';
  range.value = '0';
  $('#fullSpeedValue').textContent = `${Number(state.playback.speed).toFixed(2).replace(/0$/, '')}×`;

  if (state.debug) {
    rule.textContent = 'DEBUG 模式：可暂停、拖动、回放';
    range.disabled = false;
    panel.classList.remove('locked');
  } else {
    range.disabled = true;
  }

  if (state.audioLocked && !state.debug) {
    panel.classList.add('locked');
    button.disabled = true;
    button.innerHTML = ICONS.play;
    status.textContent = '本场听力已经开始，按考试规则不可回放';
    tip.textContent = '如需重新练习，请生成新试卷；调试可启动 --debug。';
    duration.textContent = '--:--';
    return;
  }

  const setStatus = (text, error = false) => { status.textContent = text; panel.classList.toggle('error', error); };
  const updateTime = () => {
    const total = Number.isFinite(audio.duration) ? audio.duration : 0;
    const current = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    time.textContent = `${formatTime(current)} / ${total ? formatTime(total) : '--:--'}`;
    progress.style.width = `${total ? Math.min(100, (current / total) * 100) : 0}%`;
    if (total) duration.textContent = formatTime(total);
    if (state.debug) range.value = String(total ? Math.min(100, (current / total) * 100) : 0);
  };
  const lockPlayback = () => {
    if (state.debug) return;
    state.audioLocked = true;
    try { localStorage.setItem(audioLockKey(state.test.id), '1'); } catch { /* ignore */ }
    panel.classList.add('locked');
    button.disabled = true;
    range.disabled = true;
    rule.textContent = '考试模式：已开始，不可暂停/拖动/回放';
  };
  const loadSource = () => {
    audio.src = examAudioUrl();
    audio.load();
    setStatus('正在合成整套考试音频，请稍候…');
    tip.textContent = '30 题整套音频较长，首次生成需要时间；生成后会缓存。';
  };
  const play = () => {
    if (button.disabled) return;
    if (!audio.src) loadSource();
    if (!audio.paused) { if (state.debug) audio.pause(); return; }
    audio.play().then(() => { if (!state.timerStarted) startTimer(); }).catch(() => {
      setStatus('整套音频播放失败，点击重试', true);
      button.innerHTML = ICONS.play;
    });
  };

  button.onclick = play;
  range.oninput = () => {
    if (!state.debug) return;
    if (Number.isFinite(audio.duration)) {
      audio.currentTime = (Number(range.value) / 100) * audio.duration;
      updateTime();
    }
  };
  audio.addEventListener('loadedmetadata', () => {
    player.ready = true;
    setStatus(state.debug ? '音频已就绪 · 可拖动/回放' : '整套音频已就绪 · 点击开始（含试音）');
    updateTime();
  });
  audio.addEventListener('timeupdate', updateTime);
  audio.addEventListener('playing', () => {
    button.innerHTML = ICONS.pause;
    if (!state.debug) {
      lockPlayback();
      if (!state.timerStarted) startTimer();
      setStatus('考试音频播放中 · 不可回放');
    } else {
      setStatus('考试音频播放中 · DEBUG');
    }
  });
  audio.addEventListener('pause', () => {
    if (audio.ended) return;
    button.innerHTML = ICONS.play;
    if (state.debug) setStatus('已暂停 · DEBUG 可继续');
  });
  audio.addEventListener('ended', () => {
    button.innerHTML = ICONS.play;
    button.disabled = !state.debug;
    setStatus('整套音频播放完毕 · 可以交卷');
    progress.style.width = '100%';
  });
  audio.addEventListener('error', () => {
    setStatus('整套音频合成失败，点击重试', true);
    button.innerHTML = ICONS.play;
  });
  loadSource();
}

function startTimer() {
  stopTimer();
  state.timerStarted = true;
  state.seconds = 0;
  updateTimer();
  state.timerId = setInterval(() => { state.seconds += 1; updateTimer(); }, 1000);
}

function stopTimer() {
  if (state.timerId) clearInterval(state.timerId);
  state.timerId = null;
}

function updateTimer() {
  const timer = $('#timer');
  if (timer) timer.textContent = formatTime(state.seconds);
}

function stopAudio() {
  if (state.fullPlayer) { try { state.fullPlayer.audio.pause(); } catch { /* ignore */ } }
  stopTimer();
}

/* --------------------------------------------------------------- submit/exit */
async function submitExam() {
  if (!state.test || state.result) return;
  const unanswered = allQuestions().length - answeredTotal();
  if (unanswered > 0) {
    const ok = await confirmDialog({ title: `还有 ${unanswered} 题没做`, message: '现在交卷也可以，空题会按答错计算。', confirmText: '仍然交卷', cancelText: '再检查一下' });
    if (!ok) return;
  }
  await gradeCurrent(false);
}

function openExitDialog() {
  if (!state.test) { showView('home'); return; }
  const count = answeredTotal();
  $('#exitGradeBtn').disabled = count === 0;
  $('#exitGradeBtn').textContent = count ? `批改已选（${count} 题）并退出` : '没有已选题目可批改';
  $('#exitMessage').textContent = state.audioLocked
    ? '听力已经开始，按考试规则不可回放。退出后可以选择是否批改已选题目。'
    : '退出后可以批改已选题目，也可以直接返回首页。';
  openModal('exitModal');
}

async function exitWithGrade() {
  closeModal('exitModal');
  await gradeCurrent(true);
}

function exitDirect() {
  closeModal('exitModal');
  try { localStorage.removeItem(answersKey(state.test.id)); } catch { /* ignore */ }
  state.answers = {};
  showView('home');
}

async function gradeCurrent(exited) {
  stopAudio();
  stopTimer();
  const buttons = [$('#submitBtn'), $('#submitTopBtn'), $('#exitGradeBtn')];
  buttons.forEach((b) => { if (b) b.disabled = true; });
  try {
    const result = await api('/api/grade', { method: 'POST', body: { test_id: state.test.id, answers: state.answers }, timeout: 60000 });
    state.result = result;
    state.exited = Boolean(exited);
    showView('result');
    renderResult();
  } catch (error) {
    showToast(error.message || '批改失败，请重试', 'err');
  } finally {
    buttons.forEach((b) => { if (b) b.disabled = false; });
  }
}

/* ------------------------------------------------------------------ result */
function renderResult() {
  const result = state.result;
  if (!result) return;
  const percent = result.percent || 0;
  $('#scoreRing').style.setProperty('--pct', String(percent));
  $('#scoreTotal').textContent = `/ ${result.total}`;
  animateNumber($('#scoreNum'), result.score);
  $('#statCorrect').textContent = result.score;
  $('#statWrong').textContent = result.total - result.score;
  $('#statPercent').textContent = `${percent}%`;
  $('#statTime').textContent = formatTime(state.seconds);
  $('#resultTitle').textContent = state.exited ? '已退出 · 批改结果' : (percent === 100 ? '满分，漂亮。' : percent >= 80 ? '做得不错。' : percent >= 60 ? '继续磨耳朵。' : '慢一点，也没关系。');
  $('#resultMsg').textContent = state.exited
    ? '你选择了退出考试，并批改已选题目。空题按答错计算。'
    : (percent === 100 ? '全对。你的耳朵已经跟上了英语的节奏。' : percent >= 80 ? '很稳。再精听一下错题里的关键句。' : percent >= 60 ? '基础不错。把错题原文读一遍，再盲听一次。' : '别急，先把原文看懂，再逐句跟读。');
  $('#resultScorePill').textContent = `${result.score} / ${result.total}`;
  renderResultGrid();
  renderResultSections();
  updateTimer();
}

function animateNumber(element, target) {
  if (!element) return;
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / 650);
    element.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function renderResultGrid() {
  const grid = $('#resultGrid');
  if (!grid || !state.test) return;
  const details = new Map((state.result?.details || []).map((d) => [d.id, d]));
  grid.innerHTML = allQuestions().map((q) => {
    const d = details.get(q.id);
    return `<button type="button" class="${d?.correct ? 'right' : 'wrong'}" data-qid="${escapeAttr(q.id)}">${q.number}</button>`;
  }).join('');
}

function renderResultSections() {
  const container = $('#resultSections');
  if (!container || !state.test) return;
  const details = new Map((state.result?.details || []).map((d) => [d.id, d]));
  const resultSections = new Map((state.result?.sections || []).map((s) => [s.id, s]));
  container.innerHTML = state.test.sections.map((section) => {
    let body = '';
    if (section.type === 'table_fill') {
      const rows = section.table.rows.map((row) => {
        const q = section.questions.find((x) => x.number === row.number);
        const d = details.get(q.id) || {};
        return `<tr><td class="fill-label">${escapeHTML(row.label)}</td><td><div class="fill-line"><span class="fill-prefix">${escapeHTML(row.prefix)}</span>
          <span class="fill-input ${d.correct ? 'correct' : 'wrong'}" style="display:inline-flex;align-items:center;justify-content:center;width:auto;min-width:74px;flex:0 0 auto">${escapeHTML(d.selected || '未填')}</span>
          <span class="fill-suffix">${escapeHTML(row.suffix)}</span>${d.correct ? '' : `<span class="pill-correct" style="margin-left:6px">正确：${escapeHTML(d.answer)}</span>`}</div></td></tr>`;
      }).join('');
      body = `<div class="fill-title">${escapeHTML(section.table.title)}</div><table class="fill-table"><tbody>${rows}</tbody></table>` +
        section.questions.map((q) => { const d = details.get(q.id) || {}; return `<div class="explanation" style="margin-left:0">第 ${q.number} 题：${escapeHTML(d.explanation || '')}</div>`; }).join('');
    } else {
      let lastMaterial = null;
      body = section.questions.map((q) => {
        let cue = '';
        if (section.type === 'long_dialogue' && q.material_index !== lastMaterial) {
          lastMaterial = q.material_index;
          const group = section.questions.filter((x) => x.material_index === q.material_index);
          cue = `<div class="material-cue">材料 ${q.material_index + 1} · 第 ${group[0].number}${group.length > 1 ? `–${group[group.length - 1].number}` : ''} 题</div>`;
        }
        const d = details.get(q.id) || {};
        const selected = d.type === 'choice' && d.selected != null ? `${LETTERS[d.selected]}. ${q.options[d.selected]}` : '未作答';
        const correct = `${LETTERS[d.answer]}. ${q.options[d.answer]}`;
        return `${cue}<div class="result-question" id="result-${escapeAttr(q.id)}"><div class="result-q-head"><span class="q-no">${q.number}</span><p>${escapeHTML(q.question)}</p></div>
          <div class="result-answer-line"><span class="${d.correct ? 'pill-correct' : 'pill-wrong'}">${d.correct ? '答对了' : '答错了'}</span><span>你的答案：<b>${escapeHTML(selected)}</b></span>${d.correct ? '' : `<span>正确答案：<b>${escapeHTML(correct)}</b></span>`}</div>
          <div class="explanation">${escapeHTML(d.explanation || '')}</div></div>`;
      }).join('');
    }
    const rs = resultSections.get(section.id);
    const materials = (rs?.materials || []).map((m) => `<div class="transcript-material"><strong>材料 ${m.index}${m.questions?.length ? ` · 第 ${m.questions[0]}${m.questions.length > 1 ? `–${m.questions[m.questions.length - 1]}` : ''} 题` : ''}</strong><div class="transcript-text">${escapeHTML(m.transcript)}</div></div>`).join('');
    return `<article class="panel result-section" data-section-id="${escapeAttr(section.id)}">${sectionHeader(section)}${body}
      <details class="transcript-box section-transcript"><summary>查看本节听力原文</summary>${materials}</details></article>`;
  }).join('');
}

/* ----------------------------------------------------------------- settings */
function openSettings() {
  if (!state.config) return;
  const cfg = state.config;
  $('#settingKey').value = '';
  $('#settingKey').placeholder = cfg.has_key ? cfg.key_masked : 'sk-……';
  $('#keySource').textContent = cfg.key_from_env ? '来自环境变量' : cfg.has_key ? '已保存在本机' : '尚未填写';
  $('#settingBase').value = cfg.base_url || 'https://api.deepseek.com';
  $('#settingModel').innerHTML = (cfg.models || []).map((m) => `<option value="${escapeAttr(m.id)}" ${m.id === cfg.model ? 'selected' : ''}>${escapeHTML(m.label)} · ${escapeHTML(m.hint)}</option>`).join('');
  $('#settingThinking').checked = Boolean(cfg.thinking);
  $('#settingWebSearch').checked = Boolean(cfg.web_search);
  $('#settingSoundcheck').checked = cfg.soundcheck !== false;
  $('#connectionResult').textContent = '';
  $('#connectionResult').className = 'inline-result';
  $('#cacheInfo').textContent = `${formatBytes(state.cache.bytes)} · ${state.cache.files || 0} 个文件`;
  openModal('settingsModal');
}

async function saveSettings() {
  const patch = {
    base_url: $('#settingBase').value.trim(),
    model: $('#settingModel').value,
    thinking: $('#settingThinking').checked,
    web_search: $('#settingWebSearch').checked,
    soundcheck: $('#settingSoundcheck').checked,
  };
  const key = $('#settingKey').value.trim();
  if (key) patch.api_key = key;
  const button = $('#saveSettingsBtn');
  button.disabled = true;
  try {
    const data = await api('/api/config', { method: 'POST', body: patch });
    applyServerState(data.state);
    state.playback.soundcheck = data.state.config.soundcheck !== false;
    state.webSearch = Boolean(data.state.config.web_search);
    closeModal('settingsModal');
    renderHome();
    showToast('设置已保存', 'ok');
  } catch (error) {
    showToast(error.message || '保存失败', 'err');
  } finally {
    button.disabled = false;
  }
}

async function testConnection() {
  const button = $('#testConnectionBtn');
  const result = $('#connectionResult');
  button.disabled = true;
  result.className = 'inline-result';
  result.textContent = '连接中…';
  try {
    const data = await api('/api/test-connection', { method: 'POST', body: { api_key: $('#settingKey').value.trim(), base_url: $('#settingBase').value.trim(), model: $('#settingModel').value }, timeout: 40000 });
    result.className = 'inline-result ok';
    result.textContent = `连接成功 · ${data.latency_ms} ms`;
  } catch (error) {
    result.className = 'inline-result err';
    result.textContent = error.message || '连接失败';
  } finally {
    button.disabled = false;
  }
}

async function clearCache() {
  try {
    const data = await api('/api/cache/clear', { method: 'POST', body: {} });
    state.cache = data.cache;
    $('#cacheInfo').textContent = `${formatBytes(state.cache.bytes)} · ${state.cache.files || 0} 个文件`;
    showToast(`已清除 ${data.removed} 个音频文件`, 'ok');
  } catch (error) {
    showToast(error.message || '清除失败', 'err');
  }
}

async function clearApiKey() {
  const ok = await confirmDialog({ title: '清除本机密钥？', message: '保存的 API Key 会从 data/config.json 删除。', confirmText: '清除密钥' });
  if (!ok) return;
  try {
    const data = await api('/api/config', { method: 'POST', body: { clear_key: true } });
    applyServerState(data.state);
    $('#settingKey').value = '';
    $('#keySource').textContent = data.state.config.key_from_env ? '来自环境变量' : '尚未填写';
    renderHome();
    showToast('本机密钥已清除', 'ok');
  } catch (error) {
    showToast(error.message || '清除失败', 'err');
  }
}

function resetSettings() {
  $('#settingBase').value = 'https://api.deepseek.com';
  $('#settingModel').value = 'deepseek-flash';
  $('#settingThinking').checked = false;
  $('#settingWebSearch').checked = true;
  $('#settingSoundcheck').checked = true;
  showToast('已恢复默认值，点击保存生效', 'warn');
}

/* ------------------------------------------------------------------ history */
function formatHistoryDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { day: '—', month: '—' };
  return { day: String(date.getDate()).padStart(2, '0'), month: `${date.getMonth() + 1}月` };
}

async function openHistory() {
  openModal('historyModal');
  const list = $('#historyList');
  list.innerHTML = '<div class="empty-state">正在加载…</div>';
  try {
    const data = await api('/api/history');
    const items = data.items || [];
    if (!items.length) {
      list.innerHTML = '<div class="empty-state"><strong>还没有试卷</strong>按模板 A 生成第一套听力练习。</div>';
      return;
    }
    list.innerHTML = items.map((item) => {
      const date = formatHistoryDate(item.created_at);
      return `<button type="button" class="history-item" data-test-id="${escapeAttr(item.id)}">
        <span class="history-date"><strong>${date.day}</strong><small>${date.month}</small></span>
        <span class="history-info"><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.grade)}${escapeHTML(item.book)} · ${item.question_count || 30} 题 · 模板 A</small></span>
        <span>${escapeHTML(item.model || '')}</span></button>`;
    }).join('');
  } catch (error) {
    list.innerHTML = `<div class="empty-state">${escapeHTML(error.message || '历史加载失败')}</div>`;
  }
}

async function openHistoryTest(testId) {
  try {
    const data = await api(`/api/test/${encodeURIComponent(testId)}`);
    state.test = data.test;
    state.result = null;
    state.exited = false;
    state.answers = loadAnswers(data.test.id);
    closeModal('historyModal');
    showExam();
  } catch (error) {
    showToast(error.message || '试卷加载失败', 'err');
  }
}

/* -------------------------------------------------------------------- boot */
function bindEvents() {
  $('#brandHome')?.addEventListener('click', (event) => {
    event.preventDefault();
    if (state.view === 'exam') openExitDialog();
    else showView('home');
  });
  $('#settingsBtn')?.addEventListener('click', openSettings);
  $('#historyBtn')?.addEventListener('click', openHistory);
  $('#gradeGrid')?.addEventListener('click', (event) => {
    const card = event.target.closest('[data-grade]');
    if (!card) return;
    state.grade = card.dataset.grade;
    const meta = currentGradeMeta();
    state.book = meta?.books?.[0] || '上册';
    state.unitId = unitsFor()[0]?.id || '';
    renderHome();
    savePrefs();
  });
  $('#bookSelect')?.addEventListener('change', (event) => {
    state.book = event.target.value;
    state.unitId = unitsFor()[0]?.id || '';
    renderUnitSelect();
    savePrefs();
  });
  $('#unitSelect')?.addEventListener('change', (event) => { state.unitId = event.target.value; savePrefs(); });
  $('#speedRange')?.addEventListener('input', (event) => {
    state.playback.speed = Number(event.target.value);
    $('#speedValue').textContent = `${state.playback.speed.toFixed(2).replace(/0$/, '')}×`;
    setRangeFill(event.target);
  });
  $('#voiceSelect')?.addEventListener('change', (event) => {
    const [engine, voice] = event.target.value.split('::');
    state.playback.engine = engine;
    state.playback.voice = voice;
    renderTtsCard();
  });
  $('#webSearchToggle')?.addEventListener('change', (event) => { state.webSearch = event.target.checked; });
  $('#soundcheckToggle')?.addEventListener('change', (event) => { state.playback.soundcheck = event.target.checked; });
  $('#generateBtn')?.addEventListener('click', generateTest);
  $('#backHomeBtn')?.addEventListener('click', openExitDialog);
  $('#exitExamBtn')?.addEventListener('click', openExitDialog);
  $('#submitBtn')?.addEventListener('click', submitExam);
  $('#submitTopBtn')?.addEventListener('click', submitExam);
  $('#sectionList')?.addEventListener('click', (event) => {
    const letter = event.target.closest('.match-letter');
    if (letter) { setChoice(letter.closest('.match-row').dataset.qid, Number(letter.dataset.index)); return; }
    const option = event.target.closest('.option');
    if (option) setChoice(option.closest('.question-card').dataset.qid, Number(option.dataset.index));
  });
  $('#answerGrid')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-qid]');
    if (button) scrollToQuestion(button.dataset.qid);
  });
  $('#resultGrid')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-qid]');
    if (button) scrollToQuestion(button.dataset.qid, 'result-');
  });
  $('#newTestBtn')?.addEventListener('click', generateTest);
  $('#resultHomeBtn')?.addEventListener('click', () => showView('home'));
  $('#toggleTranscriptBtn')?.addEventListener('click', (event) => {
    const details = $$('.section-transcript');
    const open = !details.every((d) => d.open);
    details.forEach((d) => { d.open = open; });
    event.currentTarget.textContent = open ? '收起全部原文' : '展开全部原文';
  });
  $('#exitGradeBtn')?.addEventListener('click', exitWithGrade);
  $('#exitDirectBtn')?.addEventListener('click', exitDirect);
  $('#exitCancelBtn')?.addEventListener('click', () => closeModal('exitModal'));
  $('#saveSettingsBtn')?.addEventListener('click', saveSettings);
  $('#testConnectionBtn')?.addEventListener('click', testConnection);
  $('#clearCacheBtn')?.addEventListener('click', clearCache);
  $('#clearKeyBtn')?.addEventListener('click', clearApiKey);
  $('#resetSettingsBtn')?.addEventListener('click', resetSettings);
  $('#toggleKeyBtn')?.addEventListener('click', () => {
    const input = $('#settingKey');
    input.type = input.type === 'password' ? 'text' : 'password';
    $('#toggleKeyBtn').textContent = input.type === 'password' ? '显示' : '隐藏';
  });
  $('#historyList')?.addEventListener('click', (event) => {
    const item = event.target.closest('[data-test-id]');
    if (item) openHistoryTest(item.dataset.testId);
  });
  $$('[data-close]').forEach((button) => button.addEventListener('click', () => closeModal(button.dataset.close)));
  $$('.modal').forEach((modal) => {
    modal.addEventListener('click', (event) => {
      if (event.target !== modal) return;
      if (modal.id === 'confirmModal') { resolveConfirm(false); return; }
      closeModal(modal.id);
    });
  });
  $('#confirmOk')?.addEventListener('click', () => resolveConfirm(true));
  $('#confirmCancel')?.addEventListener('click', () => resolveConfirm(false));
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (state.modalOpen === 'confirmModal') resolveConfirm(false);
    else if (state.modalOpen) closeModal(state.modalOpen);
  });
}

function setupDesktopBridge() {
  if (new URLSearchParams(location.search).get('embedded') !== '1') return;
  const button = $('#openBrowserBtn');
  if (!button) return;
  const bind = () => {
    if (!window.pywebview?.api?.open_browser) return;
    button.classList.remove('hidden');
    button.onclick = () => window.pywebview.api.open_browser();
  };
  bind();
  window.addEventListener('pywebviewready', bind);
}

async function boot() {
  bindEvents();
  setupDesktopBridge();
  try {
    const data = await api('/api/state');
    applyServerState(data, { first: true });
    renderHome();
    if (!state.config.has_key) showToast('先填写 DeepSeek API Key，再按模板 A 出卷', 'warn', 5600);
  } catch (error) {
    showToast(error.message || '应用启动失败，请刷新页面', 'err', 8000);
  }
}

document.addEventListener('DOMContentLoaded', boot);
