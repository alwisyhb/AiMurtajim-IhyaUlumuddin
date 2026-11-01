'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// ---------- storage (aman jika localStorage diblokir) ----------
const store = {
  get(k, d = '') { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* abaikan */ } },
};

const DEFAULT_SERVER = 'https://ai-murtajim-ihya-ulumuddin.vercel.app';
const HOME_VIEW = 'translate';
const EXIT_WINDOW_MS = 2000;
const SPLASH_MS = 2800;
const SPLASH_MAX_MS = 8000;
// Terukur untuk 806 huruf: terjemahan 42 detik, analisis 111 detik (batas server 240 detik).
const MAX_LETTERS = 800;
// Sedikit di atas batas waktu server, supaya pesan galat server yang tampil, bukan putus duluan.
const PROCESS_TIMEOUT_MS = 280000;
const SLOW_NOTICE_MS = 15000;

const PRESETS = [
  'طلب العلم فريضة على كل مسلم',
  'إنما الأعمال بالنيات وإنما لكل امرئ ما نوى',
  'العلم بلا عمل جنون والعمل بغير علم لا يكون',
  'قال تعالى يرفع الله الذين آمنوا منكم',
  'قد أفلح المؤمنون',
  'كاد الفقر أن يكون كفرا',
];
const SEARCH_EXAMPLES = ['العلم', 'النية', 'الصبر', 'الإخلاص'];
const SEARCH_EXAMPLES_HADITH = ['النية', 'الإيمان', 'الصلاة', 'الصبر'];
const DEFAULT_BOOK_ID = 'ihya';
// Dipakai sampai daftar dari server tiba
const BOOKS_FALLBACK = [
  { id: 'ihya', title: 'إحياء علوم الدين', title_latin: "Ihya' 'Ulum al-Din", navigation: 'page', default: true },
  { id: 'bukhari', title: 'صحيح البخاري', title_latin: 'Shahih al-Bukhari', navigation: 'hadith', default: false },
];
const BOOK_LABELS = { ihya: 'Ihya', bukhari: 'Bukhari' };
const BOOK_INFO = { ihya: 'Imam Al-Ghazali · 4 jilid · 1.706 halaman', bukhari: 'Imam Al-Bukhari · 9 jilid · 97 kitab · dibaca per hadis' };
const VIEW_TITLES = {
  translate: ['Al-Mutarjim', 'book'],
  search: ['Cari', 'book'],
  read: ['Baca', 'book'],
  settings: ['Setelan', ''],
};

const state = {
  server: store.get('server_url', DEFAULT_SERVER),
  apiKey: store.get('gemini_api_key'),
  autoProcess: store.get('auto_process', '1') === '1',
  fontSize: parseInt(store.get('arabic_font', '26'), 10),
  theme: store.get('theme', 'system'),
  view: HOME_VIEW,
  sheet: null,
  splashUp: true,
  lastBack: 0,
  books: BOOKS_FALLBACK,
  book: store.get('book', DEFAULT_BOOK_ID),
  bookChosen: false,
  volumes: [],
  kitabs: [],
  vol: 1, page: 1,
  pageKitab: null,
  hadith: null,
  hadithNumber: parseInt(store.get('last_hadith', '1'), 10) || 1,
  babsKitab: null,
  sourceBook: DEFAULT_BOOK_ID,
  data: null,
  tarkib: [],
  analysis: 'idle', // idle | loading | done | error
  analysisError: '',
  sourceText: '',
  parts: [],
  runId: 0,
  klasik: { angle: 25, script: 'latin', symbols: true },
  logatScript: 'latin',
  activeTab: 'indo',
};

// ---------- util ----------
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const withMarks = (s) => esc(String(s ?? '').replace(/<mark\b[^>]*>/gi, '<mark>')).replace(/&lt;(\/?)mark&gt;/g, '<$1mark>');
const native = (name) => window.Capacitor?.Plugins?.[name];

