/* Haven page logic. Plain JS, no build step, no network beyond this PC's own server. */
'use strict';

/* ===================== basics ===================== */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const store = {
  get(k, d){ try{ const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); }catch{ return d; } },
  set(k, v){ try{ localStorage.setItem(k, JSON.stringify(v)); }catch{} }
};
const TOKEN = (() => { const t = new URLSearchParams(location.search).get('t'); if (t) sessionStorage.setItem('t', t); return t || sessionStorage.getItem('t') || ''; })();
const api = (u, o = {}) => fetch(u, {...o, headers: {...(o.headers || {}), 'X-Desk-Token': TOKEN}});
const jpost = (u, b, method = 'POST') => api(u, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(b)});
const jget = async u => { const r = await api(u); if (!r.ok) throw new Error(await errorOf(r)); return r.json(); };
const desktop = () => !!(window.pywebview && window.pywebview.api);
const esc = t => String(t ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kb = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(16).slice(2) + Date.now().toString(16)).replace(/-/g, '');
let toastT;
function toast(m, opt = {}){
  const t = $('#toast'); $('#toasttxt').textContent = m; t.classList.add('on');
  const b = $('#toastbtn'); b.hidden = !opt.undo;
  b.onclick = opt.undo ? () => { t.classList.remove('on'); opt.undo(); } : null;
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), opt.ms || 1800);
}
async function errorOf(r){ try{ return (await r.json()).detail || r.statusText; }catch{ return r.statusText || 'Something went wrong'; } }

/* ===================== icons ===================== */
const P = {
  arch:'<path d="M7 20V11a5 5 0 0 1 10 0v9"/><path d="M4.5 20.2h15"/>',
  clip:'<path d="m21 12-8.6 8.6a5 5 0 0 1-7-7L14 5a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.3-2.3l7.9-7.9"/>',
  up:'<path d="M12 19V5M6 11l6-6 6 6"/>', stop:'<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/>',
  search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', edit:'<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  gear:'<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  x:'<path d="M18 6 6 18M6 6l12 12"/>', more:'<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
  file:'<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  img:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
  shrink:'<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
  merge:'<path d="M8 3v6a4 4 0 0 0 4 4 4 4 0 0 1 4 4v4"/><path d="M16 3v6a4 4 0 0 1-2 3.5"/><path d="m13 18 3 3 3-3"/>',
  split:'<path d="M12 3v7M12 10l-6 6v5M12 10l6 6v5"/><path d="m9 6 3-3 3 3"/>',
  trash:'<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6"/>', keep:'<path d="M20 6 9 17l-5-5"/>',
  rotate:'<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  topdf:'<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 18v-6M9 15l3 3 3-3"/>',
  text:'<path d="M4 7V5h16v2M9 19h6M12 5v14"/>', spark:'<path d="M12 3l1.9 5.6L19.5 10.5l-5.6 1.9L12 18l-1.9-5.6L4.5 10.5l5.6-1.9z"/><path d="M19 3v4M17 5h4"/>',
  bulb:'<path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>',
  copy:'<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  save:'<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>', folder:'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  lang:'<path d="m5 8 6 6M4 14l6-6 2-3M2 5h12M7 2h1M22 22l-5-10-5 10M14 18h6"/>', eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  q:'<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/>', list:'<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  monitor:'<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>', sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>', moon:'<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>', arrow:'<path d="M5 12h14M13 6l6 6-6 6"/>',
  swap:'<path d="M7 4v16M7 20l-4-4M17 20V4M17 4l4 4"/>',
  doc:'<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6M9 9h1"/>',
  mail:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>', check:'<path d="M20 6 9 17l-5-5"/>', alert:'<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
  cloud:'<path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.8A6 6 0 0 0 4.5 13 4 4 0 0 0 6 20h11.5"/>', cpu:'<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9h6v6H9zM9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/>',
  puzzle:'<path d="M10 3a2 2 0 1 1 4 0v2h4a1 1 0 0 1 1 1v4h-2a2 2 0 1 0 0 4h2v4a1 1 0 0 1-1 1h-4v-2a2 2 0 1 0-4 0v2H6a1 1 0 0 1-1-1v-4h2a2 2 0 1 0 0-4H5V6a1 1 0 0 1 1-1h4z"/>',
  side:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>', chev:'<path d="m6 9 6 6 6-6"/>', down:'<path d="M12 5v14M6 13l6 6 6-6"/>',
  plus:'<path d="M12 5v14M5 12h14"/>', regen:'<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/>',
  key:'<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.3-9.3M17 6l3 3M15 8l2 2"/>', lock:'<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  dl:'<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>'
};
const ic = (n, s) => `<svg class="i" viewBox="0 0 24 24"${s ? ` style="width:${s}px;height:${s}px"` : ''} aria-hidden="true">${P[n] || ''}</svg>`;
const archW = s => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4"/><path d="M13 3v5h5v2"/><path d="M8.5 11.5h5M8.5 15h2.5"/><path d="M17.5 13.2l1.15 3.15 3.15 1.15-3.15 1.15-1.15 3.15-1.15-3.15-3.15-1.15 3.15-1.15z" fill="#fff" stroke-width="1.2"/></svg>`;
$('#mark').innerHTML = archW(16); $('#heroarch').innerHTML = archW(32); $('#droparch').innerHTML = archW(28);
[['#b-search','search'],['#b-gear','gear'],['#b-attach','clip'],['#b-close','x'],['#palicon','search'],['#ic-keys','key'],['#ic-ext','puzzle'],
 ['#b-side','side'],['#b-side-close','side'],['#ic-new','plus'],['#ic-cq','search'],['#ic-pq','search'],['#pillchev','chev'],['#tobottom','down'],
 ['#ic-editing','edit'],['#b-new','edit']].forEach(([s, n]) => { const el = $(s); if (el) el.innerHTML = ic(n); });
$('#think').innerHTML = ic('bulb') + 'Think';
$('#send').innerHTML = ic('up');

/* ===================== state ===================== */
const S = {
  models: [], providers: [], modelsLoaded: false,
  model: store.get('model2', ''), recent: store.get('recentModels', []),
  convs: [], conv: null, live: new Map(), editing: null, stick: true, gen: 0,
};
window.haven = S; // handy in DevTools (and for the UI tests)
const minfo = id => S.models.find(m => m.full_id === id);
const curInfo = () => minfo(S.model);
const provOf = pid => S.providers.find(p => p.id === pid);
const isCloud = () => { const m = curInfo(); return !!m && !m.local; };
const modelLabel = id => { const m = minfo(id); return m ? m.label : (id || '').split(':').slice(1).join(':'); };

