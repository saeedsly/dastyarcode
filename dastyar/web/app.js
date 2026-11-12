/* ============================================================
   دستیار — Dastyar UI logic (vanilla JS, no build step)
   ============================================================ */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html !== undefined) n.innerHTML = html;
    return n;
  };

  const state = {
    settings: {},
    providers: {},
    dataDir: '', 
    busy: false,
    attachments: [],
    es: null,
    streamingEl: null,
    tools: [],
    pendingConfirm: null,
  };

  /* ---------------- theme ---------------- */
  const savedTheme = localStorage.getItem('dastyar-theme');
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  else document.documentElement.dataset.theme =
    window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  $('#themeBtn').textContent = document.documentElement.dataset.theme === 'light' ? '☀️' : '🌙';
  $('#themeBtn').onclick = () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('dastyar-theme', next);
    $('#themeBtn').textContent = next === 'light' ? '☀️' : '🌙';
  };

  /* ---------------- api ---------------- */
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (res.status === 401) {
      toast('کد دسترسی لازم است — صفحه را دوباره باز کن', 'err');
    }
    const ct = res.headers.get('content-type') || '';
    if (!ct.includes('json')) return res.text();
    return res.json();
  }

  function toast(msg, kind = '') {
    const t = el('div', `toast ${kind}`, escapeHtml(msg));
    $('#toasts').appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, 3600);
  }

  /* ---------------- markdown (tiny, safe) ---------------- */
  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function inlineMd(text) {
    let t = escapeHtml(text);
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
    t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    t = t.replace(/(^|\s)(https?:\/\/[^\s<]+)/g,
      '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    return t;
  }
  function renderMarkdown(src) {
    const lines = String(src || '').replace(/\r/g, '').split('\n');
    let out = [], inCode = false, codeBuf = [], listType = null, tableBuf = [];
    const flushList = () => { if (listType) { out.push(`</${listType}>`); listType = null; } };
    const flushTable = () => {
      if (!tableBuf.length) return;
      const head = tableBuf[0];
      const body = tableBuf.slice(1).filter(r => !r.every(c => /^:?-{2,}:?$/.test(c.trim())));
      out.push('<table><thead><tr>' + head.map(c => `<th>${inlineMd(c)}</th>`).join('') + '</tr></thead><tbody>');
      body.forEach(r => out.push('<tr>' + r.map(c => `<td>${inlineMd(c)}</td>`).join('') + '</tr>'));
      out.push('</tbody></table>');
      tableBuf = [];
    };
    for (const raw of lines) {
      const line = raw.replace(/\s+$/, '');
      if (/^```/.test(line.trim())) {
        if (inCode) { out.push(`<pre><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`); codeBuf = []; inCode = false; }
        else { flushList(); flushTable(); inCode = true; }
        continue;
      }
      if (inCode) { codeBuf.push(raw); continue; }
      if (/^\s*\|.*\|\s*$/.test(line)) { flushList(); tableBuf.push(line.trim().replace(/^\||\|$/g, '').split('|').map(s => s.trim())); continue; }
      flushTable();
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) { flushList(); out.push(`<h${h[1].length}>${inlineMd(h[2])}</h${h[1].length}>`); continue; }
      const ul = line.match(/^\s*[-*+•]\s+(.*)$/);
      if (ul) { if (listType !== 'ul') { flushList(); out.push('<ul>'); listType = 'ul'; } out.push(`<li>${inlineMd(ul[1])}</li>`); continue; }
      const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (ol) { if (listType !== 'ol') { flushList(); out.push('<ol>'); listType = 'ol'; } out.push(`<li>${inlineMd(ol[1])}</li>`); continue; }
      flushList();
      if (!line.trim()) { out.push(''); continue; }
      if (/^&gt;|^>\s?/.test(line)) { out.push(`<blockquote>${inlineMd(line.replace(/^>\s?/, ''))}</blockquote>`); continue; }
      if (/^---+\s*$/.test(line)) { out.push('<hr>'); continue; }
      out.push(`<p>${inlineMd(line)}</p>`);
    }
    if (inCode) out.push(`<pre><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`);
    flushList(); flushTable();
    return out.join('\n');
  }

  /* ---------------- view switching ---------------- */
  const viewTitles = { chat: 'گفت‌وگو', notes: 'یادداشت‌ها', tools: 'ابزارها', skills: 'مهارت‌ها', memory: 'حافظه', settings: 'تنظیمات' };
  function switchView(name) {
    $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
    $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === name));
    $('#viewTitle').textContent = viewTitles[name] || '';
    $('#sidebar').classList.remove('open');
    if (name === 'notes') loadNotes();
    if (name === 'tools') loadTools();
    if (name === 'memory') loadMemory();
  }
  $$('.nav-item').forEach(b => b.onclick = () => switchView(b.dataset.view));
  $('#openSidebar').onclick = () => $('#sidebar').classList.add('open');
  $('#closeSidebar').onclick = () => $('#sidebar').classList.remove('open');

  /* ---------------- messages ---------------- */
  const messagesEl = $('#messages');
  const scrollEl = $('#chatScroll');

  function scrollDown(force = false) {
    const nearBottom = scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 220;
    if (force || nearBottom) scrollEl.scrollTop = scrollEl.scrollHeight;
  }

  function addMessage(role, content, opts = {}) {
    $('#welcome').style.display = 'none';
    const wrap = el('div', `msg ${role}`);
    const avatar = el('div', 'avatar', role === 'user' ? '🙂' : '🤖');
    const bubble = el('div', 'bubble');
    bubble.innerHTML = role === 'user' ? inlineMd(content).replace(/\n/g, '<br>') : renderMarkdown(content);
    wrap.append(avatar, bubble);
    if (opts.attach && opts.attach.length) bubble.appendChild(renderAttachments(opts.attach));
    messagesEl.appendChild(wrap);
    scrollDown(true);
    return { wrap, bubble };
  }

  function renderAttachments(list) {
    const box = el('div', 'attach-grid');
    list.forEach(a => {
      const path = typeof a === 'string' ? a : a.path;
      if (!path) return;
      if (/\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(path)) {
        const img = el('img');
        img.src = '/file/' + encodeURI(path.replace(/^\//, ''));
        img.loading = 'lazy';
        img.onclick = () => { $('#lightboxImg').src = img.src; $('#lightbox').hidden = false; };
        box.appendChild(img);
      } else {
        const f = el('div', 'attach-file');
        f.innerHTML = `<span>📄</span><span class="name">${escapeHtml(path.split(/[\\/]/).pop())}</span>`;
        f.onclick = () => openFile(path);
        box.appendChild(f);
      }
    });
    return box;
  }

  function addTyping() {
    const { wrap, bubble } = addMessage('assistant', '');
    bubble.innerHTML = '<div class="typing"><i></i><i></i><i></i></div>';
    return { wrap, bubble };
  }

  function addToolCard(name, args) {
    const wrap = el('div', 'msg assistant');
    wrap.appendChild(el('div', 'avatar', '🧰'));
    const box = el('div', 'tool-card');
    box.innerHTML = `<span class="spin">⚙️</span><span class="t-name">${escapeHtml(name)}</span>
      <span class="t-status">در حال اجرا…</span>`;
    if (args && Object.keys(args).length) {
      const d = el('details');
      d.innerHTML = `<summary>پارامترها</summary><pre>${escapeHtml(JSON.stringify(args, null, 1))}</pre>`;
      box.appendChild(d);
    }
    wrap.appendChild(box);
    messagesEl.appendChild(wrap);
    scrollDown();
    return box;
  }

  /* ---------------- send ---------------- */
  const input = $('#input');
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(180, input.scrollHeight) + 'px';
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $('#sendBtn').onclick = send;
  $('#newChatBtn').onclick = async () => {
    await api('/api/reset', { method: 'POST', body: {} });
    messagesEl.innerHTML = '';
    $('#welcome').style.display = '';
    state.attachments = [];
    renderAttachPreview();
    toast('گفت‌وگوی جدید شروع شد', 'ok');
  };
  $('#stopBtn').onclick = async () => { await api('/api/stop', { method: 'POST', body: {} }); };

  async function send() {
    const text = input.value.trim();
    if ((!text && !state.attachments.length) || state.busy) return;
    input.value = '';
    input.style.height = 'auto';
    const attachments = state.attachments.slice();
    state.attachments = [];
    renderAttachPreview();
    addMessage('user', text || '📎 پیوست', { attach: attachments });
    setBusy(true);
    if (!typingRef) typingRef = addTyping();
    try {
      const res = await api('/api/chat', { method: 'POST', body: { message: text, attachments } });
      if (res && res.error) toast(res.error, 'err');
    } catch (err) {
      toast('ارتباط با سرور قطع شد: ' + err.message, 'err');
    } finally {
      setBusy(false);
    }
  }

  function setBusy(b) {
    state.busy = b;
    $('#sendBtn').disabled = b;
    $('#stopBtn').hidden = !b;
    if (!b && state.streamingEl) { state.streamingEl = null; }
  }

  /* ---------------- SSE ---------------- */
  function connectEvents() {
    if (state.es) state.es.close();
    const es = new EventSource('/api/events', { withCredentials: true });
    state.es = es;
    es.onopen = () => setStatus(true, 'متصل');
    es.onerror = () => setStatus(false, 'قطع شد — تلاش مجدد…');
    es.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }
      handleEvent(data);
    };
  }

  function setStatus(ok, text) {
    const pill = $('#statusPill');
    pill.classList.toggle('ok', ok);
    pill.classList.toggle('bad', !ok);
    pill.querySelector('span').textContent = text;
  }

  let typingRef = null;
  function handleEvent(ev) {
    switch (ev.type) {
      case 'thinking': {
        if (!typingRef) typingRef = addTyping();
        scrollDown();
        break;
      }
      case 'assistant_delta': {
        if (typingRef) { typingRef.bubble.innerHTML = ''; state.streamingEl = typingRef.bubble; typingRef = null; }
        if (!state.streamingEl) {
          const m = addMessage('assistant', '');
          state.streamingEl = m.bubble;
        }
        state.streamingEl._raw = (state.streamingEl._raw || '') + ev.text;
        state.streamingEl.innerHTML = renderMarkdown(state.streamingEl._raw);
        state.streamingEl.classList.add('cursor-blink');
        scrollDown();
        break;
      }
      case 'assistant_message': {
        const target = state.streamingEl || (typingRef && typingRef.bubble);
        if (target) {
          target._raw = ev.content || target._raw || '';
          target.innerHTML = renderMarkdown(target._raw) || '';
          target.classList.remove('cursor-blink');
          attachActions(target.parentElement, target._raw);
        } else if (ev.content) {
          const m = addMessage('assistant', ev.content);
          attachActions(m.wrap, ev.content);
        }
        state.streamingEl = null;
        typingRef = null;
        scrollDown();
        break;
      }
      case 'tool_start': {
        if (typingRef) { typingRef.bubble.innerHTML = ''; typingRef = null; }
        const card = addToolCard(ev.tool, ev.args);
        state._cards = state._cards || [];
        state._cards.push({ name: ev.tool, node: card });
        break;
      }
      case 'tool_end': {
        const cards = (state._cards || []).filter(c => c.name === ev.tool && !c.done);
        const card = cards[cards.length - 1];
        if (card) {
          card.done = true;
          card.node.classList.add(ev.ok ? 'ok' : 'err');
          card.node.querySelector('.spin').outerHTML = ev.ok ? '✅' : '❌';
          card.node.querySelector('.t-status').textContent = ev.ok ? 'انجام شد' : 'خطا';
          if (ev.preview) {
            const d = el('details');
            d.innerHTML = `<summary>مشاهده خروجی</summary><pre>${escapeHtml(ev.preview)}</pre>`;
            card.node.appendChild(d);
          }
        }
        break;
      }
      case 'tool_result': {
        if (ev.attach && ev.attach.path) {
          const m = addMessage('assistant', '');
          m.bubble.appendChild(renderAttachments([ev.attach]));
          if (ev.attach.kind === 'file') {
            const open = el('button', 'ghost-btn', '📂 باز کردن');
            open.style.marginTop = '8px';
            open.onclick = () => openFile(ev.attach.path);
            m.bubble.appendChild(open);
          }
          scrollDown();
        }
        break;
      }
      case 'confirm_request': {
        showConfirm(ev);
        break;
      }
      case 'confirm_resolved': {
        $('#confirmModal').hidden = true;
        break;
      }
      case 'skills': {
        if (ev.items && ev.items.length) {
          const chips = ev.items.map(s => `<span class="chip">⚡ ${escapeHtml(s.name)}</span>`).join(' ');
          const n = el('div', 'quick-tips', chips);
          n.style.justifyContent = 'flex-start';
          messagesEl.appendChild(n);
        }
        break;
      }
      case 'notes_updated': loadNotes(); break;
      case 'error': {
        if (typingRef) { typingRef.wrap.remove(); typingRef = null; }
        const m = addMessage('assistant', '');
        m.bubble.innerHTML = `<p style="color:var(--danger)">⚠️ ${escapeHtml(ev.message)}</p>`;
        toast(ev.message, 'err');
        break;
      }
      case 'warning': toast(ev.message); break;
      case 'done': {
        if (typingRef) { typingRef.wrap.remove(); typingRef = null; }
        if (state.streamingEl) state.streamingEl.classList.remove('cursor-blink');
        state.streamingEl = null;
        setBusy(false);
        break;
      }
      default: break;
    }
  }

  function attachActions(wrap, content) {
    if (!wrap || !content) return;
    if (wrap.querySelector('.msg-actions')) return;
    const bar = el('div', 'msg-actions');
    const copy = el('button', '', '📋 کپی');
    copy.onclick = () => { navigator.clipboard.writeText(content); toast('کپی شد', 'ok'); };
    const speak = el('button', '', '🔊 بخوان');
    speak.onclick = async () => {
      const r = await api('/api/tts', { method: 'POST', body: { text: content.slice(0, 1200) } });
      if (r && !r.ok) toast(r.error || 'خواندن ناموفق', 'err');
    };
    bar.append(copy, speak);
    wrap.appendChild(bar);
  }

  function showConfirm(ev) {
    state.pendingConfirm = ev.id;
    $('#confirmTitle').textContent = ev.title || 'اجازه می‌دهی؟';
    $('#confirmDetail').textContent = ev.detail || '';
    $('#confirmArgs').textContent = ev.args ? JSON.stringify(ev.args, null, 2) : '';
    $('#confirmModal').hidden = false;
  }
  $('#confirmYes').onclick = () => resolveConfirm(true);
  $('#confirmNo').onclick = () => resolveConfirm(false);
  async function resolveConfirm(approved) {
    $('#confirmModal').hidden = true;
    if (!state.pendingConfirm) return;
    await api('/api/confirm', { method: 'POST', body: { id: state.pendingConfirm, approved } });
    state.pendingConfirm = null;
  }
  $('#lightbox').onclick = () => { $('#lightbox').hidden = true; };

  /* ---------------- attachments ---------------- */
  $('#attachBtn').onclick = () => $('#filePicker').click();
  $('#filePicker').onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch('/api/upload', { method: 'POST', body: form });
      const data = await res.json();
      if (data.path) { state.attachments.push({ path: data.path }); renderAttachPreview(); }
      else toast(data.error || 'آپلود ناموفق', 'err');
    } catch (err) { toast('آپلود ناموفق: ' + err.message, 'err'); }
    e.target.value = '';
  };
  function renderAttachPreview() {
    const box = $('#attachPreview');
    box.innerHTML = '';
    state.attachments.forEach((a, i) => {
      const d = el('div', 'thumb');
      const img = el('img');
      img.src = '/file/' + encodeURI(a.path.replace(/^\//, ''));
      const x = el('button', 'x', '✕');
      x.onclick = () => { state.attachments.splice(i, 1); renderAttachPreview(); };
      d.append(img, x);
      box.appendChild(d);
    });
  }

  /* ---------------- mic ---------------- */
  $('#micBtn').onclick = async () => {
    const btn = $('#micBtn');
    if (btn.classList.contains('rec')) return;
    btn.classList.add('rec');
    toast('ضبط ۵ ثانیه‌ای… حالا حرف بزن 🎙️');
    try {
      const res = await api('/api/stt', { method: 'POST', body: { seconds: 5 } });
      if (res.ok && res.text) { input.value = (input.value ? input.value + ' ' : '') + res.text; input.focus(); }
      else toast(res.error || 'چیزی تشخیص داده نشد', 'err');
    } catch (err) { toast(err.message, 'err'); }
    finally { btn.classList.remove('rec'); }
  };
  $('#voiceBtn').onclick = () => $('#micBtn').click();

  async function openFile(path) {
    await api('/api/open', { method: 'POST', body: { path } });
  }

  /* ---------------- notes ---------------- */
  async function loadNotes() {
    const st = await api('/api/state');
    const notes = (st.notes && st.notes.notes) || [];
    const todos = (st.notes && st.notes.todos) || [];
    const nl = $('#notesList');
    nl.innerHTML = notes.length ? '' : '<div class="empty">یادداشتی نیست</div>';
    notes.forEach(n => {
      const item = el('div', 'list-item');
      item.innerHTML = `<div class="grow"><div class="title">${escapeHtml(n.title || 'یادداشت')}</div>
        <div class="desc">${escapeHtml(n.text || '')}</div>
        <div class="time">${new Date((n.created || 0) * 1000).toLocaleString('fa-IR')}</div></div>`;
      const x = el('button', 'x-btn', '🗑');
      x.onclick = async () => { await api('/api/notes', { method: 'POST', body: { action: 'delete', query: n.title } }); loadNotes(); };
      item.appendChild(x);
      nl.appendChild(item);
    });
    const tl = $('#todoList');
    tl.innerHTML = todos.length ? '' : '<div class="empty">کاری در لیست نیست</div>';
    todos.forEach(t => {
      const item = el('div', 'list-item');
      const cb = el('input');
      cb.type = 'checkbox';
      cb.onchange = async () => { await api('/api/notes', { method: 'POST', body: { action: 'complete', query: t.text } }); loadNotes(); };
      const g = el('div', 'grow');
      g.innerHTML = `<div class="title" style="${t.done ? 'text-decoration:line-through;opacity:.5' : ''}">${escapeHtml(t.text)}</div>`;
      item.append(cb, g);
      tl.appendChild(item);
    });
  }
  $('#saveNote').onclick = async () => {
    const title = $('#noteTitle').value.trim();
    const text = $('#noteText').value.trim();
    if (!text) return toast('متن خالی است', 'err');
    await api('/api/notes', { method: 'POST', body: { action: 'add', title, text } });
    $('#noteTitle').value = ''; $('#noteText').value = '';
    loadNotes(); toast('ذخیره شد', 'ok');
  };
  $('#addTodo').onclick = async () => {
    const text = $('#todoText').value.trim();
    if (!text) return;
    await api('/api/notes', { method: 'POST', body: { action: 'todo', text } });
    $('#todoText').value = ''; loadNotes();
  };

  /* ---------------- tools / skills / memory ---------------- */
  async function loadTools() {
    const res = await api('/api/tools');
    state.tools = res.tools || [];
    renderTools('');
  }
  function renderTools(filter) {
    const grid = $('#toolGrid');
    const f = (filter || '').toLowerCase();
    grid.innerHTML = '';
    const items = state.tools.filter(t => !f || (t.name + t.description + t.category).toLowerCase().includes(f));
    if (!items.length) { grid.innerHTML = '<div class="empty">ابزاری پیدا نشد</div>'; return; }
    items.forEach(t => {
      const d = el('div', 'tool-item');
      d.innerHTML = `<div class="name">${escapeHtml(t.name)} <span class="cat">${escapeHtml(t.category)}</span>
        ${t.dangerous ? '<span class="badge-danger">⚠️ حساس</span>' : ''}</div>
        <div class="desc">${escapeHtml(t.description)}</div>`;
      grid.appendChild(d);
    });
  }
  $('#toolSearch').oninput = (e) => renderTools(e.target.value);

  async function loadSkills() {
    const st = await api('/api/state');
    const list = $('#skillsList');
    list.innerHTML = '';
    (st.skills || []).forEach(s => {
      const d = el('div', 'list-item');
      d.innerHTML = `<span>⚡</span><div class="grow"><div class="title">${escapeHtml(s.name)}</div>
        <div class="desc">${escapeHtml(s.description || '')}</div></div>`;
      list.appendChild(d);
    });
  }

  async function loadMemory() {
    const st = await api('/api/state');
    const list = $('#memoryList');
    list.innerHTML = '';
    if (!(st.memory || []).length) { list.innerHTML = '<div class="empty">حافظه خالی است — چیزی یادش بده</div>'; return; }
    st.memory.forEach(m => {
      const d = el('div', 'list-item');
      d.innerHTML = `<span>🧠</span><div class="grow">${escapeHtml(m.fact)}</div>`;
      list.appendChild(d);
    });
  }
  $('#addMemory').onclick = async () => {
    const fact = $('#memFact').value.trim();
    if (!fact) return;
    await api('/api/remember', { method: 'POST', body: { fact } });
    $('#memFact').value = '';
    loadMemory(); toast('در حافظه ذخیره شد', 'ok');
  };

  /* ---------------- settings ---------------- */
  async function loadSettings() {
    const res = await api('/api/settings');
    state.settings = res.settings || {};
    state.providers = res.providers || {};
    const s = state.settings;
    const provSel = $('#provider');
    provSel.innerHTML = '';
    Object.entries(state.providers).forEach(([key, p]) => {
      const o = el('option');
      o.value = key; o.textContent = p.label || key;
      if (key === s.provider) o.selected = true;
      provSel.appendChild(o);
    });
    provSel.onchange = () => {
      const p = state.providers[provSel.value] || {};
      $('#baseUrl').value = p.base_url || '';
      $('#keyHelp').innerHTML = p.keys_url
        ? `دریافت کلید: <a href="${p.keys_url}" target="_blank" rel="noopener">${p.keys_url}</a>`
        : (p.no_key ? 'این ارائه‌دهنده کلید نمی‌خواهد.' : '');
      const dl = $('#modelList');
      dl.innerHTML = '';
      (p.models || []).forEach(m => { const o = el('option'); o.value = m; dl.appendChild(o); });
      if ((p.models || []).length) $('#model').value = p.models[0];
      if (p.no_key) $('#apiKey').value = '';
    };
    provSel.onchange();
    $('#model').value = s.model || '';
    $('#apiKey').value = '';
    $('#apiKey').placeholder = s.has_key ? 'کلید ذخیره شده است (برای تغییر بنویس)' : 'sk-…';
    $('#baseUrl').value = s.base_url_effective || (s.base_url || '');
    $('#policy').value = s.policy || 'ask';
    $('#allowedPaths').value = (s.allowed_paths || []).join(', ');
    $('#allowAllPaths').checked = !!s.allow_all_paths;
    $('#userName').value = s.user_name || '';
    $('#maxSteps').value = s.max_steps || 24;
    $('#vision').checked = !!s.vision;
    $('#autoSkills').checked = !!s.auto_skills;
    $('#ttsEnabled').checked = !!s.tts_enabled;
    $('#ttsAuto').checked = !!s.tts_auto_speak;
    $('#ttsEngine').value = s.tts_engine || 'auto';
    $('#sttEngine').value = s.stt_engine || 'auto';
    $('#systemPrompt').value = s.system_prompt || '';
    $('#modelName').textContent = `${s.provider_label || s.provider} · ${s.model || '—'}`;
    const banner = $('#setupBanner');
    if (banner) banner.hidden = !(s.provider === 'demo' || !s.has_key);
    $('#hintText').textContent = `مدل: ${s.model || '—'} • سیاست: ${({ ask: 'بپرس', auto: 'خودکار', readonly: 'فقط خواندنی' })[s.policy] || s.policy}`;
  }

  $('#saveSettings').onclick = async () => {
    const payload = {
      provider: $('#provider').value,
      model: $('#model').value.trim(),
      base_url: $('#baseUrl').value.trim(),
      policy: $('#policy').value,
      allowed_paths: $('#allowedPaths').value.split(',').map(s => s.trim()).filter(Boolean),
      allow_all_paths: $('#allowAllPaths').checked,
      user_name: $('#userName').value.trim(),
      max_steps: parseInt($('#maxSteps').value || '24', 10),
      vision: $('#vision').checked,
      auto_skills: $('#autoSkills').checked,
      tts_enabled: $('#ttsEnabled').checked,
      tts_auto_speak: $('#ttsAuto').checked,
      tts_engine: $('#ttsEngine').value,
      stt_engine: $('#sttEngine').value,
    };
    const key = $('#apiKey').value.trim();
    if (key) payload.api_key = key;
    const res = await api('/api/settings', { method: 'POST', body: { settings: payload } });
    if (res.ok) {
      state.settings = res.settings;
      (res.errors || []).forEach(e => toast(e, 'err'));
      $('#apiKey').value = '';
      $('#apiKey').placeholder = res.settings.has_key ? 'کلید ذخیره شده است' : 'sk-…';
      toast('تنظیمات ذخیره شد', 'ok');
      loadSettings(); loadHealth();
    } else toast('ذخیره ناموفق', 'err');
  };
  $('#savePrompt').onclick = async () => {
    const res = await api('/api/settings', { method: 'POST', body: { settings: { system_prompt: $('#systemPrompt').value } } });
    if (res.ok) toast('شخصیت ذخیره شد', 'ok');
  };
  $$('.preset').forEach(btn => btn.onclick = () => {
    const name = btn.dataset.provider;
    const sel = $('#provider');
    sel.value = name;
    sel.onchange();
    if (btn.dataset.model) $('#model').value = btn.dataset.model;
    $('#apiKey').focus();
    toast(`«${name}» انتخاب شد — کلید را بچسبان و ذخیره کن`, 'ok');
  });

  $('#testConn').onclick = async () => {
    $('#testResult').textContent = 'در حال تست…';
    const res = await api('/api/test-connection', { method: 'POST', body: {} });
    $('#testResult').textContent = res.ok ? `✅ وصل شد (${res.latency_ms}ms)` : `❌ ${res.error}`;
    $('#testResult').style.color = res.ok ? 'var(--ok)' : 'var(--danger)';
  };
  $('#testVoice').onclick = async () => {
    const r = await api('/api/tts', { method: 'POST', body: { text: 'سلام! من دستیار تو هستم.' } });
    if (r && r.ok) toast(`صدا پخش شد (${r.engine})`, 'ok');
    else toast((r && r.error) || 'صدا پخش نشد', 'err');
  };
  $('#openData').onclick = async () => {
    const dir = state.dataDir || '';
    if (!dir) return toast('پوشه‌ی داده‌ها پیدا نشد', 'err');
    await api('/api/open', { method: 'POST', body: { path: dir } });
    toast('پوشه باز شد: ' + dir, 'ok');
  };
  $('#exportChat').onclick = () => {
    const text = $$('.msg').map(m => (m.classList.contains('user') ? '👤 ' : '🤖 ') + (m.querySelector('.bubble').innerText || '')).join('\n\n');
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const a = el('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'dastyar-chat.txt';
    a.click();
  };
  $('#shutdownApp').onclick = async () => {
    if (!confirm('دستیار بسته شود؟')) return;
    await api('/api/shutdown', { method: 'POST', body: {} });
    document.body.innerHTML = '<div style="display:grid;place-items:center;height:100vh;font-size:1.2rem">دستیار بسته شد. 👋</div>';
  };

  function loadHealth() {
    api('/api/health').then(h => {
      $('#versionText').textContent = 'v' + h.version;
      $('#osLabel').textContent = h.os;
      const sys = $('#sysInfo');
      sys.innerHTML = `<b>سیستم‌عامل</b><span>${escapeHtml(h.os)}</span>
        <b>ارائه‌دهنده</b><span>${escapeHtml(h.provider || '—')}</span>
        <b>مدل</b><span>${escapeHtml(h.model || '—')}</span>
        <b>آپتایم</b><span>${Math.floor(h.uptime / 60)} دقیقه</span>
        <b>نسخه</b><span>${escapeHtml(h.version)}</span>`;
      setStatus(true, 'متصل');
    }).catch(() => setStatus(false, 'سرور در دسترس نیست'));
  }

  /* ---------------- boot ---------------- */
  async function boot() {
    try {
      const st = await api('/api/state');
      if (st.data_dir) state.dataDir = st.data_dir;
      if (st.settings && st.settings.user_name) $('#helloName').textContent = st.settings.user_name + '،';
      (st.history || []).slice(-60).forEach(m => addMessage(m.role, m.content));
      if ((st.history || []).length) $('#welcome').style.display = 'none';
      await loadSettings();
      loadSkills();
      loadHealth();
      if (state.dataDir) $('#skillsPath').textContent = state.dataDir + '\\skills';
      connectEvents();
      const tips = [
        '«یک نامه رسمی به مدیرعامل بنویس»',
        '«اسکرین‌شات بگیر و ببین چه خطایی روی صفحه است»',
        '«هر روز ساعت ۹ صبح یادم بنداز»',
        '«این فایل PDF رو خلاصه کن»',
      ];
      const qt = $('#quickTips');
      tips.forEach(t => {
        const c = el('button', 'chip', escapeHtml(t));
        c.onclick = () => { input.value = t.replace(/[«»]/g, ''); input.focus(); };
        qt.appendChild(c);
      });
      $$('.card-suggest').forEach(c => c.onclick = () => {
        input.value = c.dataset.prompt; input.focus();
      });
    } catch (err) {
      toast('اتصال به سرور برقرار نشد: ' + err.message, 'err');
      setStatus(false, 'آفلاین');
    }
  }

  // auto-resize + global shortcuts
  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); input.focus(); }
    if (e.key === 'Escape') { $('#confirmModal').hidden = true; $('#lightbox').hidden = true; }
  });

  boot();
})();