let toastTimer;
function toast(msg, kind = '', ms = 3000) {
  const t = $('#toast');
  t.hidden = true;
  void t.offsetWidth; // ulang animasi masuk
  t.textContent = msg;
  t.className = 'toast ' + kind;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

function apiUrl(path) {
  return state.server.replace(/\/+$/, '') + path;
}

async function api(path, opts = {}, timeoutMs = 70000) {
  if (!state.server) {
    switchView('settings');
    openSheet('advanced');
    throw new Error('Alamat server belum diisi.');
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(apiUrl(path), { ...opts, signal: ctl.signal });
    if (!res.ok) {
      let detail = `Server membalas ${res.status}`;
      try { detail = (await res.json()).detail || detail; } catch { /* bukan JSON */ }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return await res.json();
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('Server terlalu lama menjawab. Coba lagi.');
    if (e instanceof TypeError) throw new Error('Tidak bisa terhubung ke server. Periksa internetmu.');
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// ---------- tema ----------
function isDark() {
  return state.theme === 'dark' || (state.theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
}

function syncSystemBars() {
  // DARK = ikon bar terang. Selama splash latarnya gelap di kedua tema.
  const style = state.splashUp || isDark() ? 'DARK' : 'LIGHT';
  const color = state.splashUp ? '#2B3472' : getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
  try {
    native('SystemBars')?.setStyle({ style });
    native('WindowTheme')?.setBackground({ color });
  } catch { /* bukan di APK */ }
}

function applyTheme() {
  document.documentElement.dataset.theme = isDark() ? 'dark' : 'light';
  $$('#set-theme button').forEach((b) => b.classList.toggle('on', b.dataset.t === state.theme));
  syncSystemBars();
}

// ---------- navigasi ----------
function switchView(name) {
  state.view = name;
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + name));
  $$('.tabbar button').forEach((b) => b.classList.toggle('on', b.dataset.view === name));
  renderTopbar();
  $('#views').scrollTop = 0;
  if (name === 'read' && !$('#reader-box').children.length) loadCurrent();
}
$$('.tabbar button').forEach((b) => b.addEventListener('click', () => switchView(b.dataset.view)));

function openSheet(name) {
  if (state.sheet) closeSheet();
  state.sheet = name;
  $('#scrim').hidden = false;
  $('#sheet-' + name).hidden = false;
}

function closeSheet() {
  if (!state.sheet) return;
  $('#sheet-' + state.sheet).hidden = true;
  $('#scrim').hidden = true;
  state.sheet = null;
}

// Urutan: tutup sheet atau pilihan kitab, lalu kembali ke home, lalu dua kali ketuk untuk keluar.
function handleBack() {
  if (state.sheet) { closeSheet(); return; }
  const pickerOpen = !$('#book-picker').hidden;
  if (pickerOpen && state.bookChosen) { $('#book-picker').hidden = true; return; }
  if (!pickerOpen && state.view !== HOME_VIEW) { switchView(HOME_VIEW); return; }
  const now = Date.now();
  if (now - state.lastBack < EXIT_WINDOW_MS) {
    native('App')?.exitApp();
    return;
  }
  state.lastBack = now;
  toast('Ketuk sekali lagi untuk keluar', '', EXIT_WINDOW_MS);
}

function segment(rootSel, onPick) {
  const root = $(rootSel);
  root.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    $$('button', root).forEach((x) => x.classList.toggle('on', x === b));
    onPick(b);
  });
}

// ---------- splash ----------
function hideSplash() {
  if (!state.splashUp) return;
  state.splashUp = false;
  const s = $('#splash');
  s.classList.add('out');
  syncSystemBars();
  setTimeout(() => { s.hidden = true; }, 380);
}

// ---------- TERJEMAH ----------
// Bagi teks panjang jadi bagian yang seimbang. Teks kitab jarang bertanda baca, jadi
// urutan potongannya: akhir kalimat, koma, awal klausa (kata berawalan و/ف), lalu spasi.
function splitIntoParts(text, max = MAX_LETTERS) {
  const parts = [];
  let rest = text.trim();
  while (rest.length > max) {
    const target = Math.ceil(rest.length / Math.ceil(rest.length / max));
    const head = rest.slice(0, Math.min(max, target + 60));
    const from = target * 0.6;
    const lastOf = (re) => { let i = -1, m; while ((m = re.exec(head))) i = m.index; return i >= from ? i : -1; };
    let cut = lastOf(/[.؟?!؛:]/g);
    if (cut < 0) cut = lastOf(/[،,]/g);
    if (cut < 0) cut = lastOf(/\s(?=[وف])/g);
    if (cut < 0) cut = lastOf(/\s/g);
    if (cut < 0) cut = head.length - 1;
    parts.push(rest.slice(0, cut + 1).trim());
    rest = rest.slice(cut + 1).trim();
  }
  if (rest) parts.push(rest);
  return parts;
}

function updateCount() {
  const value = $('#arabic-input').value.trim();
  const n = value.length;
  const over = n > MAX_LETTERS;
  const el = $('#char-count');
  el.hidden = n === 0;
  el.classList.toggle('warn', over);
  el.textContent = over
    ? `${n} / ${MAX_LETTERS} huruf. Terlalu panjang, pilih salah satu bagian:`
    : `${n} / ${MAX_LETTERS} huruf`;

  if (over) state.parts = splitIntoParts(value);
  else if (!state.parts.includes(value)) state.parts = [];
  renderParts(value);
}

function renderParts(value) {
  const box = $('#parts');
  box.hidden = state.parts.length < 2;
  box.textContent = '';
  state.parts.forEach((part, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = `Bagian ${i + 1} · ${part.length} huruf`;
    b.classList.toggle('on', part === value);
    b.onclick = () => { $('#arabic-input').value = part; updateCount(); processText(); };
    box.appendChild(b);
  });
}

function renderPresets() {
  const box = $('#preset-chips');
  PRESETS.forEach((p) => {
    const b = document.createElement('button');
    b.textContent = p.split(' ').slice(0, 2).join(' ');
    b.onclick = () => { $('#arabic-input').value = p; updateCount(); processText(); };
    box.appendChild(b);
  });
}

async function processText() {
  const text = $('#arabic-input').value.trim();
  if (!text) return toast('Masukkan teks Arab dulu.');
  if (text.length > MAX_LETTERS) return toast(`Maksimal ${MAX_LETTERS} huruf. Pilih salah satu bagian.`, 'err');
  const btn = $('#btn-process');
  const label = $('#btn-process-text');
  btn.disabled = true;
  label.textContent = 'Sedang memproses…';
  $('#result').hidden = true;
  $('#home-intro').hidden = true;
  $('#result-skeleton').hidden = false;
  const run = ++state.runId;
  const slowTimer = setTimeout(() => { label.textContent = 'Teks panjang, bisa sampai beberapa menit…'; }, SLOW_NOTICE_MS);
  try {
    const data = await api('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        api_key: state.apiKey || null,
        model_name: 'gemini-3.5-flash',
        stage: 'core',
        book: state.book,
      }),
    }, PROCESS_TIMEOUT_MS);
    if (run !== state.runId) return;
    // Server lama bisa menaruh jawaban AI yang rusak ke kolom syakal dan melaporkannya sukses.
    if ((data.tashkil || '').length > text.length * 5 || (data.tashkil || '').startsWith('```')) {
      throw new Error('Hasil dari AI rusak. Silakan coba lagi, atau pilih bagian yang lebih pendek.');
    }
    $('#result-skeleton').hidden = true;
    state.sourceText = text;
    state.sourceBook = state.book;
    renderResult(data);
    // Server lama (atau hasil cache) mengirim paket lengkap; selainnya analisis dimuat terpisah.
    if (state.analysis !== 'done' && $('#auto-analysis').checked) loadAnalysis();
  } catch (e) {
    if (run !== state.runId) return;
    $('#result-skeleton').hidden = true;
    if (state.data) $('#result').hidden = false; else $('#home-intro').hidden = false;
    toast(e.message, 'err', 4500);
    if (e.status === 401) { switchView('settings'); openSheet('advanced'); }
  } finally {
    clearTimeout(slowTimer);
    btn.disabled = false;
    label.textContent = 'Beri Syakal & Terjemahkan';
  }
}