/* ===================== models + picker ===================== */
async function refreshModels(refresh = false){
  try{
    const j = await jget('/api/models' + (refresh ? '?refresh=1' : ''));
    S.models = j.models; S.providers = j.providers; S.modelsLoaded = true;
    S.models.forEach(m => { m._q = (m.label + ' ' + m.id + ' ' + ((provOf(m.provider) || {}).name || '')).toLowerCase(); });
  }catch{ /* server busy: keep the last list */ }
  if (!S.model && S.models.length) S.model = (S.recent.find(minfo) || (S.models.find(m => m.local) || S.models[0]).full_id);
  paintModel();
  if (!$('#picker').hidden) renderPicker();
}
function paintModel(){
  const m = curInfo(), pill = $('#pill');
  pill.className = 'pill' + (!m ? ' none' : m.local ? '' : ' cloud');
  $('#pillname').textContent = m ? m.label : (S.model ? modelLabel(S.model) : 'No model');
  $('#tag').textContent = !m ? (S.model ? 'Unavailable' : 'Off') : m.local ? 'Private' : 'Cloud';
  const p = m && provOf(m.provider);
  $('#foot').classList.toggle('cloud', !!m && !m.local);
  $('#foottxt').textContent = !m ? 'No model selected' : m.local ? 'Running on this laptop' : `Using ${p ? p.name : 'a cloud model'}, so messages and files go there`;
  const th = $('#think');
  th.hidden = !m || m.think === 'no';
  th.title = m && m.think === 'always' ? 'This model always thinks. On: show its thinking.' : 'Think it through first (slower)';
  updateNotice(); paintEmpty();
}
function updateNotice(){
  const n = $('#notice');
  if (!S.modelsLoaded || !S.model || curInfo()){ n.hidden = true; return; }
  const pid = S.model.split(':')[0], p = provOf(pid);
  $('#noticetxt').textContent = p && p.local && p.status !== 'ok' ? `${p.name} isn't running. Start it, or pick another model.` : 'Model no longer available, pick another.';
  n.hidden = false;
}
function setModel(id){
  S.model = id; store.set('model2', id);
  paintModel();
  if (S.conv) jpost(`/api/conversations/${S.conv.id}`, {model: id}, 'PATCH');
}
let pk = 0, pitemsM = [];
function openPicker(){
  closePal(); closeMenus();
  const p = $('#picker'), r = $('#pill').getBoundingClientRect();
  p.hidden = false;
  const w = p.offsetWidth;
  p.style.top = (r.bottom + 6) + 'px';
  p.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + 'px';
  $('#pq').value = ''; pk = 0; renderPicker(); $('#pq').focus();
  refreshModels();
}
function closePicker(){ $('#picker').hidden = true; }
function renderPicker(){
  const t0 = performance.now();
  const q = $('#pq').value.toLowerCase().trim(), toks = q.split(/\s+/).filter(Boolean);
  const hit = m => toks.every(t => m._q.includes(t));
  const LIMIT = 300; let shown = 0, more = 0;
  pitemsM = [];
  let html = '';
  const item = (m, grp) => {
    if (shown >= LIMIT){ more++; return ''; }
    shown++; const k = pitemsM.length; pitemsM.push(m.full_id);
    const p = provOf(m.provider) || {};
    return `<li class="m ${k === pk ? 'on' : ''} ${m.full_id === S.model ? 'cur' : ''}" role="option" data-k="${k}">`
      + `<span class="n">${esc(m.label)}${m.label !== m.id ? `<span class="sub"> · ${esc(m.id)}</span>` : ''}</span>`
      + (m.vision ? `<span title="Can see images">${ic('eye')}</span>` : '') + (m.think !== 'no' ? `<span title="Can think">${ic('bulb')}</span>` : '')
      + `<span class="badge ${m.local ? 'private' : 'cloud'}">${m.local ? 'Private' : 'Cloud'}</span>`
      + (grp === 'recent' ? `<span class="sub">${esc(p.name || '')}</span>` : '') + `</li>`;
  };
  if (!q){
    const rec = S.recent.map(minfo).filter(Boolean).slice(0, 3);
    if (rec.length) html += `<li class="grp">Recent</li>` + rec.map(m => item(m, 'recent')).join('');
  }
  for (const p of S.providers){
    const ms = S.models.filter(m => m.provider === p.id && (!toks.length || hit(m)));
    const st = p.status === 'ok' ? '' : p.status === 'not running' ? 'not running' : 'unavailable' + (p.message ? ' – ' + p.message : '');
    if (!ms.length && (q || (p.local && p.status !== 'ok' && !S.models.some(m => m.provider === p.id) && p.id !== 'ollama'))) continue;
    html += `<li class="grp">${esc(p.label || p.name)}<span class="pst">${esc(st)}</span></li>`;
    if (!ms.length && p.id === 'ollama' && p.status !== 'ok') html += `<li class="more">Open Ollama to use private models on this PC.</li>`;
    html += ms.map(m => item(m)).join('');
  }
  if (!pitemsM.length) html += `<li class="more">${q ? 'No model matches.' : 'No models yet. Start Ollama or add a key.'}</li>`;
  if (more) html += `<li class="more">${more} more. Keep typing to narrow it down.</li>`;
  $('#pl').innerHTML = html;
  $('#pstat').textContent = `${S.models.length} models`;
  const on = $('#pl .m.on'); if (on) on.scrollIntoView({block:'nearest'});
  S.pickerMs = performance.now() - t0;
}
function pickModel(k){ const id = pitemsM[k]; if (!id) return; closePicker(); setModel(id); useModel(id); toast(modelLabel(id)); $('#input').focus(); }
$('#pill').onclick = () => $('#picker').hidden ? openPicker() : closePicker();
$('#pq').oninput = () => { pk = 0; renderPicker(); };
$('#pq').onkeydown = e => {
  if (e.key === 'ArrowDown'){ pk = Math.min(pk + 1, pitemsM.length - 1); renderPicker(); e.preventDefault(); }
  else if (e.key === 'ArrowUp'){ pk = Math.max(pk - 1, 0); renderPicker(); e.preventDefault(); }
  else if (e.key === 'Enter'){ pickModel(pk); e.preventDefault(); }
  else if (e.key === 'Escape'){ closePicker(); $('#pill').focus(); e.stopPropagation(); }
};
$('#pl').onclick = e => { const li = e.target.closest('li.m'); if (li) pickModel(+li.dataset.k); };
$('#prefresh').onclick = async () => { $('#prefresh').disabled = true; await refreshModels(true); $('#prefresh').disabled = false; };
$('#paddkey').onclick = () => { closePicker(); openSheet(true); };
$('#noticebtn').onclick = openPicker;