function renderResult(d) {
  state.data = d;
  $('#result').hidden = false;
  const tk = $('#tashkil');
  tk.textContent = d.tashkil || '';
  tk.style.fontSize = state.fontSize + 'px';

  $('#t-indo').textContent = d.translation_id || '';
  $('#t-lemes').textContent = d.translation_sunda_lemes || '';
  const latin = d.translation_sunda_logat || '';
  $('#t-logat').textContent = latin;
  $('#t-logat-pegon').textContent = d.translation_sunda_logat_pegon || sundaToPegonClient(latin);

  state.tarkib = d.tarkib_notes || [];
  state.analysis = state.tarkib.length ? 'done' : 'idle';
  state.analysisError = '';
  $('#tarkib-filter').value = '';
  renderKlasik();
  renderTarkib();
  applyLogatScript();
  $('#result').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Analisis i'rab dan makna miring diminta terpisah supaya terjemahan tampil cepat.
async function loadAnalysis() {
  if (!state.data || state.analysis === 'loading') return;
  const run = state.runId;
  state.analysis = 'loading';
  renderKlasik();
  renderTarkib();
  try {
    const r = await api('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: state.sourceText,
        api_key: state.apiKey || null,
        model_name: 'gemini-3.5-flash',
        stage: 'analysis',
        book: state.sourceBook,
        tashkil: state.data.tashkil,
        logat: state.data.translation_sunda_logat,
      }),
    }, PROCESS_TIMEOUT_MS);
    if (run !== state.runId) return;
    state.data.tarkib_notes = r.tarkib_notes || [];
    state.data.translation_sunda_klasik = r.translation_sunda_klasik || [];
    state.tarkib = state.data.tarkib_notes;
    state.analysis = 'done';
  } catch (e) {
    if (run !== state.runId) return;
    state.analysis = 'error';
    state.analysisError = e.message;
    toast(e.message, 'err', 4500);
  }
  renderKlasik();
  renderTarkib();
}

function analysisPlaceholder(box) {
  if (state.analysis === 'loading') {
    box.innerHTML = '<p class="hint center" dir="ltr">Menyusun analisis, teks panjang bisa beberapa menit…</p><div class="sk w60"></div><div class="sk w100"></div><div class="sk w80"></div>';
    return;
  }
  const failed = state.analysis === 'error';
  box.innerHTML = `<div class="cta${failed ? ' err' : ''}" dir="ltr">
    <p>${failed ? esc(state.analysisError) : 'Analisis i\'rab dan makna miring dimuat terpisah, supaya terjemahan cepat muncul.'}</p>
    <button class="btn primary small" data-load-analysis>${failed ? 'Coba lagi' : 'Muat analisis'}</button></div>`;
}

function applyLogatScript() {
  const s = state.logatScript;
  $('#t-logat').hidden = s === 'pegon';
  $('#t-logat-pegon').hidden = s === 'latin';
}

// Pecah makna panjang menjadi beberapa baris pendek agar tidak saling bertabrakan.
function wrapGloss(text, maxLen = 16) {
  const lines = [];
  text.split(/\s*\/\s*|\n/).filter(Boolean).forEach((part) => {
    let cur = '';
    part.split(/\s+/).forEach((word) => {
      if (cur && (cur + ' ' + word).length > maxLen) { lines.push(cur); cur = word; }
      else cur = cur ? cur + ' ' + word : word;
    });
    if (cur) lines.push(cur);
  });
  return lines;
}

function renderKlasik() {
  const flow = $('#klasik-flow');
  flow.textContent = '';
  if (state.data && state.analysis !== 'done') { analysisPlaceholder(flow); return; }
  const tokens = state.data?.translation_sunda_klasik || [];
  if (!tokens.length) {
    flow.innerHTML = '<p class="empty" dir="ltr">Makna miring belum tersedia.</p>';
    return;
  }
  const { angle, script, symbols } = state.klasik;
  tokens.forEach((it) => {
    const w = document.createElement('div');
    w.className = 'kw';
    const ar = document.createElement('div');
    ar.className = 'ar';
    ar.style.fontSize = state.fontSize + 'px';
    ar.textContent = it.word || '';
    w.appendChild(ar);

    const pegon = script === 'pegon';
    const raw = pegon ? (isArabicScript(it.pegon) ? it.pegon : sundaToPegonClient(it.sunda || '')) : (it.sunda || '');
    const lines = wrapGloss(raw);
    const gl = document.createElement('div');
    gl.className = 'gl' + (pegon ? ' peg' : '') + (angle ? '' : ' flat');
    gl.dir = pegon ? 'rtl' : 'ltr';
    if (angle) {
      gl.style.transform = `rotate(-${angle}deg)`;
      const longest = Math.max(1, ...lines.map((l) => l.length));
      const drop = Math.min(90, Math.max(18, longest * 6.2 * Math.sin(angle * Math.PI / 180)));
      gl.style.marginBottom = Math.round(drop) + 'px';
    }
    lines.forEach((l, i) => {
      const row = document.createElement('div');
      if (i === 0 && symbols && it.symbol && it.symbol !== '-') {
        const s = document.createElement('span');
        s.className = 'sym';
        s.textContent = it.symbol;
        row.appendChild(s);
      }
      row.appendChild(document.createTextNode(l));
      gl.appendChild(row);
    });
    w.appendChild(gl);
    flow.appendChild(w);
  });
}