/* ===================== conversations + sidebar ===================== */
const DAY = 86400000;
function groupOf(ts){
  const d = new Date(ts * 1000), now = new Date(), start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d.getTime() >= start) return 'Today';
  if (d.getTime() >= start - DAY) return 'Yesterday';
  if (d.getTime() >= start - 7 * DAY) return 'Previous 7 days';
  return 'Older';
}
let pendingDeletes = new Map(), sideQ = '', searchRes = null;
async function loadConvs(){
  try{ S.convs = (await jget('/api/conversations')).conversations; }catch{ S.convs = []; }
  renderSide();
}
function convItem(c, snip){
  const live = S.live.has(c.id);
  return `<div class="conv ${S.conv && S.conv.id === c.id ? 'on' : ''}" data-id="${esc(c.id)}" role="button" tabindex="0">`
    + (live ? '<span class="live" title="Answering"></span>' : '')
    + `<span class="t">${esc(c.title || 'New chat')}${snip ? `<span class="snip">${esc(snip)}</span>` : ''}</span>`
    + `<button class="menu" data-menu="${esc(c.id)}" title="More" aria-label="Chat options">${ic('more', 16)}</button></div>`;
}
function renderSide(){
  const list = S.convs.filter(c => !pendingDeletes.has(c.id));
  let html = '';
  if (sideQ){
    const ql = sideQ.toLowerCase();
    const seen = new Set(), rows = [];
    list.filter(c => (c.title || '').toLowerCase().includes(ql)).forEach(c => { seen.add(c.id); rows.push([c, '']); });
    (searchRes || []).forEach(r => { if (!seen.has(r.id) && !pendingDeletes.has(r.id)){ seen.add(r.id); rows.push([r, r.snippet]); } else if (r.snippet){ const x = rows.find(y => y[0].id === r.id); if (x && !x[1]) x[1] = r.snippet; } });
    html = rows.length ? rows.map(([c, s]) => convItem(c, s)).join('') : `<div class="side-empty">No chats match “${esc(sideQ)}”.</div>`;
  } else if (!list.length){
    html = '<div class="side-empty">Your chats will appear here.</div>';
  } else {
    let g = null;
    for (const c of list){ const gg = groupOf(c.updated); if (gg !== g){ html += `<div class="grp">${gg}</div>`; g = gg; } html += convItem(c); }
  }
  $('#convs').innerHTML = html;
}
let sqT;
$('#cq').oninput = () => {
  sideQ = $('#cq').value.trim(); renderSide(); clearTimeout(sqT);
  if (!sideQ){ searchRes = null; return; }
  const q = sideQ;
  sqT = setTimeout(async () => { try{ const r = await jget('/api/conversations/search?q=' + encodeURIComponent(q)); if (q === sideQ){ searchRes = r.results; renderSide(); } }catch{} }, 40);
};
$('#cq').onkeydown = e => { if (e.key === 'Escape'){ $('#cq').value = ''; $('#cq').oninput(); $('#input').focus(); e.stopPropagation(); } };
$('#convs').onclick = e => {
  const m = e.target.closest('[data-menu]'); if (m){ e.stopPropagation(); return convMenu(m.dataset.menu, m); }
  const c = e.target.closest('.conv'); if (c && !e.target.closest('input')) openConv(c.dataset.id);
};
$('#convs').onkeydown = e => { const c = e.target.closest('.conv'); if (c && e.key === 'Enter' && e.target === c) openConv(c.dataset.id); };
function closeMenus(){ $$('.popmenu').forEach(x => x.remove()); }
function convMenu(id, btn){
  closeMenus();
  const r = btn.getBoundingClientRect(), menu = document.createElement('div');
  menu.className = 'popmenu';
  menu.innerHTML = `<button data-a="rename">${ic('edit')}Rename</button><button data-a="export">${ic('dl')}Export as Markdown</button><button data-a="delete" class="danger">${ic('trash')}Delete</button>`;
  document.body.appendChild(menu);
  menu.style.top = Math.min(innerHeight - menu.offsetHeight - 8, r.bottom + 4) + 'px';
  menu.style.left = Math.min(innerWidth - menu.offsetWidth - 8, r.left) + 'px';
  menu.onclick = ev => { const a = ev.target.closest('[data-a]'); if (!a) return; closeMenus(); ({rename: renameConv, export: exportConv, delete: deleteConv})[a.dataset.a](id); };
  menu.querySelector('button').focus();
}
function renameConv(id){
  const el = $(`.conv[data-id="${CSS.escape(id)}"]`); if (!el) return;
  const c = S.convs.find(x => x.id === id); const t = el.querySelector('.t');
  const inp = Object.assign(document.createElement('input'), {value: c ? c.title : ''}); inp.setAttribute('aria-label', 'Chat title');
  t.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  const finish = async ok => {
    if (done) return; done = true;
    const v = inp.value.trim();
    if (ok && v && c && v !== c.title){ c.title = v; if (S.conv && S.conv.id === id) S.conv.title = v; await jpost(`/api/conversations/${id}`, {title: v}, 'PATCH'); }
    renderSide();
  };
  inp.onkeydown = e => { if (e.key === 'Enter') finish(true); if (e.key === 'Escape'){ e.stopPropagation(); finish(false); } };
  inp.onblur = () => finish(true);
}
async function exportConv(id){
  const c = await jget(`/api/conversations/${id}`);
  const lines = [`# ${c.conversation.title || 'Chat'}`, ''];
  for (const m of c.messages){
    if (m.role === 'user') lines.push(`**You:** ${m.content}`, '');
    else if (m.role === 'assistant') lines.push(`**${modelLabel(m.model) || 'Assistant'}:**`, '', m.content, '');
    else if (m.role === 'tool') lines.push(`> ${m.meta.state === 'fail' ? 'Failed' : 'File'}: ${m.meta.title || ''}`, '');
  }
  const name = (c.conversation.title || 'chat').replace(/[\\/:*?"<>|]+/g, ' ').trim().slice(0, 60) + '.md';
  if (await saveText(name, lines.join('\n'))) toast('Exported');
}
function deleteConv(id){
  const wasOpen = S.conv && S.conv.id === id;
  const live = S.live.get(id); if (live) live.ctrl.abort();
  const timer = setTimeout(() => { pendingDeletes.delete(id); api(`/api/conversations/${id}`, {method:'DELETE'}); S.convs = S.convs.filter(c => c.id !== id); }, 5000);
  pendingDeletes.set(id, timer);
  if (wasOpen) newChat(false);
  renderSide();
  toast('Chat deleted', {ms: 5000, undo: () => { clearTimeout(timer); pendingDeletes.delete(id); renderSide(); if (wasOpen) openConv(id); }});
}
addEventListener('pagehide', () => { for (const [id, t] of pendingDeletes){ clearTimeout(t); fetch(`/api/conversations/${id}`, {method:'DELETE', keepalive:true, headers:{'X-Desk-Token': TOKEN}}); } });

async function ensureConv(){
  if (S.conv) return S.conv;
  const c = await (await jpost('/api/conversations', {model: S.model})).json();
  S.conv = {...c, messages: []}; store.set('conv', c.id);
  S.convs.unshift(c); renderSide();
  return S.conv;
}
async function openConv(id){
  if (S.conv && S.conv.id === id){ closeDrawer(); return; }
  const gen = ++S.gen;
  let c;
  try{ c = await jget(`/api/conversations/${id}`); }catch(e){ toast('That chat is gone'); store.set('conv', ''); return loadConvs(); }
  if (gen !== S.gen) return;
  const live = S.live.get(id);
  if (live){ const i = c.messages.findIndex(m => m.id === live.msg.id); if (i >= 0) c.messages[i] = live.msg; else c.messages.push(live.msg); }
  S.conv = {...c.conversation, messages: c.messages}; S.editing = null; $('#editing').hidden = true;
  store.set('conv', id);
  if (c.conversation.model && c.conversation.model !== S.model){ S.model = c.conversation.model; store.set('model2', S.model); paintModel(); }
  renderThread(); renderSide(); setBusyUI(); closeDrawer(); paintDock();
}
function newChat(focus = true){
  S.gen++; S.conv = null; S.editing = null; $('#editing').hidden = true; store.set('conv', '');
  files = []; closeParam(); renderThread(); renderSide(); paintDock(); setBusyUI();
  if (focus) $('#input').focus();
}
$('#b-new').onclick = $('#b-new2').onclick = () => newChat();

/* sidebar open/close (a drawer under 900px) */
const narrow = () => innerWidth <= 900;
function toggleSide(){
  if (narrow()){ document.documentElement.classList.toggle('side-open'); return; }
  const off = document.documentElement.classList.toggle('side-off'); store.set('side', !off);
}
function closeDrawer(){ document.documentElement.classList.remove('side-open'); }
$('#b-side').onclick = $('#b-side-close').onclick = toggleSide;
addEventListener('resize', () => { if (!narrow()) closeDrawer(); });
document.addEventListener('click', e => { if (narrow() && document.documentElement.classList.contains('side-open') && !e.target.closest('#side') && !e.target.closest('#b-side')) closeDrawer(); });

/* ===================== files ===================== */
const KIND = f => {
  const e = (f.name.split('.').pop() || '').toLowerCase();
  if (e === 'pdf') return 'pdf';
  if (['jpg','jpeg','png','webp','gif','bmp','heic','heif','tif','tiff'].includes(e)) return 'img';
  if (['doc','docx','ppt','pptx','xls','xlsx','odt','odp','ods','rtf'].includes(e)) return 'office';
  if (['txt','md','csv','json','py','js','html','css'].includes(e)) return 'txt';
  if (['mp4','mov','mkv','webm','avi','m4v','wmv','flv','3gp','mpeg','mpg','ts'].includes(e)) return 'vid';
  if (['mp3','wav','m4a','aac','ogg','oga','flac','opus','wma','aiff','amr'].includes(e)) return 'aud';
  return 'other';
};
const FT = {pdf:['PDF','c-pdf'], img:['IMG','c-conv'], office:['DOC','c-office'], txt:['TXT','c-ai'], vid:['VID','c-ai'], aud:['AUD','c-conv'], other:['FILE','c-ai']};
let files = [], pending = null;
const kinds = () => files.map(KIND);
const only = k => files.length > 0 && kinds().every(x => x === k);
const one = k => files.length === 1 && KIND(files[0]) === k;
const picker = Object.assign(document.createElement('input'), {type:'file', multiple:true});
picker.onchange = () => { add(picker.files); picker.value = ''; };
function add(list){
  const arr = [...list]; if (!arr.length) return;
  files = files.concat(arr); paintDock();
  if (pending){ const id = pending === 'compress' && only('img') ? 'img-compress' : pending; pending = null; loadFormats().then(() => { const a = ACT(id); if (!a) return; if (id === 'convert'){ const t = convertTargets(); if (presetTo && t.includes(presetTo)){ const to = presetTo; presetTo = null; return run(a, to); } presetTo = null; if (t.length) return choose(a); toast('No conversions available for this file'); return; } if (a.when()) choose(a); }); }
  else loadFormats();
}
$('#b-attach').onclick = () => { pending = null; picker.accept = ''; picker.click(); };
let depth = 0;
addEventListener('dragenter', e => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')){ depth++; $('#drop').classList.add('on'); } });
addEventListener('dragleave', () => { if (--depth <= 0){ depth = 0; $('#drop').classList.remove('on'); } });
addEventListener('dragover', e => e.preventDefault());
addEventListener('drop', e => { e.preventDefault(); depth = 0; $('#drop').classList.remove('on'); add(e.dataTransfer.files); });
addEventListener('paste', e => { if (e.clipboardData && e.clipboardData.files.length){ e.preventDefault(); add(e.clipboardData.files); } });

/* ===================== action registry ===================== */
const PR = {
  summary:'Summarise this. Start with a 2-sentence overview, then the main points as short bullets.',
  points:'List the key points, then any action items, dates, numbers or decisions, as short bullets.',
  quiz:'Write 8 practice questions (easy to hard) from this, with short answers at the end.',
  ocr:'Transcribe ALL text exactly as written, in reading order. Keep line breaks. Render tables as Markdown tables. Output only the text.',
  explain:'Explain what this image shows. If it has an error, chart or problem, explain it and what to do.',
  grammar:'Fix grammar, spelling and punctuation. Keep meaning and tone. Return only the corrected text.',
  shorter:'Make this noticeably shorter, keeping all key information. Return only the result.',
  formal:'Rewrite this in a clear, professional tone. Return only the result.',
  email:'Turn this into a clear email with a subject line. Return only the email.'
};
const doc1 = () => one('pdf') || one('txt');
const typed = () => $('#input').value.trim();
const ACTIONS = [
  {id:'summary', label:'Summarise', icon:'spark', c:'ai', ai:1, whole:1, accept:'.pdf,.txt,.md', when: () => doc1() || one('img'), prompt: () => PR.summary},
  {id:'compress', label:'Compress', icon:'shrink', c:'pdf', ep:'/api/pdf/compress', accept:'.pdf,image/*,.heic', when: () => one('pdf'), param:{cmp:1}},
  {id:'img-compress', label:'Compress', icon:'shrink', c:'conv', ep:'/api/image/compress', multi:1, accept:'image/*,.heic', when: () => only('img'), param:{cmp:1}},
  {id:'merge', label:'Merge', icon:'merge', c:'pdf', ep:'/api/pdf/merge', multi:1, accept:'.pdf', when: () => only('pdf') && files.length >= 2},
  {id:'delete', label:'Remove pages', icon:'trash', c:'pdf', ep:'/api/pdf/delete', accept:'.pdf', when: () => one('pdf'), param:{name:'pages', ph:'Pages to remove, e.g. 2, 5-7'}},
  {id:'ocr', label:'Read text', icon:'text', c:'ai', ai:1, accept:'.pdf,image/*,.heic', when: () => one('pdf') || (only('img') && files.length <= 4), prompt: () => PR.ocr},
  {id:'explain', label:'Explain', icon:'eye', c:'ai', ai:1, accept:'image/*,.heic', when: () => one('img'), prompt: () => PR.explain},
  {id:'from-images', label:'Make PDF', icon:'topdf', c:'conv', ep:'/api/pdf/from-images', multi:1, accept:'image/*,.heic', when: () => only('img')},
  {id:'convert', label:'Convert to…', icon:'swap', c:'conv', ep:'/api/convert', multi:1, accept:'', when: () => files.length > 0 && convertTargets().length > 0, param:{name:'to', fmt:1}},
  {id:'split', label:'Split', icon:'split', c:'pdf', ep:'/api/pdf/split', accept:'.pdf', when: () => one('pdf'), param:{name:'ranges', ph:'Leave blank for every page, or 1-3, 4-10', optional:1}},
  {id:'extract', label:'Keep pages', icon:'keep', c:'pdf', ep:'/api/pdf/extract', accept:'.pdf', when: () => one('pdf'), param:{name:'pages', ph:'Pages to keep, e.g. 1-3, 8'}},
  {id:'points', label:'Key points', icon:'list', c:'ai', ai:1, whole:1, accept:'.pdf,.txt,.md', when: doc1, prompt: () => PR.points},
  {id:'quiz', label:'Practice questions', icon:'q', c:'ai', ai:1, whole:1, accept:'.pdf,.txt,.md', when: doc1, prompt: () => PR.quiz},
  {id:'rotate', label:'Rotate', icon:'rotate', c:'pdf', ep:'/api/pdf/rotate', accept:'.pdf', when: () => one('pdf'), param:{name:'angle', sel:[['90','90° right'],['180','180°'],['270','90° left']]}, extra:{pages:''}},
  {id:'to-images', label:'To images', icon:'img', c:'conv', ep:'/api/pdf/to-images', accept:'.pdf', when: () => one('pdf'), param:{name:'fmt', sel:[['png','PNG'],['jpg','JPG']]}, extra:{dpi:'150'}},
  {id:'pdf-text', label:'Copy text', icon:'copy', c:'pdf', ep:'/api/pdf/text', text:1, accept:'.pdf', when: () => one('pdf')},
  {id:'grammar', label:'Fix grammar', icon:'edit', c:'ai', ai:1, write:1, when: () => !files.length && typed().length > 15, prompt: () => PR.grammar},
  {id:'shorter', label:'Shorter', icon:'shrink', c:'ai', ai:1, write:1, when: () => !files.length && typed().length > 15, prompt: () => PR.shorter},
  {id:'formal', label:'Professional', icon:'doc', c:'ai', ai:1, write:1, when: () => !files.length && typed().length > 15, prompt: () => PR.formal},
  {id:'email', label:'Make email', icon:'mail', c:'ai', ai:1, write:1, when: () => !files.length && typed().length > 15, prompt: () => PR.email},
  {id:'translate', label:'Translate', icon:'lang', c:'ai', ai:1, write:1, when: () => !files.length && typed().length > 0, param:{name:'lang', ph:'Language, e.g. Hindi'}, prompt: v => `Translate this into ${v}. Return only the translation.`}
];
const ACT = id => ACTIONS.find(a => a.id === id);
const extOf = f => (f.name.split('.').pop() || '').toLowerCase();
const fmtCache = {};
async function loadFormats(){
  const need = [...new Set(files.map(extOf))].filter(e => !(e in fmtCache));
  if (!need.length) return;
  try{ const r = await (await api('/api/convert/formats?exts=' + encodeURIComponent(need.join(',')))).json(); Object.assign(fmtCache, r.targets); }
  catch{ need.forEach(e => fmtCache[e] = []); }
  paintDock();
}
function convertTargets(){
  if (!files.length) return [];
  return files.map(f => fmtCache[extOf(f)] || []).reduce((a, b) => a.filter(x => b.includes(x)));
}
let presetTo = null;
const FMT_NAME = {docx:'Word', xlsx:'Excel', pptx:'PowerPoint', odt:'ODT', ods:'ODS', odp:'ODP', md:'Markdown', txt:'Text', jpg:'JPG'};
const fmtLabel = x => FMT_NAME[x] || x.toUpperCase();
const TILES = [['compress','Compress'],['merge','Merge PDFs'],['split','Split PDF'],['delete','Remove pages'],['from-images','Images to PDF'],['convert','Convert'],['rotate','Rotate PDF'],['summary','Summarise']];
$('#tiles').innerHTML = TILES.map(([id, label]) => { const a = ACT(id); return `<button class="tile" data-t="${id}"><span class="d c-${a.c}">${ic(a.icon, 19)}</span><b>${label}</b></button>`; }).join('');
$$('#tiles .tile').forEach(b => b.onclick = () => startTool(b.dataset.t));
function startTool(id){
  const a = ACT(id);
  if (a.write){ $('#input').focus(); return; }
  if (files.length && a.when()) return choose(a);
  files = []; paintDock(); pending = id; presetTo = null; picker.accept = a.accept || ''; picker.click();
}

/* ===================== dock ===================== */
function paintDock(){
  const ctx = $('#ctx');
  $('#stage').classList.toggle('hasfiles', files.length > 0);
  ctx.hidden = !files.length && !ACTIONS.some(a => a.write && a.when());
  $('#files').innerHTML = files.map((f, i) => { const [t, c] = FT[KIND(f)];
    return `<span class="fchip"><span class="ft ${c}">${t}</span><span class="t">${esc(f.name)}</span><small>${kb(f.size)}</small><button data-i="${i}" title="Remove" aria-label="Remove ${esc(f.name)}">${ic('x')}</button></span>`; }).join('');
  $$('#files button').forEach(b => b.onclick = () => { files.splice(+b.dataset.i, 1); closeParam(); paintDock(); });
  const acts = ACTIONS.filter(a => a.when());
  const shown = acts.slice(0, 7), rest = acts.length - shown.length;
  const html = shown.map(a => `<button class="act" data-a="${a.id}"><span class="d c-${a.c}">${ic(a.icon)}</span>${a.label}</button>`).join('')
    + (rest > 0 ? `<button class="act" data-more="1"><span class="d" style="background:var(--sunken);color:var(--ink-2)">${ic('more')}</span>${rest} more</button>` : '');
  if ($('#acts').dataset.sig !== html){ $('#acts').innerHTML = html; $('#acts').dataset.sig = html;
    $$('#acts .act').forEach(b => b.onclick = () => b.dataset.more ? openPal() : choose(ACT(b.dataset.a))); }
  $('#input').placeholder = files.length ? 'Ask about ' + (files.length === 1 ? 'this file' : 'these files') + ', or pick a tool' : 'Ask something, or drop a file here';
  setBusyUI(); paintEmpty();
}
function paintEmpty(){
  const noModels = S.modelsLoaded && !S.models.length;
  $('#onboard').hidden = !noModels;
  $('#greet').innerHTML = files.length ? 'Ready <span>when you are</span>' : 'Drop a file <span>to get started</span>';
  const chips = files.length
    ? [['Summarise this', () => run(ACT('summary'))], ['Key points', () => doc1() ? run(ACT('points')) : ask('List the key points of this.', 'Key points')],
       ['What dates and deadlines are in it?', () => ask('List every date, deadline and amount mentioned, with what each one is for.')], ['Ask a question about it', () => $('#input').focus()]]
    : [['Explain something simply', 'Explain this simply, like I am new to it: '], ['Help me write an email', 'Help me write a short, friendly email to '],
       ['Brainstorm ideas', 'Give me 10 ideas for '], ['Plan my week', 'Help me plan my week. Here is what I have on: ']];
  $('#chips').innerHTML = noModels ? '' : chips.map(([l], i) => `<button class="chip" data-c="${i}">${esc(l)}</button>`).join('');
  $$('#chips .chip').forEach(b => b.onclick = () => { const v = chips[+b.dataset.c][1]; if (typeof v === 'function') v(); else { $('#input').value = v; grow(); $('#input').focus(); paintDock(); } });
}

/* ===================== parameters ===================== */
function closeParam(){ $('#param').hidden = true; $('#param').innerHTML = ''; }
function niceSize(b){ return b >= 1048576 ? (b / 1048576).toFixed(b >= 10485760 ? 0 : 1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB'; }
function chooseCompress(a){
  const box = $('#param'), orig = files.reduce((t, f) => t + f.size, 0), each = files.length > 1;
  const lo = Math.max(10 * 1024, orig * 0.01), hi = Math.max(lo * 1.5, orig * 0.95);
  const toV = b => Math.round(1000 * Math.log(Math.min(hi, Math.max(lo, b)) / lo) / Math.log(hi / lo));
  const fromV = v => lo * Math.pow(hi / lo, v / 1000);
  let mode = store.get('cmpMode', 'ebook'), target = Math.min(hi, Math.max(lo, orig * 0.5));
  box.hidden = false; box.className = 'param cmp';
  box.innerHTML = `<span class="d c-${a.c}" style="width:26px;height:26px;border-radius:8px;display:grid;place-items:center">${ic('shrink', 15)}</span><b>Compress</b>
    <div class="seg" id="seg">${[['ebook','Balanced'],['screen','Smallest'],['printer','Best quality'],['target','Target size']].map(([k, l]) => `<button data-m="${k}">${l}</button>`).join('')}</div>
    <span style="flex:1"></span><button class="btn primary" id="pgo">Compress</button><button class="ib" id="px" title="Cancel">${ic('x')}</button>
    <div class="tgt" id="tgt" hidden><small>${each ? 'Each file' : 'Size'}</small><input type="range" id="rng" min="0" max="1000" step="1" aria-label="Target size">
      <input class="num" id="num" inputmode="decimal" aria-label="Target size number"><select id="unit" aria-label="Unit"><option>KB</option><option>MB</option></select><small>of ${niceSize(each ? orig / files.length : orig)}</small></div>
    <div class="tgt" id="tgtp" hidden><small>Quick</small><div class="presets">${[50,100,200,500,1024,2048].filter(k => k * 1024 < (each ? orig / files.length : orig)).map(k => `<button data-k="${k}">${k >= 1024 ? k / 1024 + ' MB' : k + ' KB'}</button>`).join('')}</div></div>`;
  const setTarget = (b, fromSlider) => {
    target = Math.max(5 * 1024, b);
    const mb = target >= 1048576;
    if (document.activeElement !== $('#num')){ $('#unit').value = mb ? 'MB' : 'KB'; $('#num').value = mb ? (target / 1048576).toFixed(target >= 10485760 ? 0 : 1) : Math.round(target / 1024); }
    if (!fromSlider) $('#rng').value = toV(target);
  };
  const paintMode = () => { $$('#seg button').forEach(b => b.classList.toggle('on', b.dataset.m === mode)); $('#tgt').hidden = $('#tgtp').hidden = mode !== 'target'; };
  $$('#seg button').forEach(b => b.onclick = () => { mode = b.dataset.m; store.set('cmpMode', mode); paintMode(); if (mode === 'target') $('#rng').focus(); });
  $('#rng').oninput = () => setTarget(fromV(+$('#rng').value), true);
  const fromNum = () => { const v = parseFloat($('#num').value); if (v > 0) setTarget(v * ($('#unit').value === 'MB' ? 1048576 : 1024)); };
  $('#num').oninput = fromNum; $('#unit').onchange = fromNum;
  $$('#tgtp button').forEach(b => b.onclick = () => { setTarget(+b.dataset.k * 1024); });
  $('#num').onkeydown = e => { if (e.key === 'Enter') go(); };
  const go = () => { closeParam(); run(a, mode === 'target' ? {level:'ebook', target_kb: Math.max(5, Math.floor(target / 1024))} : {level: mode, target_kb: 0}); };
  $('#pgo').onclick = go; $('#px').onclick = closeParam;
  setTarget(target); paintMode(); $('#pgo').focus();
}
function choose(a){
  if (a.param && a.param.cmp) return chooseCompress(a);
  $('#param').className = 'param';
  if (!a.param){ closeParam(); return run(a); }
  const p = a.param, box = $('#param');
  box.hidden = false;
  box.innerHTML = `<span class="d c-${a.c}" style="width:26px;height:26px;border-radius:8px;display:grid;place-items:center">${ic(a.icon, 15)}</span><b>${a.label}</b>`
    + (p.fmt ? `<div class="fmtgrid">${convertTargets().map(x => `<button class="fmt" data-to="${x}">${fmtLabel(x)}</button>`).join('')}</div><input type="hidden" id="pv">`
       : p.sel ? `<select class="f" id="pv">${p.sel.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>` : `<input class="f" id="pv" placeholder="${esc(p.ph)}">`)
    + (p.fmt ? '' : `<button class="btn primary" id="pgo">Go</button>`) + `<button class="ib" id="px" title="Cancel">${ic('x')}</button>`;
  const go = () => { const v = $('#pv').value.trim(); if (!v && !p.sel && !p.optional){ $('#pv').focus(); return; } closeParam(); run(a, v); };
  if (p.fmt){ box.querySelectorAll('.fmt').forEach(b => b.onclick = () => { $('#pv').value = b.dataset.to; go(); }); $('#px').onclick = closeParam; box.querySelector('.fmt')?.focus(); return; }
  $('#pgo').onclick = go; $('#px').onclick = closeParam;
  $('#pv').onkeydown = e => { if (e.key === 'Enter') go(); if (e.key === 'Escape'){ e.stopPropagation(); closeParam(); } };
  $('#pv').focus();
}

/* ===================== thread rendering ===================== */
const scrollEl = $('#scroll');
const atBottom = () => scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 80;
function toBottom(){ scrollEl.scrollTop = scrollEl.scrollHeight; S.stick = true; $('#tobottom').hidden = true; }
scrollEl.addEventListener('scroll', () => {
  S.stick = atBottom();
  $('#tobottom').hidden = S.stick || scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 300;
}, {passive:true});
$('#tobottom').onclick = toBottom;

function mdOpts(m){ return {pages: (m.meta && m.meta.pages) || 0}; }
function display(m){ return m.content || ''; }   // Phase 4 swaps Privacy Shield placeholders back here
function paintMd(box, text, opts){
  const blocks = MD.split(text), prev = box._b || [];
  for (let i = 0; i < blocks.length; i++){
    if (prev[i] && prev[i].src === blocks[i]) continue;
    const n = document.createElement('div'); n.className = 'mdb'; n.innerHTML = MD.render(blocks[i], opts);
    if (prev[i]) box.replaceChild(n, prev[i].node); else box.appendChild(n);
    prev[i] = {src: blocks[i], node: n};
  }
  while (prev.length > blocks.length) prev.pop().node.remove();
  box._b = prev;
}
function metaLine(m){
  const bits = [modelLabel(m.model)];
  const mt = m.meta || {};
  if (mt.stopped) bits.push('Stopped');
  if (mt.elapsed != null) bits.push(mt.elapsed.toFixed(1) + 's');
  if (mt.speed) bits.push(mt.speed + ' tok/s');
  return bits.filter(Boolean).join(' · ');
}
function toolSub(m){
  const mt = m.meta || {};
  if (mt.info || mt.size) return subline(mt.size || 0, mt.info || '');
  return esc(mt.subText || '');
}
function msgEl(m){
  const el = document.createElement('div');
  el.dataset.id = m.id;
  const mt = m.meta || {};
  if (m.role === 'user'){
    el.className = 'uwrap msg still';
    const editable = !mt.tool && !mt.prompt;
    el.innerHTML = `<div class="u">${mt.files && mt.files.length ? `<div class="att">${mt.files.map(f => `<span>${ic('file')}${esc(f.name)}</span>`).join('')}</div>` : ''}${esc(display(m))}</div>`
      + `<div class="tools">${editable ? `<button class="chipbtn" data-act="edit">${ic('edit')}Edit</button>` : ''}<button class="chipbtn" data-act="copy">${ic('copy')}Copy</button></div>`;
    return el;
  }
  if (m.role === 'tool'){
    const st = mt.state || 'done', a = ACT(mt.act) || {c:'pdf', icon:'file'};
    el.className = `msg card still ${st}`;
    el.innerHTML = `<span class="badge2 c-${a.c}">${st === 'fail' ? ic('alert') : ic(a.icon)}</span><div class="grow"><div class="nm">${esc(mt.title || '')}</div><div class="sub">${toolSub(m)}</div></div>`
      + (mt.path && desktop() && st === 'done' ? `<button class="btn" data-act="open">${ic('folder')}Show</button>` : '');
    return el;
  }
  el.className = 'msg a still';
  el.innerHTML = `<span class="av"></span><div class="content"><div class="notes"></div><div class="thk"></div><div class="body md"></div><div class="tools"></div></div>`;
  paintAssistant(el, m);
  return el;
}
function paintAssistant(el, m){
  const mt = m.meta || {}, live = !!m.live;
  el.querySelector('.av').className = 'av' + (mt.error ? ' err' : '');
  el.querySelector('.av').innerHTML = archW(15);
  const notes = (mt.notes || []).join(' ');
  const nb = el.querySelector('.notes');
  if (nb._v !== notes){ nb._v = notes; nb.innerHTML = notes ? `<div class="note">${esc(notes)}</div>` : ''; }
  const tb = el.querySelector('.thk');
  if (m.thinking){
    let d = tb.querySelector('details');
    if (!d){ tb.innerHTML = `<details class="th"><summary></summary><div class="tx"></div></details>`; d = tb.querySelector('details'); if (live) d.open = true; }
    const lbl = live && !m.content ? 'Thinking…' : 'Thought process';
    const s = d.querySelector('summary'); if (s._v !== lbl){ const was = s._v; s._v = lbl; s.innerHTML = ic('bulb', 14) + lbl; if (was === 'Thinking…' && m.content) d.open = false; } // fold away once the answer starts
    const tx = d.querySelector('.tx'); if (tx._v !== m.thinking.length){ tx._v = m.thinking.length; tx.textContent = m.thinking; }
  } else if (tb.innerHTML) tb.innerHTML = '';
  const body = el.querySelector('.body');
  body.classList.toggle('errtxt', !!mt.error);
  body.classList.toggle('live-caret', live && !!m.content);
  const text = display(m);
  if (!text && live){ if (!body.querySelector('.typing')){ body.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>'; body._b = null; } }
  else { if (body.querySelector('.typing')) body.innerHTML = ''; paintMd(body, text || (live ? '' : '(no answer)'), mdOpts(m)); }
  const tools = el.querySelector('.tools');
  const sig = live ? 'live' : `${m.id}|${metaLine(m)}|${isLastAssistant(m)}`;
  if (tools._v !== sig){
    tools._v = sig;
    tools.innerHTML = live ? '' : `<button class="chipbtn" data-act="copy">${ic('copy')}Copy</button>`
      + (isLastAssistant(m) ? `<button class="chipbtn" data-act="regen">${ic('regen')}Regenerate</button>` : '')
      + `<button class="chipbtn" data-act="save">${ic('save')}Save</button><span class="meta">${esc(metaLine(m))}</span>`;
  }
}
function isLastAssistant(m){ const ms = S.conv ? S.conv.messages : []; return ms.length && ms[ms.length - 1] === m && m.role === 'assistant'; }
function markLast(){ $$('#thread .a.last').forEach(x => x.classList.remove('last')); const l = $('#thread > :last-child'); if (l && l.classList.contains('a')) l.classList.add('last'); }
function renderThread(){
  const gen = ++S.gen, th = $('#thread');
  th.innerHTML = '';
  const msgs = S.conv ? S.conv.messages : [];
  setEmpty(!msgs.length, true);
  const N = 40, start = Math.max(0, msgs.length - N), frag = document.createDocumentFragment();
  for (let i = start; i < msgs.length; i++) frag.appendChild(msgEl(msgs[i]));
  th.appendChild(frag); markLast();
  toBottom();
  let end = start;
  const more = () => { // older messages are added above, a chunk at a time, without moving the view
    if (gen !== S.gen || end <= 0) return;
    const from = Math.max(0, end - 60), f = document.createDocumentFragment();
    for (let i = from; i < end; i++) f.appendChild(msgEl(msgs[i]));
    const h = scrollEl.scrollHeight, top = scrollEl.scrollTop, stick = S.stick;
    th.prepend(f); end = from;
    if (stick) scrollEl.scrollTop = scrollEl.scrollHeight; else scrollEl.scrollTop = top + scrollEl.scrollHeight - h;
    setTimeout(more, 16);
  };
  if (start > 0) setTimeout(more, 50);
}
function setEmpty(empty, instant){
  const dock = $('#dock'), stage = $('#stage');
  if (stage.classList.contains('empty') === empty) return;
  const before = dock.getBoundingClientRect().top;
  stage.classList.toggle('empty', empty);
  $('#hero').hidden = !empty;
  $('#main').classList.toggle('busy-thread', !empty);
  if (instant) return;
  const after = dock.getBoundingClientRect().top;
  dock.animate([{transform:`translateY(${before - after}px)`}, {transform:'none'}], {duration:420, easing:'cubic-bezier(.2,.8,.2,1)'});
}
function appendMsg(conv, m){
  conv.messages.push(m);
  if (S.conv !== conv) return;
  const wasEmpty = conv.messages.length === 1;
  if (wasEmpty) setEmpty(false);
  const el = msgEl(m); el.classList.remove('still');
  $('#thread').appendChild(el);
  $$('#thread .a').forEach(x => { const mm = conv.messages.find(y => y.id === x.dataset.id); if (mm && mm !== m) paintAssistant(x, mm); });
  markLast(); toBottom();
}
function repaint(m){
  if (!S.conv || !S.conv.messages.includes(m)) return;
  const el = $(`#thread > [data-id="${CSS.escape(m.id)}"]`); if (!el) return;
  if (m.role === 'assistant') paintAssistant(el, m);
  else { const n = msgEl(m); el.replaceWith(n); markLast(); }
  if (S.stick) scrollEl.scrollTop = scrollEl.scrollHeight;
}
const dirty = new Set(); let raf = 0;
function schedule(m){ dirty.add(m); if (!raf) raf = requestAnimationFrame(() => { raf = 0; const d = [...dirty]; dirty.clear(); d.forEach(repaint); }); }

$('#thread').addEventListener('click', async e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  const el = b.closest('[data-id]'), m = S.conv && S.conv.messages.find(x => x.id === el.dataset.id); if (!m) return;
  const act = b.dataset.act;
  if (act === 'copy'){ await navigator.clipboard.writeText(display(m)); toast('Copied'); }
  else if (act === 'save'){ if (await saveText('haven.md', display(m))) toast('Saved'); }
  else if (act === 'regen') regenerate(m);
  else if (act === 'edit') startEdit(m);
  else if (act === 'open') window.pywebview.api.open_folder(m.meta.path);
});
document.addEventListener('click', e => {
  const cp = e.target.closest('.code .cp');
  if (cp){ navigator.clipboard.writeText(cp.closest('.code').querySelector('code').textContent); toast('Copied'); }
  const ln = e.target.closest('.lnk[data-href]');
  if (ln){ e.preventDefault(); const u = ln.dataset.href; if (/^https:\/\//i.test(u)) desktop() ? window.pywebview.api.open_url(u) : window.open(u, '_blank', 'noopener,noreferrer'); }
  const ext = e.target.closest('[data-ext]'); if (ext){ e.preventDefault(); desktop() ? window.pywebview.api.open_url(ext.dataset.ext) : window.open(ext.dataset.ext, '_blank', 'noopener'); }
  if (!e.target.closest('.popmenu') && !e.target.closest('[data-menu]')) closeMenus();
  if (!$('#picker').hidden && !e.target.closest('#picker') && !e.target.closest('#pill') && !e.target.closest('#noticebtn')) closePicker();
});

/* ===================== AI ===================== */
const readB64 = f => new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(',')[1]); r.onerror = bad; r.readAsDataURL(f); });
async function attachments(){
  for (const f of files) if (f.size > 25 * 1048576) throw new Error(`${f.name} is over 25 MB`);
  return Promise.all(files.map(async f => ({name: f.name, mime: f.type, data: await readB64(f)})));
}
async function stream(body, on, signal){
  const r = await api('/api/chat', {method:'POST', signal, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  if (!r.ok) throw new Error(await errorOf(r));
  const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
  for (;;){ const {value, done} = await rd.read(); if (done) break; buf += dec.decode(value, {stream:true}); let k;
    while ((k = buf.indexOf('\n')) >= 0){ const ln = buf.slice(0, k); buf = buf.slice(k + 1); if (ln.trim()){ let j; try{ j = JSON.parse(ln); }catch{ continue; } on(j); } } }
}
const liveHere = () => !!(S.conv && S.live.has(S.conv.id));
function setBusyUI(){
  const on = liveHere(), b = $('#send');
  b.classList.toggle('stop', on); b.innerHTML = ic(on ? 'stop' : 'up'); b.title = on ? 'Stop (Esc)' : 'Send (Enter)'; b.setAttribute('aria-label', on ? 'Stop' : 'Send');
  b.disabled = !on && !typed();
}
const thinking = () => $('#think').getAttribute('aria-pressed') === 'true' && !$('#think').hidden;
function historyOf(conv){
  return conv.messages.filter(m => (m.role === 'user' && !(m.meta || {}).tool) || (m.role === 'assistant' && m.content && !(m.meta || {}).error && !m.live)).slice(-16)
    .map(m => ({role: m.role, content: m.role === 'user' ? ((m.meta || {}).prompt || m.content) : m.content}));
}
async function saveMsg(conv, m){
  const body = {id: m.id, role: m.role, content: m.content || '', thinking: m.thinking || '', model: m.model || '', meta: m.meta || {}, created: m.created};
  try{ await jpost(`/api/conversations/${conv.id}/messages`, body); }catch{}
}
function useModel(id){ S.recent = [id, ...S.recent.filter(x => x !== id)].slice(0, 6); store.set('recentModels', S.recent); }

async function ask(prompt, label, system, opt = {}){
  if (liveHere()) return;
  const info = curInfo();
  if (!S.model || !info){ if (S.modelsLoaded && !S.models.length){ toast('No model yet. Start Ollama or add a key in Settings.'); return; } updateNotice(); openPicker(); return; }
  let atts = [];
  try{ atts = await attachments(); }catch(e){ toast(e.message); return; }
  const conv = await ensureConv();
  if (!opt.regen){
    const um = {id: uid(), role:'user', content: label || prompt, model:'', created: Date.now() / 1000,
      meta: {prompt: label ? prompt : undefined, system, files: files.length ? files.map(f => ({name: f.name, size: f.size})) : undefined, tool: undefined}};
    appendMsg(conv, um); await saveMsg(conv, um);
    if (!conv.title) refreshTitle(conv); // the sidebar shows the real title straight away
  }
  const hist = historyOf(conv);
  const am = {id: uid(), role:'assistant', content:'', thinking:'', model: S.model, meta: {notes: []}, live: 1, created: Date.now() / 1000};
  appendMsg(conv, am);
  const ctrl = new AbortController(); S.live.set(conv.id, {ctrl, msg: am});
  useModel(S.model); setBusyUI(); renderSide();
  const t0 = performance.now();
  let httpFailed = false;
  try{
    await stream({model: S.model, think: thinking(), files: atts, messages: hist, system, save: {conversation_id: conv.id, message_id: am.id}}, j => {
      if (j.error){ am.content += (am.content ? '\n\n' : '') + j.error; am.meta.error = true; }
      if (j.note) am.meta.notes.push(j.note);
      if (j.thinking) am.thinking += j.thinking;
      if (j.content) am.content += j.content;
      if (j.done){ if (j.speed) am.meta.speed = j.speed; if (j.usage) am.meta.usage = j.usage; }
      schedule(am);
    }, ctrl.signal);
  }catch(e){
    if (e.name === 'AbortError') am.meta.stopped = true;
    else { am.content += (am.content ? '\n\n' : '') + e.message; am.meta.error = true; httpFailed = true; }
  }
  am.meta.elapsed = (performance.now() - t0) / 1000;
  am.live = 0;
  if (S.live.get(conv.id) && S.live.get(conv.id).msg === am) S.live.delete(conv.id);
  if (httpFailed) saveMsg(conv, am); // the server never started, so it saved nothing
  cancelAnimationFrame(raf); raf = 0; dirty.clear(); repaint(am);
  setBusyUI(); refreshTitle(conv);
}
async function refreshTitle(conv){
  try{ const c = (await jget(`/api/conversations/${conv.id}`)).conversation; conv.title = c.title;
    const i = S.convs.findIndex(x => x.id === c.id); if (i >= 0) S.convs.splice(i, 1); S.convs.unshift(c); renderSide(); }catch{}
}
function stopCurrent(){ const l = S.conv && S.live.get(S.conv.id); if (l){ l.ctrl.abort(); setBusyUI(); } }
async function regenerate(m){
  if (liveHere() || !S.conv) return;
  const conv = S.conv, i = conv.messages.indexOf(m);
  const lastUser = [...conv.messages.slice(0, i)].reverse().find(x => x.role === 'user' && !(x.meta || {}).tool);
  if (!lastUser) return;
  await jpost(`/api/conversations/${conv.id}/truncate`, {from_id: m.id});
  conv.messages.splice(i);
  $(`#thread > [data-id="${CSS.escape(m.id)}"]`)?.remove();
  const mt = lastUser.meta || {};
  ask(mt.prompt || lastUser.content, null, mt.system, {regen: true});
}
function startEdit(m){
  if (liveHere()) return;
  S.editing = m.id; $('#editing').hidden = false;
  $('#input').value = m.content; grow(); paintDock(); $('#input').focus();
  $('#input').setSelectionRange($('#input').value.length, $('#input').value.length);
}
function cancelEdit(){ S.editing = null; $('#editing').hidden = true; }
$('#editcancel').onclick = () => { cancelEdit(); $('#input').value = ''; grow(); paintDock(); $('#input').focus(); };

/* ===================== run actions ===================== */
async function run(a, v){
  if (a.write){
    const text = typed(); $('#input').value = ''; grow(); paintDock();
    return ask(a.prompt(v) + '\n\nTEXT:\n' + text, `${a.label}${v ? ' (' + v + ')' : ''}\n${text.length > 180 ? text.slice(0, 180) + '…' : text}`);
  }
  if (a.ai) return ask(a.prompt(v), a.label, a.id === 'ocr' ? 'You are a precise OCR engine.' : undefined, {whole: a.whole});
  return runFile(a, v);
}
async function runFile(a, v){
  const names = files.map(f => f.name), fd = new FormData();
  files.forEach(f => fd.append(a.multi ? 'files' : 'file', f));
  if (a.param && a.param.cmp) Object.entries(v || {}).forEach(([k, x]) => fd.append(k, x));
  else if (a.param) fd.append(a.param.name, v || '');
  Object.entries(a.extra || {}).forEach(([k, x]) => fd.append(k, x));
  const opt = a.param && a.param.cmp ? (v && v.target_kb ? 'to ' + niceSize(v.target_kb * 1024) + (files.length > 1 ? ' each' : '') : ({ebook:'Balanced', screen:'Smallest', printer:'Best quality'})[v && v.level]) : a.param && a.param.fmt ? fmtLabel(v) : a.param && a.param.sel ? (a.param.sel.find(s => s[0] === v) || [, v])[1] : v;
  const conv = await ensureConv();
  const um = {id: uid(), role:'user', content: a.id === 'convert' ? 'Convert to ' + opt : a.label + (!opt ? '' : opt.startsWith('to ') ? ' ' + opt : ', ' + opt.toLowerCase()),
    meta: {files: files.map(f => ({name: f.name, size: f.size})), tool: 1}, created: Date.now() / 1000};
  appendMsg(conv, um); saveMsg(conv, um).then(() => { if (!conv.title) refreshTitle(conv); });
  const item = {id: uid(), role:'tool', content:'', meta: {act: a.id, state:'work', title: a.label + '…', subText: names.join(', ')}, created: Date.now() / 1000};
  appendMsg(conv, item);
  const done = () => { repaint(item); saveMsg(conv, item); };
  try{
    if (a.text){
      const r = await api(a.ep, {method:'POST', body: fd});
      if (!r.ok) throw new Error(await errorOf(r));
      const text = await r.text(), empty = text.replace(/--- Page \d+ ---/g, '').trim().length < 20;
      Object.assign(item.meta, {state:'done', title: empty ? 'No text in this PDF' : 'Text pulled out', subText: empty ? 'This looks like a scan. Try Read text.' : `${text.length.toLocaleString()} characters`});
      done();
      if (!empty){ const tm = {id: uid(), role:'assistant', content: text, model:'', meta:{}, created: Date.now() / 1000}; appendMsg(conv, tm); saveMsg(conv, tm); }
      return;
    }
    const r = await api(a.ep, {method:'POST', body: fd, headers: desktop() ? {'X-Desk-Store':'1'} : {}});
    if (!r.ok) throw new Error(await errorOf(r));
    if (desktop()){
      const d = await r.json(); const s = await window.pywebview.api.save_result(d.id);
      if (s.cancelled) Object.assign(item.meta, {state:'fail', title:'Save cancelled', subText:''});
      else if (s.error) throw new Error(s.error);
      else Object.assign(item.meta, {state:'done', title: s.path.split(/[\\/]/).pop(), size: d.size, info: d.info, path: s.path, subText:''});
    } else {
      const blob = await r.blob(), nm = (r.headers.get('Content-Disposition') || '').match(/filename="(.+?)"/)?.[1] || 'result';
      const l = Object.assign(document.createElement('a'), {href: URL.createObjectURL(blob), download: nm}); document.body.appendChild(l); l.click(); l.remove();
      Object.assign(item.meta, {state:'done', title: nm, size: blob.size, info: r.headers.get('X-Info') || '', subText:''});
    }
  }catch(e){ Object.assign(item.meta, {state:'fail', title: e.message, subText:''}); }
  done();
}
function subline(size, info){
  let j = null; try{ j = info && String(info).trim().startsWith('{') ? JSON.parse(info) : null; }catch{}
  if (!j || !j.before) return kb(size);
  const before = +j.before || 0, after = +j.after || 0, target = +j.target || 0;
  const pct = Math.max(0, Math.round(100 - after * 100 / before));
  const hit = target ? (after <= target ? `<span class="save">under ${niceSize(target)}</span>` : `<span class="miss">couldn't get under ${niceSize(target)}, this is the smallest</span>`) : '';
  return `<div class="sz"><span>${niceSize(before)}</span><span class="arrow">${ic('arrow', 14)}</span><b>${niceSize(after)}</b>`
    + (pct > 0 ? `<span class="save">${pct}% smaller</span>` : `<span class="miss">${esc(j.note || 'already as small as it gets')}</span>`) + hit + `</div>`
    + `<div class="bar"><i style="width:${Math.max(3, 100 - pct)}%"></i></div>`;
}
async function saveText(name, text){
  if (desktop()){ const r = await window.pywebview.api.save_text(name, text); return r && r.path; }
  const l = Object.assign(document.createElement('a'), {href: URL.createObjectURL(new Blob([text], {type:'text/plain'})), download: name});
  document.body.appendChild(l); l.click(); l.remove(); return name;
}

/* ===================== composer ===================== */
const grow = () => { const t = $('#input'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, innerHeight * 0.4) + 'px'; };
$('#input').oninput = () => { grow(); paintDock(); };
$('#input').onkeydown = e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing){ e.preventDefault(); submit(); }
  else if (e.key === 'ArrowUp' && !$('#input').value && S.conv){
    const last = [...S.conv.messages].reverse().find(m => m.role === 'user' && !(m.meta || {}).tool && !(m.meta || {}).prompt);
    if (last){ e.preventDefault(); startEdit(last); }
  }
};
$('#send').onclick = () => liveHere() ? stopCurrent() : submit();
async function submit(){
  const t = typed(); if (!t || liveHere()) return;
  $('#input').value = ''; grow(); paintDock(); $('#input').focus();
  if (S.editing && S.conv){
    const id = S.editing; cancelEdit();
    const i = S.conv.messages.findIndex(m => m.id === id);
    if (i >= 0){
      await jpost(`/api/conversations/${S.conv.id}/truncate`, {from_id: id});
      S.conv.messages.splice(i); renderThread();
    }
  }
  ask(t);
}
$('#think').setAttribute('aria-pressed', String(store.get('think', false)));
$('#think').onclick = () => { const on = $('#think').getAttribute('aria-pressed') !== 'true'; $('#think').setAttribute('aria-pressed', String(on)); store.set('think', on); };

/* ===================== command palette ===================== */
let pi = 0, pitems = [];
function openPal(){ closePicker(); $('#pal').classList.add('on'); $('#scrim').classList.add('on'); $('#palq').value = ''; pi = 0; listPal(); requestAnimationFrame(() => { if ($('#pal').classList.contains('on')) $('#palq').focus(); }); }
function closePal(){ $('#pal').classList.remove('on'); if (!$('#sheet').classList.contains('on')) $('#scrim').classList.remove('on'); }
function listPal(){
  const q = $('#palq').value.toLowerCase().trim();
  const tools = ACTIONS.filter(a => !a.write).map(a => ({...a, ready: a.when()}));
  const app = [{id:'_new', label:'New chat', icon:'edit', c:'pdf', k:'Ctrl N'}, {id:'_model', label:'Pick a model', icon:'cpu', c:'ai', k:'Ctrl M'}, {id:'_files', label:'Add files', icon:'clip', c:'pdf'}, {id:'_think', label:'Think mode', icon:'bulb', c:'ai'}, {id:'_settings', label:'Settings', icon:'gear', c:'pdf'}];
  const groups = [['Works with your files', tools.filter(a => a.ready)], ['All tools', tools.filter(a => !a.ready)], ['App', app]]
    .map(([g, list]) => [g, list.filter(a => !q || a.label.toLowerCase().includes(q))]).filter(([, l]) => l.length);
  pitems = groups.flatMap(([, l]) => l); pi = Math.min(pi, Math.max(0, pitems.length - 1));
  let n = 0;
  $('#pall').innerHTML = groups.map(([g, l]) => `<li class="grp">${g}</li>` + l.map(a => { const k = n++;
    return `<li class="it ${k === pi ? 'on' : ''}" data-k="${k}"><span class="d c-${a.c}">${ic(a.icon)}</span>${esc(a.label)}<span class="k">${a.k || (a.ready ? 'Enter' : '')}</span></li>`; }).join('')).join('')
    || '<li class="grp" style="text-transform:none">No match</li>';
  $$('#pall .it').forEach(li => { li.onclick = () => pickPal(+li.dataset.k); li.onmousemove = () => { if (pi !== +li.dataset.k){ pi = +li.dataset.k; $$('#pall .it').forEach(x => x.classList.toggle('on', +x.dataset.k === pi)); } }; });
  const on = $('#pall .it.on'); if (on) on.scrollIntoView({block:'nearest'});
}
function pickPal(k){
  const a = pitems[k]; if (!a) return; closePal();
  if (a.id === '_new') return newChat();
  if (a.id === '_model') return openPicker();
  if (a.id === '_files') return $('#b-attach').click();
  if (a.id === '_think') return $('#think').click();
  if (a.id === '_settings') return openSheet();
  startTool(a.id);
}
$('#palq').oninput = () => { pi = 0; listPal(); };
$('#palq').onkeydown = e => {
  if (e.key === 'ArrowDown'){ pi = Math.min(pi + 1, pitems.length - 1); listPal(); e.preventDefault(); }
  if (e.key === 'ArrowUp'){ pi = Math.max(pi - 1, 0); listPal(); e.preventDefault(); }
  if (e.key === 'Enter') pickPal(pi);
  if (e.key === 'Escape'){ e.stopPropagation(); closePal(); $('#input').focus(); }
};
$('#scrim').onclick = () => { closePal(); closeSheet(); };
$('#b-search').onclick = openPal;
const THEMES = ['system', 'light', 'dark'], TICON = {system:'monitor', light:'sun', dark:'moon'};
$$('#theme button').forEach(b => b.innerHTML = ic(TICON[b.dataset.t]));
function setTheme(t, save){
  if (!THEMES.includes(t)) t = 'system';
  if (t === 'system') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  $$('#theme button').forEach(b => b.setAttribute('aria-checked', b.dataset.t === t));
  $('#theme .knob').style.transform = `translateX(${THEMES.indexOf(t) * 30}px)`;
  if (save) store.set('theme', t);
}
$$('#theme button').forEach(b => b.onclick = () => setTheme(b.dataset.t, true));
$('#theme').onkeydown = e => { const k = {ArrowRight:1, ArrowLeft:-1}[e.key]; if (!k) return; const cur = THEMES.indexOf(store.get('theme', 'system')); const n = THEMES[(cur + k + 3) % 3]; setTheme(n, true); $(`#theme [data-t=${n}]`).focus(); };
setTheme(store.get('theme', 'system'));

/* ===================== keyboard ===================== */
addEventListener('keydown', e => {
  const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
  if (mod && !e.shiftKey && k === 'k'){ e.preventDefault(); $('#pal').classList.contains('on') ? closePal() : openPal(); }
  else if (mod && !e.shiftKey && k === 'n'){ e.preventDefault(); newChat(); }
  else if (mod && !e.shiftKey && k === 'm'){ e.preventDefault(); $('#picker').hidden ? openPicker() : closePicker(); }
  else if (mod && e.shiftKey && k === 'f'){ e.preventDefault(); if (narrow()) document.documentElement.classList.add('side-open'); else if (document.documentElement.classList.contains('side-off')) toggleSide(); $('#cq').focus(); $('#cq').select(); }
  else if (e.key === 'Escape'){
    if ($$('.popmenu').length){ closeMenus(); return; }
    if (!$('#picker').hidden){ closePicker(); return; }
    if ($('#pal').classList.contains('on') || $('#sheet').classList.contains('on')){ closePal(); closeSheet(); return; }
    if (!$('#param').hidden){ closeParam(); return; }
    if (liveHere()){ stopCurrent(); $('#input').focus(); return; }
    if (S.editing){ $('#editcancel').click(); return; }
    closeDrawer();
  }
});

/* ===================== settings ===================== */
const st = (c, t) => `<span class="st ${c}">${esc(t)}</span>`;
let KINDS = [];
function openSheet(focusKey){ closePicker(); $('#sheet').classList.add('on'); $('#scrim').classList.add('on'); loadSettings(); if (focusKey) requestAnimationFrame(() => $('#nkey').focus()); }
function closeSheet(){ $('#sheet').classList.remove('on'); if (!$('#pal').classList.contains('on')) $('#scrim').classList.remove('on'); }
$('#b-gear').onclick = () => openSheet(); $('#b-close').onclick = closeSheet;
$('#ob-key').onclick = () => openSheet(true);
$('#ob-ollama').onclick = () => desktop() ? window.pywebview.api.open_url('https://ollama.com/download') : window.open('https://ollama.com/download', '_blank', 'noopener');
$('#ob-retry').onclick = async () => { await refreshModels(true); toast(S.models.length ? `Found ${S.models.length} models` : 'Still no models'); };
async function loadSettings(){
  let j;
  try{ j = await jget('/api/providers'); }catch{ return; }
  KINDS = j.kinds;
  $('#nkind').innerHTML = '<option value="">Pick the provider…</option>' + KINDS.map(k => `<option value="${esc(k.kind)}">${esc(k.name)}</option>`).join('');
  $('#provlist').innerHTML = j.providers.map(p => {
    const sub = p.local ? (p.status === 'ok' ? `Running · ${p.model_count} models` : 'Not running') :
      [p.hint, p.source === 'env' ? 'from environment (read-only)' : p.source === 'file' ? 'plain file' : 'Credential Manager',
       p.status === 'unavailable' ? 'unavailable – ' + p.message : p.model_count ? p.model_count + ' models' : ''].filter(Boolean).join(' · ');
    return `<div class="prov ${p.enabled ? '' : 'off'}" data-id="${esc(p.id)}"><span class="badge ${p.local ? 'private' : 'cloud'}">${p.local ? 'Private' : 'Cloud'}</span>`
      + `<div class="grow"><div class="nm">${esc(p.name)}${p.label ? ' · ' + esc(p.label) : ''}</div><div class="sub">${st(p.local ? (p.status === 'ok' ? 'ok' : 'no') : p.status === 'unavailable' ? 'part' : 'cloud', sub)}</div></div>`
      + (p.local || p.source === 'env' ? '' : `<button class="btn small ghost" data-tog="${esc(p.id)}">${p.enabled ? 'Turn off' : 'Turn on'}</button><button class="ib" data-del="${esc(p.id)}" title="Remove this key">${ic('trash', 16)}</button>`)
      + `</div>`;
  }).join('');
  $('#storagenote').textContent = j.storage === 'keyring' ? 'Keys are kept in Windows Credential Manager on this PC and never shown again in full.' : 'Stored in a plain file on this PC (Windows Credential Manager isn\'t available).';
  $$('#provlist [data-del]').forEach(b => b.onclick = async () => { if (!confirm('Remove this key from Haven?')) return; await api('/api/providers/' + b.dataset.del, {method:'DELETE'}); await refreshModels(); loadSettings(); toast('Key removed'); });
  $$('#provlist [data-tog]').forEach(b => b.onclick = async () => { const p = j.providers.find(x => x.id === b.dataset.tog); await jpost('/api/providers/' + p.id, {enabled: !p.enabled}, 'PATCH'); await refreshModels(); loadSettings(); });
  try{
    const s = await jget('/api/status');
    $('#gsstatus').innerHTML = s.ghostscript ? st('ok', 'Installed') : st('part', 'Not installed');
    $('#lostatus').innerHTML = s.libreoffice ? st('ok', 'Installed') : st('part', 'Not installed');
    $('#about').innerHTML = `Haven ${esc(s.version)}. <kbd>Ctrl</kbd> <kbd>K</kbd> tools, <kbd>Ctrl</kbd> <kbd>M</kbd> model, <kbd>Ctrl</kbd> <kbd>N</kbd> new chat, <kbd>Ctrl</kbd> <kbd>Shift</kbd> <kbd>F</kbd> search chats.`;
  }catch{}
}
$('#nkind').onchange = () => { $('#nbase').hidden = $('#nkind').value !== 'custom'; };
$('#addkey').onclick = addKey;
$('#nkey').onkeydown = e => { if (e.key === 'Enter') addKey(); };
async function addKey(){
  const key = $('#nkey').value; if (!key.trim()) { $('#nkey').focus(); return; }
  const body = {key, label: $('#nlabel').value.trim()};
  if (!$('#manualrow').hidden && $('#nkind').value){ body.provider = $('#nkind').value; if (body.provider === 'custom') body.base_url = $('#nbase').value; }
  $('#keymsg').textContent = 'Checking the key…'; $('#addkey').disabled = true;
  try{
    const r = await jpost('/api/providers', body);
    const j = await r.json();
    if (!r.ok){
      $('#keymsg').textContent = j.detail || 'That key did not work.';
      if (j.unrecognised || r.status === 400) $('#manualrow').hidden = false;
      return;
    }
    $('#nkey').value = ''; $('#nlabel').value = ''; $('#manualrow').hidden = true;
    $('#keymsg').textContent = `${j.provider.name}${j.provider.label ? ' · ' + j.provider.label : ''}: ${j.models.length} chat models added.`;
    await refreshModels();
    if (!curInfo() && j.models[0]) setModel(j.models[0].full_id);
    toast(`${j.provider.name} connected`);
    loadSettings();
  } finally { $('#addkey').disabled = false; }
}

/* ===================== v0.9 chat history -> SQLite (once) ===================== */
async function migrate(){
  const raw = localStorage.getItem('thread6');
  if (raw === null) return;
  if (store.get('migrated6', false)){ localStorage.removeItem('thread6'); return; }
  let arr = [];
  try{ arr = JSON.parse(raw); }catch{}
  if (Array.isArray(arr) && arr.length){
    const strip = h => String(h || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
    const msgs = arr.map(m => m.r === 'u'
      ? {role:'user', content: m.text || '', meta: {prompt: m.prompt && m.prompt !== m.text ? m.prompt : undefined, tool: m.tool ? 1 : undefined, files: (m.files || []).map(n => ({name: String(n)}))}}
      : m.r === 'a' ? {role:'assistant', content: m.text || '', thinking: m.thinking || '', meta: {notes: m.notes ? [String(m.notes).trim()] : [], error: !!m.error, legacyInfo: m.info}}
      : {role:'tool', content:'', meta: {act: m.act, state: m.state === 'work' ? 'fail' : (m.state || 'done'), title: m.title || '', path: m.path, subText: strip(m.sub)}});
    const r = await jpost('/api/conversations/import', {title: 'Earlier chats', messages: msgs});
    if (!r.ok) return; // try again next launch
  }
  store.set('migrated6', true);
  localStorage.removeItem('thread6');
}

/* ===================== start ===================== */
(async function start(){
  paintDock(); paintModel(); $('#input').focus({preventScroll:true});
  await migrate();
  await Promise.all([refreshModels(), loadConvs()]);
  const last = store.get('conv', '');
  if (last && S.convs.some(c => c.id === last)) await openConv(last); else renderThread();
  setInterval(refreshModels, 20000);
  document.documentElement.dataset.ready = '1';
  document.documentElement.dataset.readyAt = String(Math.round(performance.now())); // ms since navigation start
})();