function renderTarkib() {
  if (state.data && state.analysis !== 'done') {
    $('#tarkib-count').textContent = '';
    analysisPlaceholder($('#tarkib-list'));
    return;
  }
  const q = $('#tarkib-filter').value.trim().toLowerCase();
  const items = state.tarkib.filter((it) => !q || JSON.stringify(it).toLowerCase().includes(q));
  $('#tarkib-count').textContent = state.tarkib.length ? `${state.tarkib.length} kata` : '';
  const box = $('#tarkib-list');
  if (!items.length) { box.innerHTML = '<p class="empty">Tidak ada catatan.</p>'; return; }
  box.innerHTML = items.map((it) => {
    if (typeof it === 'string') it = { word: it.split(' ')[0], note: it };
    const sym = it.symbol && it.symbol !== '-' ? `<span class="sym">${esc(it.symbol)}</span>` : '';
    return `<details class="tk">
      <summary>
        <svg class="i"><use href="#i-chev-down"/></svg>
        <span class="tk-pos">${sym}${esc(it.position || 'Nahwu')}</span>
        <span class="tk-word" dir="rtl">${esc(it.word)}</span>
      </summary>
      <dl>
        ${it.sunda ? `<dt>Logat</dt><dd>${esc(it.sunda)}</dd>` : ''}
        ${it.i_rab ? `<dt>I'rab</dt><dd>${esc(it.i_rab)}</dd>` : ''}
        ${it.shorof ? `<dt>Shorof</dt><dd dir="auto">${esc(it.shorof)}</dd>` : ''}
        ${it.note ? `<dd class="note">${esc(it.note)}</dd>` : ''}
      </dl></details>`;
  }).join('');
}

function activeTranslationText() {
  const d = state.data || {};
  return { indo: d.translation_id, lemes: d.translation_sunda_lemes, logat: d.translation_sunda_logat,
    klasik: (d.translation_sunda_klasik || []).map((t) => `${t.word}: ${t.sunda}`).join('\n') }[state.activeTab] || '';
}

async function copyText(text) {
  if (!text) return toast('Belum ada teks.');
  try { await navigator.clipboard.writeText(text); toast('Tersalin', 'ok', 1500); }
  catch { toast('Gagal menyalin', 'err'); }
}

function bindTranslate() {
  renderPresets();
  $('#btn-process').onclick = processText;
  $('#btn-clear').onclick = () => { $('#arabic-input').value = ''; updateCount(); $('#arabic-input').focus(); };
  $('#arabic-input').addEventListener('input', updateCount);
  $('#auto-analysis').checked = store.get('auto_analysis', '0') === '1';
  $('#auto-analysis').onchange = (e) => store.set('auto_analysis', e.target.checked ? '1' : '0');
  document.addEventListener('click', (e) => { if (e.target.closest('[data-load-analysis]')) loadAnalysis(); });
  segment('#trans-tabs', (b) => {
    state.activeTab = b.dataset.tab;
    ['indo', 'lemes', 'logat', 'klasik'].forEach((t) => { $('#pane-' + t).hidden = t !== state.activeTab; });
  });
  segment('#logat-script', (b) => { state.logatScript = b.dataset.s; applyLogatScript(); });
  segment('#klasik-angle', (b) => { state.klasik.angle = +b.dataset.a; renderKlasik(); });
  segment('#klasik-script', (b) => { state.klasik.script = b.dataset.s; renderKlasik(); });
  $('#klasik-sym').onchange = (e) => { state.klasik.symbols = e.target.checked; renderKlasik(); };
  $('#tarkib-filter').oninput = renderTarkib;
  $('#btn-copy-trans').onclick = () => copyText(activeTranslationText());
  $$('[data-font]').forEach((b) => b.onclick = () => {
    state.fontSize = Math.min(48, Math.max(18, state.fontSize + +b.dataset.font));
    store.set('arabic_font', state.fontSize);
    $('#tashkil').style.fontSize = state.fontSize + 'px';
    renderKlasik();
  });
  $('[data-copy="tashkil"]').onclick = () => copyText(state.data?.tashkil);
}

// ---------- KITAB ----------
const bookCfg = () => state.books.find((b) => b.id === state.book) || state.books[0];
const isHadithBook = () => bookCfg().navigation === 'hadith';
const withBook = (path) => `${path}${path.includes('?') ? '&' : '?'}book=${encodeURIComponent(state.book)}`;
const bookLabel = (b) => BOOK_LABELS[b.id] || b.title_latin;
const readJson = (key, fallback) => { try { return JSON.parse(store.get(key, '')) || fallback; } catch { return fallback; } };

function renderBookCards() {
  const usedBefore = store.get('book') !== '';
  $('#book-cards').innerHTML = state.books.map((b) => `
    <button type="button" class="book-card" data-book="${esc(b.id)}">
      <span class="ar" dir="rtl">${esc(b.title)}</span>
      <span class="lat">${esc(b.title_latin)}</span>
      <span class="info">${esc(BOOK_INFO[b.id] || '')}</span>
      ${usedBefore && b.id === state.book ? '<span class="last">Terakhir dibuka</span>' : ''}
    </button>`).join('');
  $('#current-book').textContent = bookLabel(bookCfg());
}

const isTranslating = () => $('#btn-process').disabled || state.analysis === 'loading';

function openBookPicker() {
  if (isTranslating()) { toast('Tunggu terjemahan selesai dulu.'); return; }
  renderBookCards();
  $('#book-picker').hidden = false;
}

function chooseBook(id) {
  store.set('book', id);
  state.bookChosen = true;
  $('#book-picker').hidden = true;
  if (id !== state.book) setBook(id);
  switchView(HOME_VIEW);
}

// Teks dan hasil milik kitab sebelumnya tidak boleh terbawa ke kaidah kitab yang baru
function resetTranslate() {
  state.runId++;
  state.data = null;
  state.parts = [];
  state.tarkib = [];
  state.analysis = 'idle';
  $('#arabic-input').value = '';
  updateCount();
  $('#result').hidden = true;
  $('#result-skeleton').hidden = true;
  $('#home-intro').hidden = false;
}

function renderTopbar() {
  const [title, sub] = VIEW_TITLES[state.view];
  $('#top-title').textContent = title;
  $('#top-sub').textContent = sub === 'book' ? bookCfg().title_latin : sub;
  $('#top-sub').hidden = !sub;
}

function setBook(id) {
  if (id === state.book || !state.books.some((b) => b.id === id)) return;
  state.book = id;
  store.set('book', id);
  resetTranslate();
  renderBookCards();
  renderTopbar();
  searchVol = '';
  applyBookLayout();
  $('#reader-box').textContent = '';
  $('#reader-meta').textContent = '';
  $('#search-q').value = '';
  renderSearchEmpty();
  loadVolumes();
  loadKitabs().then(() => { if (state.view === 'read') loadCurrent(); });
}

// Bagian layar yang berbeda antara kitab per halaman dan kitab per hadis
function applyBookLayout() {
  const hadith = isHadithBook();
  $('.read-controls').classList.toggle('hadith', hadith);
  $('#sel-vol').hidden = hadith;
  $('#sel-bab').hidden = !hadith;
  $('#reader-bab').hidden = !hadith;
  $('#reader-source').hidden = true;
  $('#reader-hint').textContent = hadith ? 'Ketuk hadis untuk menerjemahkannya.' : 'Ketuk paragraf untuk menerjemahkannya.';
  $('#presets-box').hidden = state.book !== DEFAULT_BOOK_ID;
  $('#search-q').placeholder = hadith ? 'Cari kata atau nomor hadis' : 'Cari kata di kitab ini';
  renderVolumeControls();
}

// ---------- CARI ----------
let searchVol = '';

function renderSearchEmpty() {
  const box = $('#search-results');
  const hadith = isHadithBook();
  const words = hadith ? SEARCH_EXAMPLES_HADITH : SEARCH_EXAMPLES;
  box.innerHTML = `<div class="empty">${hadith ? 'Tulis kata Arab atau nomor hadis, atau coba salah satu ini:' : 'Tulis kata Arab, atau coba salah satu ini:'}
    <div class="chips">${words.map((w) => `<button type="button">${esc(w)}</button>`).join('')}</div></div>`;
  $$('button', box).forEach((b) => b.onclick = () => { $('#search-q').value = b.textContent; runSearch(); });
}

const hadithLabel = (r) => (r.number_end > r.number ? `Hadis ${r.number}–${r.number_end}` : `Hadis ${r.number}`);

async function runSearch() {
  const q = $('#search-q').value.trim();
  const box = $('#search-results');
  if (q.length < 2 && !/^\d+$/.test(q)) return toast('Minimal 2 huruf.');
  $('#search-q').blur();
  const hadith = isHadithBook();
  box.innerHTML = '<div class="card"><div class="sk w40"></div><div class="sk w100"></div><div class="sk w80"></div></div>';
  try {
    const res = await api(withBook(`/api/search?q=${encodeURIComponent(q)}&limit=30${searchVol ? '&vol=' + searchVol : ''}`));
    if (!res.length) { box.innerHTML = `<p class="empty">Tidak ada hasil untuk “${esc(q)}”.</p>`; return; }
    box.innerHTML = res.map((r, i) => `
      <div class="res" data-i="${i}">
        <div class="res-head"><b>${hadith ? hadithLabel(r) : `Jilid ${r.volume} · Hal ${r.volume_page}`}</b><span dir="rtl">${esc(r.kitab_title || '')}</span></div>
        <div class="res-ex">${withMarks(r.excerpt)}</div>
      </div>`).join('') + (res.length >= 30 ? '<p class="hint center">Menampilkan 30 hasil pertama. Tambah kata supaya lebih spesifik.</p>' : '');
    $$('.res', box).forEach((el) => el.onclick = () => {
      const r = res[+el.dataset.i];
      if (hadith) openHadith(r.number); else openReader(r.volume, r.volume_page);
    });
    $('#views').scrollTop = 0;
  } catch (err) {
    box.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
  }
}

// ---------- BACA ----------
function rangeOf(v) {
  const entry = state.volumes.find((x) => x.volume_number === v);
  return entry ? [entry.min_vol_page, entry.max_vol_page] : [1, Number.MAX_SAFE_INTEGER];
}

function renderVolumeControls() {
  const sel = $('#sel-vol');
  const vols = state.volumes;
  sel.innerHTML = (vols.length ? vols.map((v) => v.volume_number) : [state.vol])
    .map((v) => `<option value="${v}">Jilid ${v}</option>`).join('');
  sel.value = state.vol;
  // Bukhari punya 9 jilid dan dicari lewat kitab atau nomor, jadi saringan jilid hanya untuk kitab per halaman
  const seg = $('#search-vol');
  seg.hidden = isHadithBook();
  if (!isHadithBook()) {
    seg.innerHTML = `<button data-v="" class="${searchVol ? '' : 'on'}">Semua</button>`
      + vols.map((v) => `<button data-v="${v.volume_number}" class="${String(v.volume_number) === searchVol ? 'on' : ''}">Jilid ${v.volume_number}</button>`).join('');
  }
}

async function loadVolumes() {
  const book = state.book;
  state.volumes = readJson(`volumes_${book}`, []);
  renderVolumeControls();
  try {
    const vols = await api(withBook('/api/volumes'));
    if (book !== state.book) return;
    state.volumes = vols;
    store.set(`volumes_${book}`, JSON.stringify(vols));
    renderVolumeControls();
    fillKitabs();
  } catch { /* tetap memakai salinan terakhir */ }
}

function fillKitabs() {
  const sel = $('#sel-kitab');
  if (isHadithBook()) {
    sel.innerHTML = state.kitabs.length
      ? state.kitabs.map((k) => `<option value="${k.first_hadith}" data-id="${k.id}">${k.id}. ${esc(k.title)}</option>`).join('')
      : '<option>—</option>';
    if (state.hadith) syncHadithControls(state.hadith);
    return;
  }
  const list = state.kitabs.filter((k) => k.volume_number === state.vol);
  sel.innerHTML = list.length
    ? list.map((k) => `<option value="${k.start_vol_page}" data-id="${k.id}">${esc(k.title_short || k.title_full)}</option>`).join('')
    : '<option>—</option>';
  sel.insertAdjacentHTML('beforeend', '<option id="kitab-other" hidden disabled></option>');
  const [min, max] = rangeOf(state.vol);
  $('#pg-total').textContent = max === Number.MAX_SAFE_INTEGER ? '' : '/ ' + max;
  $('#pg-input').min = min; $('#pg-input').max = max;
  syncKitabSelect();
}

// Muqaddimah tidak ada di daftar kitab, jadi namanya ditampilkan lewat opsi cadangan.
function syncKitabSelect() {
  if (!state.pageKitab) return;
  const { id, title } = state.pageKitab;
  const opt = $(`#sel-kitab option[data-id="${id}"]`);
  if (opt) {
    $('#sel-kitab').value = opt.value;
  } else {
    const other = $('#kitab-other');
    if (!other) return;
    other.textContent = title || '';
    other.selected = true;
  }
}

function loadCurrent() {
  if (isHadithBook()) return loadHadith(state.hadithNumber);
  return loadPage(state.vol, state.page);
}

function sendToTranslate(text, what) {
  // Teks panjang langsung dibagi, supaya bagian pertama yang diproses.
  const parts = splitIntoParts(text);
  state.parts = parts;
  $('#arabic-input').value = parts[0];
  updateCount();
  switchView(HOME_VIEW);
  if (parts.length > 1) toast(`${what} dibagi jadi ${parts.length} bagian`, '', 2500);
  if (state.autoProcess) processText();
  else toast(`${what} masuk ke kotak terjemah.`);
}

async function openReader(vol, page) {
  state.vol = vol;
  $('#sel-vol').value = vol;
  fillKitabs();
  state.page = page;
  $('#reader-box').innerHTML = '<div class="state">Memuat…</div>';
  switchView('read');
  await loadPage(vol, page);
}

async function loadPage(vol, page) {
  const box = $('#reader-box');
  box.innerHTML = '<div class="state">Memuat…</div>';
  try {
    const d = await api(withBook(`/api/page?vol=${vol}&page=${page}`));
    state.vol = d.volume; state.page = d.volume_page;
    store.set('last_read', JSON.stringify([state.vol, state.page]));
    $('#pg-input').value = d.volume_page;
    const [min, max] = [d.min_vol_page ?? rangeOf(vol)[0], d.max_vol_page ?? rangeOf(vol)[1]];
    $('#pg-prev').disabled = d.volume_page <= min;
    $('#pg-next').disabled = d.volume_page >= max;
    $('#pg-total').textContent = '/ ' + max;
    state.pageKitab = { id: d.kitab_id, title: d.kitab_title };
    syncKitabSelect();
    $('#reader-meta').innerHTML = [`Jilid ${d.volume} · Hal ${d.volume_page}`, d.bab_title || d.fasal_title || d.kitab_title]
      .filter(Boolean).map((t) => `<span>${esc(t)}</span>`).join('');
    box.textContent = '';
    (d.content_clean || '').split(/\n+/).filter((p) => p.trim()).forEach((t) => {
      const p = document.createElement('p');
      p.textContent = t;
      p.onclick = () => {
        p.classList.add('sel');
        setTimeout(() => p.classList.remove('sel'), 400);
        sendToTranslate(t, 'Paragraf');
      };
      box.appendChild(p);
    });
    $('#views').scrollTop = 0;
  } catch (e) {
    box.innerHTML = `<div class="state">${esc(e.message)}</div>`;
  }
}

async function openHadith(number) {
  state.hadithNumber = number;
  $('#reader-box').innerHTML = '<div class="state">Memuat…</div>';
  switchView('read');
  await loadHadith(number);
}

async function loadBabs(kitabId) {
  const sel = $('#sel-bab');
  if (state.babsKitab === kitabId) return;
  state.babsKitab = kitabId;
  sel.innerHTML = '<option>Memuat bab…</option>';
  try {
    const babs = await api(withBook(`/api/babs?kitab=${kitabId}`));
    if (state.babsKitab !== kitabId) return;
    const withHadith = babs.filter((b) => b.hadith_count > 0);
    sel.innerHTML = withHadith.map((b) => `<option value="${b.first_hadith}" data-id="${b.id}">${esc(b.title)}</option>`).join('');
    if (state.hadith) syncHadithControls(state.hadith);
  } catch {
    state.babsKitab = null;
    sel.innerHTML = '<option>—</option>';
  }
}

function syncHadithControls(d) {
  const kitab = $(`#sel-kitab option[data-id="${d.kitab_id}"]`);
  if (kitab) $('#sel-kitab').value = kitab.value;
  const bab = $(`#sel-bab option[data-id="${d.bab_id}"]`);
  if (bab) $('#sel-bab').value = bab.value;
  loadBabs(d.kitab_id);
}

async function loadHadith(number) {
  const box = $('#reader-box');
  box.innerHTML = '<div class="state">Memuat…</div>';
  try {
    const d = await api(withBook(`/api/hadith?number=${number}`));
    state.hadith = d;
    state.hadithNumber = d.number;
    store.set('last_hadith', String(d.number));
    $('#pg-input').value = d.number;
    $('#pg-input').min = 1; $('#pg-input').max = d.last_number;
    $('#pg-total').textContent = '/ ' + d.last_number;
    $('#pg-prev').disabled = d.prev_number == null;
    $('#pg-next').disabled = d.next_number == null;
    syncHadithControls(d);
    $('#reader-meta').innerHTML = [`${hadithLabel(d)} · Jilid ${d.volume}`, d.kitab_title].map((t) => `<span>${esc(t)}</span>`).join('');
    $('#reader-bab').textContent = d.bab_title || '';
    $('#reader-bab').hidden = !d.bab_title;
    $('#reader-source').hidden = d.source === 'shamela';
    box.textContent = '';
    d.text.split(/\n+/).filter((p) => p.trim()).forEach((t) => {
      const p = document.createElement('p');
      p.textContent = t;
      p.onclick = () => {
        $$('p', box).forEach((x) => x.classList.add('sel'));
        setTimeout(() => $$('p', box).forEach((x) => x.classList.remove('sel')), 400);
        sendToTranslate(d.text.replace(/\n+/g, ' '), 'Hadis');
      };
      box.appendChild(p);
    });
    $('#views').scrollTop = 0;
  } catch (e) {
    box.innerHTML = `<div class="state">${esc(e.message)}</div>`;
  }
}

function bindReader() {
  $('#book-cards').addEventListener('click', (e) => {
    const b = e.target.closest('.book-card');
    if (b) chooseBook(b.dataset.book);
  });
  $('#btn-change-book').onclick = openBookPicker;
  $('#sel-vol').onchange = () => {
    state.vol = +$('#sel-vol').value;
    fillKitabs();
    const first = state.kitabs.find((k) => k.volume_number === state.vol);
    loadPage(state.vol, first ? first.start_vol_page : rangeOf(state.vol)[0]);
  };
  $('#sel-kitab').onchange = () => {
    if (isHadithBook()) loadHadith(+$('#sel-kitab').value);
    else loadPage(state.vol, +$('#sel-kitab').value);
  };
  $('#sel-bab').onchange = () => loadHadith(+$('#sel-bab').value);
  $('#pg-prev').onclick = () => {
    if (isHadithBook()) loadHadith(state.hadith?.prev_number ?? 1);
    else loadPage(state.vol, state.page - 1);
  };
  $('#pg-next').onclick = () => {
    if (isHadithBook()) loadHadith(state.hadith?.next_number ?? state.hadithNumber);
    else loadPage(state.vol, state.page + 1);
  };
  $('#pg-input').onchange = () => {
    const typed = parseInt($('#pg-input').value, 10);
    if (isHadithBook()) {
      const last = state.hadith?.last_number ?? typed;
      loadHadith(Math.min(last, Math.max(1, typed || 1)));
      return;
    }
    const [min, max] = rangeOf(state.vol);
    loadPage(state.vol, Math.min(max, Math.max(min, typed || min)));
  };
}

async function loadKitabs() {
  const book = state.book;
  state.babsKitab = null;
  state.kitabs = readJson(`kitabs_${book}`, []);
  fillKitabs();
  try {
    const kitabs = await api(withBook('/api/kitabs'));
    if (book !== state.book) return;
    state.kitabs = kitabs;
    store.set(`kitabs_${book}`, JSON.stringify(kitabs));
    fillKitabs();
  } catch { /* tetap memakai salinan terakhir */ }
}

async function loadBooks() {
  try {
    const books = await api('/api/books');
    state.books = books;
    store.set('books_cache', JSON.stringify(books));
    renderBookCards();
    renderTopbar();
    applyBookLayout();
  } catch { /* tetap memakai salinan terakhir */ }
}

// ---------- SETELAN ----------
async function checkServer() {
  const msg = $('#server-status');
  msg.textContent = 'Menghubungkan…';
  try {
    await api('/api/status', {}, 12000);
    msg.textContent = '✓ Terhubung';
    return true;
  } catch (e) {
    msg.textContent = e.message;
    return false;
  }
}

function bindSettings() {
  $('#set-server').value = state.server;
  $('#set-key').value = state.apiKey;
  $('#set-auto').checked = state.autoProcess;
  $('#set-auto').onchange = (e) => { state.autoProcess = e.target.checked; store.set('auto_process', e.target.checked ? '1' : '0'); };

  segment('#set-theme', (b) => {
    state.theme = b.dataset.t;
    store.set('theme', state.theme);
    applyTheme();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);

  $$('[data-sheet]').forEach((b) => b.onclick = () => openSheet(b.dataset.sheet));
  $$('[data-close]').forEach((b) => b.onclick = closeSheet);
  $('#scrim').onclick = closeSheet;

  $('#btn-save-server').onclick = async () => {
    const url = $('#set-server').value.trim().replace(/\/+$/, '') || DEFAULT_SERVER;
    const devHost = /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(url);
    if (!devHost && !/^https:\/\//i.test(url)) {
      $('#server-status').textContent = 'Alamat harus diawali https://';
      return;
    }
    $('#set-server').value = url;
    state.server = url;
    store.set('server_url', url);
    if (await checkServer()) loadKitabs();
  };

  $('#btn-save-key').onclick = () => {
    state.apiKey = $('#set-key').value.trim();
    store.set('gemini_api_key', state.apiKey);
    $('#key-status').textContent = state.apiKey ? '✓ Tersimpan di HP ini' : 'Kunci dihapus';
  };

  $('#btn-test-key').onclick = async () => {
    const key = $('#set-key').value.trim();
    const out = $('#key-status');
    if (!key) { out.textContent = 'Isi kuncinya dulu.'; return; }
    out.textContent = 'Menguji…';
    try {
      const r = await api('/api/verify-key', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key }),
      }, 30000);
      out.textContent = r.valid === false ? (r.message || r.detail || 'Kunci tidak valid') : '✓ Kunci valid';
    } catch (e) { out.textContent = e.message; }
  };
}

// ---------- init ----------
(function init() {
  bindTranslate();
  bindReader();
  bindSettings();
  applyTheme();
  segment('#search-vol', (b) => { searchVol = b.dataset.v; if ($('#search-q').value.trim().length >= 2) runSearch(); });
  $('#search-form').addEventListener('submit', (e) => { e.preventDefault(); runSearch(); });
  renderSearchEmpty();

  native('App')?.addListener('backButton', handleBack);

  // Keyboard terbuka membuat tinggi jendela menyusut: sembunyikan bilah tab agar ruang isi lebih lega.
  let fullHeight = window.innerHeight;
  window.addEventListener('resize', () => {
    fullHeight = Math.max(fullHeight, window.innerHeight);
    document.body.classList.toggle('kb-open', window.innerHeight < fullHeight * 0.8);
  });

  $('#splash').onclick = hideSplash;
  // Hitung mundur baru mulai setelah layar benar-benar tergambar, supaya pesannya sempat terbaca di HP lambat.
  requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(hideSplash, SPLASH_MS)));
  setTimeout(hideSplash, SPLASH_MAX_MS);

  try { const [v, p] = JSON.parse(store.get('last_read', '[1,1]')); state.vol = v; state.page = p; } catch { /* default */ }
  state.books = readJson('books_cache', BOOKS_FALLBACK);
  if (!state.books.some((b) => b.id === state.book)) state.book = DEFAULT_BOOK_ID;
  renderBookCards();
  renderTopbar();
  applyBookLayout();
  loadBooks();
  loadVolumes();
  loadKitabs();
})();
