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
  image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
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
  dl:'<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  info:'<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  user:'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  chats:'<path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z"/><path d="M8.5 11h7M8.5 14h4"/>', ext:'<path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
  shield:'<path d="M12 3 4 6v6c0 4.4 3.4 8.3 8 9 4.6-.7 8-4.6 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
  shieldoff:'<path d="M12 3 4 6v6c0 4.4 3.4 8.3 8 9 4.6-.7 8-4.6 8-9V6z"/><path d="M4 4l16 16"/>'
};
const ic = (n, s) => `<svg class="i" viewBox="0 0 24 24"${s ? ` style="width:${s}px;height:${s}px"` : ''} aria-hidden="true">${P[n] || ''}</svg>`;
const archW = s => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4"/><path d="M13 3v5h5v2"/><path d="M8.5 11.5h5M8.5 15h2.5"/><path d="M17.5 13.2l1.15 3.15 3.15 1.15-3.15 1.15-1.15 3.15-1.15-3.15-3.15-1.15 3.15-1.15z" fill="#fff" stroke-width="1.2"/></svg>`;
$('#mark').innerHTML = archW(16); $('#heroarch').innerHTML = archW(32); $('#droparch').innerHTML = archW(28);
[['#b-search','search'],['#b-gear','gear'],['#b-attach','clip'],['#b-close','x'],['#palicon','search'],['#ic-keys','key'],['#ic-ext','puzzle'],
 ['#b-side','side'],['#b-side-close','side'],['#ic-new','plus'],['#ic-cq','search'],['#ic-pq','search'],['#pillchev','chev'],['#tobottom','down'],
 ['#ic-editing','edit'],['#b-new','edit'],['#ic-shield','shield'],['#ic-about','info'],['#r-open','side'],['#r-new','edit'],['#r-search','search'],['#r-recent','chats'],['#ic-prof','user'],['#me-gear','gear']].forEach(([s, n]) => { const el = $(s); if (el) el.innerHTML = ic(n); });
$('#think').innerHTML = ic('bulb') + 'Think';
$('#imgmode').innerHTML = ic('image') + 'Image';
$('#ic-images').innerHTML = ic('image');
$('#send').innerHTML = ic('up');

/* ===================== state ===================== */
const S = {
  models: [], providers: [], modelsLoaded: false,
  model: store.get('model2', ''), recent: store.get('recentModels', []),
  convs: [], conv: null, live: new Map(), editing: null, stick: true, gen: 0,
  shield: true, shieldOk: store.get('shieldOk', {}), catalog: [], kinds: [], profile: {},
};
window.haven = S; // handy in DevTools (and for the UI tests)
const minfo = id => S.models.find(m => m.full_id === id) || S.catalog.find(m => m.full_id === id);
const kindInfo = k => S.kinds.find(x => x.kind === k) || {name: k};
const curInfo = () => minfo(S.model);
const provOf = pid => S.providers.find(p => p.id === pid);
const isCloud = () => { const m = curInfo(); return !!m && !m.local; };
const IMG_LABEL = {'images:hf': 'Hugging Face', 'images:cf': 'Cloudflare', 'images:pollinations': 'Pollinations'};
const modelLabel = id => { if (IMG_LABEL[id]) return IMG_LABEL[id]; const m = minfo(id); return m ? m.label : (id || '').split(':').slice(1).join(':'); };

/* ===================== models + picker ===================== */
async function refreshModels(refresh = false){
  try{
    const j = await jget('/api/models' + (refresh ? '?refresh=1' : ''));
    S.models = j.models; S.providers = j.providers; S.catalog = j.catalog || []; S.kinds = j.kinds || []; S.modelsLoaded = true;
    for (const m of S.models.concat(S.catalog)) m._q = (m.label + ' ' + m.id + ' ' + kindInfo(m.kind).name + ' ' + ((provOf(m.provider) || {}).label || '')).toLowerCase();
  }catch{ /* server busy: keep the last list */ }
  if (!S.model && S.models.length) S.model = (S.recent.find(id => S.models.some(m => m.full_id === id)) || (S.models.find(m => m.local) || S.models.find(m => !m.issue) || S.models[0]).full_id);
  paintModel();
  if (!$('#picker').hidden) renderPicker();
}
function paintModel(){
  const m = curInfo(), pill = $('#pill');
  pill.className = 'pill' + (!m ? ' none' : m.locked ? ' locked' : m.local ? '' : ' cloud');
  $('#pillname').textContent = m ? m.label : (S.model ? modelLabel(S.model) : 'Pick a model');
  $('#tag').textContent = !m ? (S.model ? 'Unavailable' : 'Off') : m.locked ? (m.local ? 'Not installed' : 'Needs key') : m.local ? 'Private' : 'Cloud';
  const k = m && kindInfo(m.kind);
  $('#foot').classList.toggle('cloud', !!m && !m.local);
  $('#foottxt').textContent = !m ? 'No model selected' : m.local ? 'Running on this laptop' : `Using ${k ? k.name : 'a cloud model'}, so messages and files go there`;
  paintShield();
  const th = $('#think');
  th.hidden = !m || m.locked || m.think === 'no';
  th.title = m && m.think === 'always' ? 'This model always thinks. On: show its thinking.' : 'Think it through first (slower)';
  updateNotice(); paintEmpty();
}
function paintShield(){
  const b = $('#shield'), m = curInfo();
  b.hidden = !m || m.local || m.locked;
  b.setAttribute('aria-pressed', String(S.shield));
  b.innerHTML = ic(S.shield ? 'shield' : 'shieldoff') + (S.shield ? 'Shield on' : 'Shield off');
  b.title = S.shield ? 'Privacy Shield is on: phone numbers, emails, PAN, Aadhaar, card and bank details are hidden before sending to the cloud'
                     : 'Privacy Shield is off: messages go to the cloud as written';
  const t = $('#shieldtg'); if (t) t.checked = S.shield;
}
async function setShield(on){
  S.shield = on; paintShield();
  try{ await jpost('/api/settings', {shield: on}); }catch{}
  toast(on ? 'Privacy Shield on' : 'Privacy Shield off');
}
let noticeAct = null;
function updateNotice(){
  const n = $('#notice'), m = curInfo();
  const show = (txt, label, act) => { $('#noticetxt').textContent = txt; $('#noticebtn').textContent = label; noticeAct = act; n.hidden = false; };
  if (!S.modelsLoaded || !S.model){ n.hidden = true; return; }
  if (m && m.locked){
    if (!m.local) return show(`${m.label} needs ${an(kindInfo(m.kind).name)} API key. Add one to use it, or pick another model.`, `Add ${kindInfo(m.kind).name} key`, () => openSheet('models', m.kind));
    const oll = provOf('ollama');
    if (oll && oll.status === 'ok') return show(`${m.label} isn't downloaded yet. In a terminal, run: ollama pull ${m.id}`, 'Copy command', () => { navigator.clipboard.writeText('ollama pull ' + m.id); toast('Copied'); });
    return show(`${m.label} runs on this PC with Ollama, which isn't running. Start Ollama, then run: ollama pull ${m.id}`, 'Get Ollama', () => openExt('https://ollama.com/download'));
  }
  if (m){ n.hidden = true; return; }
  const p = provOf(S.model.split(':')[0]);
  if (p && p.local && p.status !== 'ok') return show(`${p.name} isn't running. Start it, or pick another model.`, 'Pick a model', openPicker);
  show('Model no longer available, pick another.', 'Pick a model', openPicker);
}
const an = w => (/^(?:[AEIOU]|xAI|LM)/i.test(w) ? 'an ' : 'a ') + w;
const openExt = u => desktop() ? window.pywebview.api.open_url(u) : window.open(u, '_blank', 'noopener');
function setModel(id){
  S.model = id; store.set('model2', id);
  paintModel();
  if (S.conv && minfo(id) && !minfo(id).locked) jpost(`/api/conversations/${S.conv.id}`, {model: id}, 'PATCH');
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
  const hit = m => !toks.length || toks.every(t => m._q.includes(t));
  const LIMIT = 300; let shown = 0, more = 0;
  pitemsM = [];
  const item = (m, recent) => {
    if (shown >= LIMIT){ more++; return ''; }
    shown++; const k = pitemsM.length; pitemsM.push(m.full_id);
    const cur = m.full_id === S.model;
    return `<li class="m ${k === pk ? 'on' : ''} ${cur ? 'cur' : ''} ${m.locked ? 'locked' : ''}" role="option" data-k="${k}">`
      + `<span class="n">${esc(m.label)}${!m.locked && m.label !== m.id ? `<span class="sub"> · ${esc(m.id)}</span>` : ''}</span>`
      + (m.locked && m.note ? `<span class="pnote">${esc(m.note)}</span>` : '')
      + (m.issue ? `<span class="pnote warn" title="This model failed recently">${esc(m.issue)}</span>` : '')
      + (m.vision ? `<span title="Can see images">${ic('eye')}</span>` : '') + (m.think !== 'no' ? `<span title="Can think">${ic('bulb')}</span>` : '')
      + (m.locked ? `<span title="${m.local ? 'Not downloaded yet' : 'Needs a key'}">${ic('lock')}</span>`
                  : `<span class="badge ${m.local ? 'private' : 'cloud'}">${m.local ? 'Private' : 'Cloud'}</span>`)
      + (recent ? `<span class="sub">${esc(kindInfo(m.kind).name)}</span>` : '') + `</li>`;
  };
  let html = '';
  if (!q){
    const rec = S.recent.map(id => S.models.find(m => m.full_id === id)).filter(Boolean).slice(0, 3);
    if (rec.length) html += `<li class="grp">Recent</li>` + rec.map(m => item(m, true)).join('');
  }
  // 1) what you can use right now: local providers with models, then connected cloud keys;
  //    a local provider with nothing to offer yet (Ollama not running / no models) comes after those
  const usable = p => S.models.some(m => m.provider === p.id);
  const ordered = [...S.providers.filter(p => p.local && usable(p)), ...S.providers.filter(p => !p.local), ...S.providers.filter(p => p.local && !usable(p))];
  for (const p of ordered){
    const ms = S.models.filter(m => m.provider === p.id && hit(m));
    if (p.local){
      if (!ms.length && p.id !== 'ollama') continue;
      if (!ms.length && q && !S.catalog.some(m => m.kind === 'ollama' && hit(m))) continue;
      const st = p.status === 'ok' ? '' : 'not running';
      html += `<li class="grp">${esc(p.name)}<span class="pst">${st}</span></li>`;
      if (ms.length) html += ms.map(m => item(m)).join('');
      else {
        if (!q) html += `<li class="more">${p.status === 'ok' ? 'Ollama has no models yet. Download one below.' : 'Ollama isn\'t running. Start it to chat privately on this PC.'}</li>`;
        html += S.catalog.filter(m => m.kind === 'ollama' && hit(m)).map(m => item(m)).join('');
      }
      continue;
    }
    if (!ms.length && q) continue;
    const st = p.status === 'ok' ? '' : 'unavailable' + (p.message ? ' – ' + p.message : '');
    html += `<li class="grp">${esc(p.label ? kindInfo(p.kind).name + ' · ' + p.label : kindInfo(p.kind).name)}<span class="pst">${esc(st)}</span></li>`;
    const pop = ms.filter(m => m.popular), rest = ms.filter(m => !m.popular);
    html += pop.map(m => item(m)).join('');
    if (pop.length && rest.length) html += `<li class="sub2">More ${esc(kindInfo(p.kind).name)} models</li>`;
    html += rest.map(m => item(m)).join('');
    if (!q) html += `<li class="addrow" data-addmodel="${esc(p.id)}" data-kind="${esc(p.kind)}">${ic('plus')}Add a model by name…</li>`;
  }
  // 2) popular models from providers you haven't connected yet
  let lockedHtml = '';
  for (const k of S.kinds){
    if (k.local || k.connected || k.kind === 'custom') continue;
    const ms = S.catalog.filter(m => m.kind === k.kind && hit(m));
    if (q && !ms.length && !k.name.toLowerCase().includes(q)) continue;
    lockedHtml += `<li class="grp">${esc(k.name)}<button class="addk" data-addkey="${esc(k.kind)}">Add key</button></li>`;
    lockedHtml += ms.length ? ms.map(m => item(m)).join('')
      : `<li class="addrow" data-addkey="${esc(k.kind)}">${ic('lock')}Add a ${esc(k.name)} key to see its models</li>`;
  }
  if (lockedHtml) html += `<li class="sep">Add a key to use these</li>` + lockedHtml;
  if (!pitemsM.length && !lockedHtml) html += `<li class="more">No model matches “${esc(q)}”.</li>`;
  if (more) html += `<li class="more">${more} more. Keep typing to narrow it down.</li>`;
  $('#pl').innerHTML = html;
  const ready = S.models.length;
  $('#pstat').textContent = ready ? `${ready} ready to use` : 'Nothing connected yet';
  const on = $('#pl .m.on'); if (on) on.scrollIntoView({block:'nearest'});
  S.pickerMs = performance.now() - t0;
}
function pickModel(k){
  const id = pitemsM[k]; if (!id) return;
  const m = minfo(id);
  closePicker(); setModel(id);
  if (m && !m.locked){ useModel(id); toast(m.label); }
  $('#input').focus();
}
$('#pill').onclick = () => $('#picker').hidden ? openPicker() : closePicker();
$('#pq').oninput = () => { pk = 0; renderPicker(); };
$('#pq').onkeydown = e => {
  if (e.key === 'ArrowDown'){ pk = Math.min(pk + 1, pitemsM.length - 1); renderPicker(); e.preventDefault(); }
  else if (e.key === 'ArrowUp'){ pk = Math.max(pk - 1, 0); renderPicker(); e.preventDefault(); }
  else if (e.key === 'Enter'){ pickModel(pk); e.preventDefault(); }
  else if (e.key === 'Escape'){ closePicker(); $('#pill').focus(); e.stopPropagation(); }
};
$('#pl').onclick = e => {
  const add = e.target.closest('[data-addkey]');
  if (add){ closePicker(); return openSheet('models', add.dataset.addkey); }
  const am = e.target.closest('[data-addmodel]');
  if (am){ closePicker(); return openSheet('models', null, am.dataset.addmodel); }
  const li = e.target.closest('li.m'); if (li) pickModel(+li.dataset.k);
};
$('#prefresh').onclick = async () => { $('#prefresh').disabled = true; await refreshModels(true); $('#prefresh').disabled = false; };
$('#paddkey').onclick = () => { closePicker(); openSheet('models'); };
$('#noticebtn').onclick = () => noticeAct && noticeAct();

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
  renderThread(); renderSide(); setBusyUI(); closeDrawer(); paintDock(); peek(false, true);
}
function newChat(focus = true){
  S.gen++; S.conv = null; S.editing = null; $('#editing').hidden = true; store.set('conv', '');
  files = []; closeParam(); renderThread(); renderSide(); paintDock(); setBusyUI();
  if (focus) $('#input').focus();
}
$('#b-new').onclick = $('#b-new2').onclick = () => newChat();

/* sidebar open/close (a drawer under 900px) */
const narrow = () => innerWidth <= 760;
function toggleSide(){
  if (narrow()){ document.documentElement.classList.toggle('side-open'); return; }
  const off = document.documentElement.classList.toggle('side-off'); store.set('side', !off);
}
function closeDrawer(){ document.documentElement.classList.remove('side-open'); peek(false, true); }
let peekT;
function peek(on, now){
  clearTimeout(peekT);
  const root = document.documentElement;
  if (on){
    if (!root.classList.contains('side-off') || narrow()) return;
    peekT = setTimeout(() => { root.classList.add('side-peek'); $('#r-recent').classList.add('on'); }, now ? 0 : 120);
  } else {
    const off = () => { root.classList.remove('side-peek'); $('#r-recent').classList.remove('on'); };
    if (now) off(); else peekT = setTimeout(off, 260);
  }
}
$('#rail').addEventListener('mouseenter', () => peek(true));
$('#rail').addEventListener('mouseleave', () => peek(false));
$('#sidein').addEventListener('mouseenter', () => { if (document.documentElement.classList.contains('side-peek')) clearTimeout(peekT); });
$('#sidein').addEventListener('mouseleave', () => { if (!$('#sidein').contains(document.activeElement) || !$('#cq').value) peek(false); });
$('#r-open').onclick = () => { peek(false, true); toggleSide(); };
$('#r-new').onclick = () => { peek(false, true); newChat(); };
$('#r-recent').onclick = () => document.documentElement.classList.contains('side-peek') ? peek(false, true) : peek(true, true);
$('#r-search').onclick = () => { peek(true, true); setTimeout(() => $('#cq').focus(), 20); };
$('#r-me').onclick = $('#me').onclick = () => { peek(false, true); openSheet('profile'); };
$('#b-side').onclick = toggleSide;
$('#b-side-close').onclick = () => { if (document.documentElement.classList.contains('side-peek')){ peek(false, true); document.documentElement.classList.remove('side-off'); store.set('side', true); } else toggleSide(); };
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
const TILES = [['compress','Compress'],['merge','Merge PDFs'],['convert','Convert'],['summary','Summarise']];
$('#tiles').innerHTML = TILES.map(([id, label]) => { const a = ACT(id); return `<button class="tile" data-t="${id}"><span class="d c-${a.c}">${ic(a.icon, 19)}</span><b>${label}</b></button>`; }).join('');
$('#tiles').insertAdjacentHTML('beforeend', `<button class="tile" data-more="1" title="All tools (Ctrl K)"><span class="d" style="background:var(--sunken);color:var(--ink-2)">${ic('more', 19)}</span><b>More tools</b></button>`);
$$('#tiles .tile').forEach(b => b.onclick = () => b.dataset.more ? openPal() : startTool(b.dataset.t));
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
  const nm = (S.profile.call || S.profile.name || '').trim().split(/\s+/)[0];
  const hr = new Date().getHours(), part = hr < 5 ? 'Hello' : hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening';
  $('#greet').textContent = files.length ? (files.length === 1 ? 'What should I do with this file?' : 'What should I do with these files?') : nm ? `${part}, ${nm}` : 'What can I help with?';
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
/* Privacy Shield: the model saw [PHONE_1]; the page shows (and copies) the real value. Tolerates [PHONE 1], PHONE_1, [phone-1]. */
const PH_RE = /(?:\[\s*)?\b(EMAIL|UPI|CARD|AADHAAR|PAN|IFSC|PHONE)[ _-]?(\d{1,4})\b(?:\s*\])?/gi;
function unmask(text, map){
  if (!text || !map) return text || '';
  const canon = {};
  for (const [k, v] of Object.entries(map)) canon[k.replace(/[\[\]]/g, '').toUpperCase()] = v;
  return text.replace(PH_RE, (all, kind, n) => canon[kind.toUpperCase() + '_' + n] ?? all);
}
function display(m){ return unmask(m.content || '', m.meta && m.meta.unmask); }
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
    const tx = d.querySelector('.tx'); if (tx._v !== m.thinking.length){ tx._v = m.thinking.length; tx.textContent = unmask(m.thinking, mt.unmask); }
  } else if (tb.innerHTML) tb.innerHTML = '';
  const body = el.querySelector('.body');
  paintPics(el, body, mt.images || []);
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
const picURLs = new Map();
async function picURL(name){
  if (!picURLs.has(name)) picURLs.set(name, api('/api/images/' + encodeURIComponent(name)).then(r => r.ok ? r.blob() : Promise.reject()).then(b => URL.createObjectURL(b)));
  return picURLs.get(name);
}
function paintPics(el, body, names){
  let box = el.querySelector('.pics');
  const sig = names.join('|');
  if (!names.length){ if (box) box.remove(); return; }
  if (box && box._v === sig) return;
  if (!box){ box = document.createElement('div'); box.className = 'pics'; body.before(box); }
  box._v = sig;
  box.innerHTML = names.map(n => `<figure class="pic" data-pic="${esc(n)}"><img alt="Generated image"><figcaption>`
    + `<button class="chipbtn" data-pact="save">${ic('save')}Save</button><button class="chipbtn" data-pact="copy">${ic('copy')}Copy</button></figcaption></figure>`).join('');
  box.querySelectorAll('.pic').forEach(f => picURL(f.dataset.pic).then(u => { f.querySelector('img').src = u; }).catch(() => { f.querySelector('img').alt = 'Image file is missing'; }));
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-pact]'); if (!b) return;
  const name = b.closest('.pic').dataset.pic, blob = await (await fetch(await picURL(name))).blob();
  if (b.dataset.pact === 'copy'){
    try{ const png = blob.type === 'image/png' ? blob : await toPng(blob); await navigator.clipboard.write([new ClipboardItem({'image/png': png})]); toast('Image copied'); }
    catch{ toast('Copying images is not supported here; use Save'); }
  } else {
    const fname = 'haven-image.' + (name.split('.').pop() || 'png');
    if (desktop()){ const b64 = await readB64(blob); const r = await window.pywebview.api.save_b64(fname, b64); if (r && r.path) toast('Saved'); }
    else { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = fname; a.click(); }
  }
});
async function toPng(blob){
  const img = await createImageBitmap(blob), c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  c.getContext('2d').drawImage(img, 0, 0); return new Promise(ok => c.toBlob(ok, 'image/png'));
}
function isLastAssistant(m){ const ms = S.conv ? S.conv.messages : []; return ms.length && ms[ms.length - 1] === m && m.role === 'assistant'; }
function markLast(){ $$('#thread .a.last').forEach(x => x.classList.remove('last')); const l = $('#thread > :last-child'); if (l && l.classList.contains('a')) l.classList.add('last'); }
function renderThread(){
  const gen = ++S.gen, th = $('#thread');
  th.innerHTML = '';
  th.classList.remove('fade'); void th.offsetWidth; th.classList.add('fade');
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
// keep the newest message in view when the dock grows (attached file chips) or the last answer gains its buttons
const stickRO = new ResizeObserver(() => { if (S.stick) scrollEl.scrollTop = scrollEl.scrollHeight; }); ['#dock', '#thread'].forEach(s => stickRO.observe($(s)));
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
  const info = curInfo(), img = !!opt.image;
  if (!img && (!S.model || !info)){ if (S.modelsLoaded && !S.models.length && !S.catalog.length){ toast('No model yet. Start Ollama or add a key in Settings.'); return; } updateNotice(); openPicker(); return; }
  if (!img && info.locked){ updateNotice(); $('#notice').animate([{transform:'translateX(-6px)'}, {transform:'translateX(6px)'}, {transform:'none'}], {duration:240}); return; }
  let atts = [];
  try{ if (!img) atts = await attachments(); }catch(e){ toast(e.message); return; }
  const conv = await ensureConv();
  if (!opt.regen){
    const um = {id: uid(), role:'user', content: label || prompt, model:'', created: Date.now() / 1000,
      meta: {prompt: label ? prompt : undefined, system, files: files.length ? files.map(f => ({name: f.name, size: f.size})) : undefined, tool: undefined}};
    appendMsg(conv, um); await saveMsg(conv, um);
    if (!conv.title) refreshTitle(conv); // the sidebar shows the real title straight away
  }
  const hist = historyOf(conv);
  const am = {id: uid(), role:'assistant', content:'', thinking:'', model: img ? '' : S.model, meta: {notes: [], image: img || undefined}, live: 1, created: Date.now() / 1000};
  appendMsg(conv, am);
  const ctrl = new AbortController(); S.live.set(conv.id, {ctrl, msg: am});
  if (!img) useModel(S.model); setBusyUI(); renderSide();
  const t0 = performance.now();
  let httpFailed = false;
  try{
    await stream({model: S.model, image: img, think: thinking(), files: atts, messages: hist, system, whole: !!opt.whole, shield_ok: !!S.shieldOk[conv.id],
                  save: {conversation_id: conv.id, message_id: am.id}}, j => {
      if (j.confirm){ am.confirm = j.confirm; return; }
      if (j.docs){ am.meta.pages = j.docs.pages; am.meta.previews = j.docs.previews; }
      if (j.unmask) am.meta.unmask = {...(am.meta.unmask || {}), ...j.unmask};
      if (j.error){ am.content += (am.content ? '\n\n' : '') + j.error; am.meta.error = true; }
      if (j.note) am.meta.notes.push(j.note);
      if (j.thinking) am.thinking += j.thinking;
      if (j.content) am.content += j.content;
      if (j.image) (am.meta.images = am.meta.images || []).push(j.image);
      if (j.model) am.model = j.model;
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
  cancelAnimationFrame(raf); raf = 0; dirty.clear();
  if (am.confirm) return shieldConfirm(conv, am, prompt, label, system, opt);
  repaint(am);
  setBusyUI(); refreshTitle(conv);
  if (am.meta.error) refreshModels(); // so the picker can warn about a model that just failed
}
async function shieldConfirm(conv, am, prompt, label, system, opt){
  const i = conv.messages.indexOf(am); if (i >= 0) conv.messages.splice(i, 1);
  $(`#thread > [data-id="${CSS.escape(am.id)}"]`)?.remove();
  setBusyUI();
  if (confirm(am.confirm)){
    S.shieldOk[conv.id] = true; store.set('shieldOk', S.shieldOk);
    return ask(prompt, label, system, {...opt, regen: true});
  }
  // not sent: take the question back out of the chat and put it in the composer
  const um = [...conv.messages].reverse().find(m => m.role === 'user');
  if (um && !opt.regen){
    await jpost(`/api/conversations/${conv.id}/truncate`, {from_id: um.id});
    conv.messages.splice(conv.messages.indexOf(um));
    $(`#thread > [data-id="${CSS.escape(um.id)}"]`)?.remove();
    if (!conv.messages.length) setEmpty(true);
    if (!label){ $('#input').value = prompt; grow(); paintDock(); }
  }
  toast('Not sent');
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
  ask(mt.prompt || lastUser.content, null, mt.system, {regen: true, image: !!(m.meta || {}).image});
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
  let image = imageMode();
  if (!image && IMAGE_ASK.test(t) && !files.length) image = confirm('This looks like a request for a picture. Make an image?\n\nOK = make an image · Cancel = answer in text');
  ask(t, null, undefined, {image});
}
const IMAGE_ASK = /^\s*(please\s+)?(can you\s+|could you\s+)?(draw|paint|sketch|illustrate|(generate|create|make|design|render)\s+(me\s+)?(an?\s+|the\s+|some\s+)?(\w+\s+){0,3}(image|picture|pic|photo|drawing|illustration|logo|icon|wallpaper|poster|art(work)?))\b/i;
const imageMode = () => $('#imgmode').getAttribute('aria-pressed') === 'true';
$('#imgmode').onclick = () => { const on = !imageMode(); $('#imgmode').setAttribute('aria-pressed', String(on)); $('#input').placeholder = on ? 'Describe the picture to make' : 'Ask something, or drop a file here'; };
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
  else if (mod && e.shiftKey && k === 'f'){ e.preventDefault(); if (narrow()) document.documentElement.classList.add('side-open'); else if (document.documentElement.classList.contains('side-off')){ peek(true, true); setTimeout(() => { $('#cq').focus(); $('#cq').select(); }, 20); return; } $('#cq').focus(); $('#cq').select(); }
  else if (e.key === 'Escape'){
    if ($$('.popmenu').length){ closeMenus(); return; }
    if (document.documentElement.classList.contains('side-peek')){ peek(false, true); return; }
    if (!$('#picker').hidden){ closePicker(); return; }
    if ($('#pal').classList.contains('on') || $('#sheet').classList.contains('on')){ closePal(); closeSheet(); return; }
    if (!$('#param').hidden){ closeParam(); return; }
    if (liveHere()){ stopCurrent(); $('#input').focus(); return; }
    if (S.editing){ $('#editcancel').click(); return; }
    closeDrawer();
  }
});

/* ===================== citations ===================== */
let tip = null;
document.addEventListener('mouseover', e => {
  const c = e.target.closest('.cite');
  if (!c){ if (tip){ tip.remove(); tip = null; } return; }
  const el = c.closest('[data-id]'), m = el && S.conv && S.conv.messages.find(x => x.id === el.dataset.id);
  const p = c.dataset.p, prev = m && m.meta && m.meta.previews && m.meta.previews[p];
  if (!tip){ tip = document.createElement('div'); tip.className = 'citetip'; document.body.appendChild(tip); }
  tip.innerHTML = `<b>Page ${esc(p)}</b>${prev ? esc(prev) : 'This page was not part of what the model read.'}`;
  const r = c.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(innerWidth - 370, r.left)) + 'px';
  tip.style.top = (r.top > 180 ? r.top - tip.offsetHeight - 8 : r.bottom + 8) + 'px';
});
$('#shield').onclick = () => setShield(!S.shield);

/* ===================== profile ===================== */
const HUES = [225, 265, 300, 340, 15, 35, 150, 185];
function initials(p){ const n = (p.name || p.call || '').trim(); if (!n) return ''; const w = n.split(/\s+/); return ((w[0][0] || '') + (w.length > 1 ? w[w.length - 1][0] : '')).toUpperCase(); }
function avatarHtml(p){ return p.image ? `<img src="${esc(p.image)}" alt="">` : (initials(p) ? esc(initials(p)) : ic('user', 16)); }
function paintProfile(){
  const p = S.profile;
  for (const el of [$('#me-av'), $('#r-av'), $('#pf-av')]){ el.innerHTML = avatarHtml(p); el.style.setProperty('--h', p.hue ?? 225); }
  $('#me-nm').textContent = p.name || p.call || 'Set up your profile';
  paintEmpty();
}
async function loadProfile(){ try{ S.profile = await jget('/api/profile'); }catch{ S.profile = {}; } paintProfile(); }
let pfImage = null, pfHue = 225, pfStyle = 'balanced';
function fillProfileForm(){
  const p = S.profile;
  $('#pf-name').value = p.name || ''; $('#pf-call').value = p.call || ''; $('#pf-about').value = p.about || ''; $('#pf-lang').value = p.language || '';
  $('#pf-use').checked = p.use_in_chats !== false; pfImage = p.image || ''; pfHue = p.hue ?? 225; pfStyle = p.style || 'balanced';
  $('#pf-count').textContent = `${$('#pf-about').value.length} / 1500`; $('#pf-msg').textContent = '';
  previewProfile();
}
function previewProfile(){
  const p = {name: $('#pf-name').value, call: $('#pf-call').value, image: pfImage, hue: pfHue};
  $('#pf-av').innerHTML = avatarHtml(p); $('#pf-av').style.setProperty('--h', pfHue);
  $('#pf-rmphoto').hidden = !pfImage;
  $('#pf-colors').innerHTML = HUES.map(h => `<button style="--h:${h}" data-h="${h}" class="${h === pfHue ? 'on' : ''}" title="Colour" aria-label="Avatar colour"></button>`).join('');
  $$('#pf-style button').forEach(b => b.classList.toggle('on', b.dataset.v === pfStyle));
}
$('#pf-name').oninput = $('#pf-call').oninput = previewProfile;
$('#pf-about').oninput = () => { $('#pf-count').textContent = `${$('#pf-about').value.length} / 1500`; };
$('#pf-colors').onclick = e => { const b = e.target.closest('[data-h]'); if (b){ pfHue = +b.dataset.h; previewProfile(); } };
$('#pf-style').onclick = e => { const b = e.target.closest('[data-v]'); if (b){ pfStyle = b.dataset.v; previewProfile(); } };
$('#pf-rmphoto').onclick = () => { pfImage = ''; previewProfile(); };
$('#pf-photo').onclick = () => {
  const inp = Object.assign(document.createElement('input'), {type: 'file', accept: 'image/*'});
  inp.onchange = () => { const f = inp.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => { const img = new Image(); img.onload = () => {
    const c = document.createElement('canvas'), z = 256, k = Math.max(z / img.width, z / img.height); c.width = c.height = z;
    c.getContext('2d').drawImage(img, (z - img.width * k) / 2, (z - img.height * k) / 2, img.width * k, img.height * k);
    pfImage = c.toDataURL('image/jpeg', 0.85); previewProfile(); }; img.src = r.result; }; r.readAsDataURL(f); };
  inp.click();
};
$('#pf-save').onclick = async () => {
  const body = {name: $('#pf-name').value, call: $('#pf-call').value, about: $('#pf-about').value, language: $('#pf-lang').value,
                style: pfStyle, hue: pfHue, image: pfImage, use_in_chats: $('#pf-use').checked};
  const r = await jpost('/api/profile', body);
  if (!r.ok){ $('#pf-msg').textContent = await errorOf(r); return; }
  S.profile = await r.json(); paintProfile(); $('#pf-msg').textContent = 'Saved'; toast('Profile saved');
};

/* ===================== tooltips ===================== */
// Styled tooltips instead of the browser's plain title boxes. The title moves to aria-label so screen readers keep it.
let tipEl = null, tipT = 0, tipShownAt = 0;
function hideTip(){ clearTimeout(tipT); if (tipEl){ tipEl.classList.remove('on'); tipShownAt = performance.now(); } }
document.addEventListener('mouseover', e => {
  const t = e.target.closest('[title],[data-tip]');
  if (!t || t.closest('.picker li') || t.matches('input,textarea,select')) return;
  if (t.hasAttribute('title')){ const v = t.getAttribute('title'); t.dataset.tip = v; if (!t.hasAttribute('aria-label') && !t.textContent.trim()) t.setAttribute('aria-label', v); t.removeAttribute('title'); }
  clearTimeout(tipT);
  const quick = performance.now() - tipShownAt < 600;
  tipT = setTimeout(() => {
    if (!t.isConnected || !t.matches(':hover')) return;
    if (!tipEl){ tipEl = document.createElement('div'); tipEl.className = 'tip'; tipEl.setAttribute('role', 'tooltip'); document.body.appendChild(tipEl); }
    tipEl.textContent = t.dataset.tip;
    const r = t.getBoundingClientRect(), w = tipEl.offsetWidth, hh = tipEl.offsetHeight;
    const below = r.bottom + hh + 10 < innerHeight;
    tipEl.style.left = Math.max(6, Math.min(innerWidth - w - 6, r.left + r.width / 2 - w / 2)) + 'px';
    tipEl.style.top = (below ? r.bottom + 7 : r.top - hh - 7) + 'px';
    tipEl.classList.add('on');
  }, quick ? 60 : 450);
});
document.addEventListener('mouseout', e => { if (e.target.closest('[data-tip]')) hideTip(); });
addEventListener('mousedown', hideTip, true); addEventListener('scroll', hideTip, true); addEventListener('keydown', hideTip, true);

/* ===================== settings ===================== */
const HUE = {ollama:150, lmstudio:265, openai:160, anthropic:22, gemini:215, openrouter:250, groq:5, xai:0, deepseek:225, mistral:30, together:200, fireworks:15, cerebras:280, huggingface:45, custom:200};
const mono = k => { const n = kindInfo(k).name || k, w = n.replace(/[^A-Za-z ]/g, '').split(' ').filter(Boolean);
  const t = k === 'xai' ? 'xAI' : k === 'lmstudio' ? 'LM' : (w.length > 1 ? w[0][0] + w[1][0] : n.slice(0, 2)).toUpperCase();
  return `<span class="mono" style="--h:${HUE[k] ?? 200}">${esc(t.length > 2 ? t.slice(0, 3) : t)}</span>`; };
let SET = {providers: [], storage: 'keyring'};
let openForm = null;
function openSheet(tab = 'models', kind = null, addModelFor = null){
  closePicker(); closePal();
  $('#sheet').classList.add('on'); $('#scrim').classList.add('on');
  showTab(tab); openForm = kind;
  loadSettings().then(() => { if (kind) focusForm(kind); if (addModelFor) openAddModel(addModelFor); });
}
function closeSheet(){ $('#sheet').classList.remove('on'); if (!$('#pal').classList.contains('on')) $('#scrim').classList.remove('on'); }
function showTab(t){
  if (t === 'profile') fillProfileForm();
  $$('.dlg .tab').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  $$('.dlg .tabp').forEach(p => p.hidden = p.dataset.p !== t);
  $('#dlgbody').scrollTop = 0;
}
$$('.dlg .tab').forEach(b => b.onclick = () => showTab(b.dataset.tab));
$('#b-gear').onclick = () => openSheet(); $('#b-close').onclick = closeSheet;
$('#ob-key').onclick = () => openSheet('models');
$('#ob-ollama').onclick = () => openExt('https://ollama.com/download');
$('#ob-retry').onclick = async () => { await refreshModels(true); toast(S.models.length ? `Found ${S.models.length} models` : 'Still no models'); };

function keyLine(p){
  const src = p.source === 'env' ? 'from environment (read-only)' : p.source === 'file' ? 'saved in a plain file' : 'saved in Credential Manager';
  const st = !p.enabled ? 'turned off' : p.status === 'unavailable' ? (p.message || 'problem') : p.model_count ? `${p.model_count} models` : '';
  return `<div class="pkey ${p.enabled ? '' : 'off'}" data-id="${esc(p.id)}"><span class="k">${esc(p.hint || '')}</span>`
    + `<span class="grow">${esc([p.label, src, st].filter(Boolean).join(' · '))}</span>`
    + (p.source === 'env' ? '' : `<button class="btn small ghost" data-tog="${esc(p.id)}">${p.enabled ? 'Turn off' : 'Turn on'}</button><button class="ib" data-del="${esc(p.id)}" title="Remove this key" aria-label="Remove this key">${ic('trash', 16)}</button>`)
    + `</div>`
    + (p.source === 'env' || !p.enabled ? '' : `<div class="xm" data-xm="${esc(p.id)}">`
      + (p.extra_models || []).map(x => `<span class="xchip">${esc(x)}<button data-xdel="${esc(x)}" title="Remove" aria-label="Remove ${esc(x)}">${ic('x', 12)}</button></span>`).join('')
      + `<button class="linkish" data-xadd="${esc(p.id)}">+ Add a model by name</button>`
      + `<span class="xform" hidden><input class="fld" data-xin placeholder="Exact model id, e.g. gpt-6.2-sol" autocomplete="off" spellcheck="false"><button class="btn small" data-xsave="${esc(p.id)}">Add</button></span></div>`);
}
function openAddModel(pid){
  const box = $(`.xm[data-xm="${CSS.escape(pid)}"]`); if (!box) return;
  box.querySelector('[data-xadd]').hidden = true;
  const f = box.querySelector('.xform'); f.hidden = false;
  box.closest('.pcard').scrollIntoView({block:'nearest'});
  f.querySelector('input').focus();
}
async function saveExtra(pid, list){
  const r = await jpost('/api/providers/' + pid, {extra_models: list}, 'PATCH');
  if (!r.ok){ toast(await errorOf(r)); return false; }
  await refreshModels(true); await loadSettings(); return true;
}
function formHtml(k){
  const info = kindInfo(k), custom = k === 'custom';
  return `<div class="pform" data-form="${esc(k)}" hidden>`
    + (custom ? `<div class="row"><input class="fld" data-f="base" placeholder="Server address, e.g. http://localhost:8000" autocomplete="off" spellcheck="false"></div>` : '')
    + `<div class="row"><input class="fld" type="password" data-f="key" placeholder="${custom ? 'API key (leave empty if the server has none)' : `Paste your ${esc(info.name)} API key`}" autocomplete="off" spellcheck="false"></div>`
    + `<div class="row"><input class="fld" data-f="label" placeholder="Label (optional), e.g. Personal or Work" autocomplete="off"><button class="btn primary" data-save="${esc(k)}">Connect</button><button class="btn ghost" data-cancel="${esc(k)}">Cancel</button></div>`
    + `<div class="msg"></div>`
    + (info.url && !custom ? `<div class="small">Don't have one? <a class="linkish" data-ext="${esc(info.url)}">Get ${esc(an(info.name))} key ${ic('ext', 12)}</a></div>` : '')
    + `</div>`;
}
function provCard(k){
  const info = kindInfo(k), keys = SET.providers.filter(p => !p.local && p.kind === k);
  const on = keys.filter(p => p.enabled), bad = on.some(p => p.status === 'unavailable');
  const stat = !keys.length ? '' : bad ? '<span class="stat warn">Check key</span>' : on.length ? '<span class="stat ok">Connected</span>' : '<span class="stat off">Off</span>';
  return `<div class="pcard" data-kind="${esc(k)}"><div class="prow">${mono(k)}<div class="pinfo"><div class="pname">${esc(info.name)}${stat}</div><div class="pdesc">${esc(info.desc || '')}</div></div>`
    + `<div class="pact"><button class="btn small ${keys.length ? 'ghost' : ''}" data-add="${esc(k)}">${keys.length ? 'Add another' : k === 'custom' ? 'Add server' : 'Add key'}</button></div></div>`
    + keys.map(keyLine).join('') + formHtml(k) + `</div>`;
}
function localCard(p){
  const info = kindInfo(p.kind), ok = p.status === 'ok';
  return `<div class="pcard"><div class="prow">${mono(p.kind)}<div class="pinfo"><div class="pname">${esc(p.name)}<span class="stat ${ok ? 'ok' : 'off'}">${ok ? 'Running' : 'Not running'}</span></div>`
    + `<div class="pdesc">${ok ? `${p.model_count} model${p.model_count === 1 ? '' : 's'} on this PC` : esc(info.desc || '')}</div></div>`
    + `<div class="pact">${ok ? '' : `<button class="btn small ghost" data-retry="1">Check again</button><button class="btn small" data-ext="${esc(info.url || '')}">${esc(info.url_label || 'Download')}</button>`}</div></div></div>`;
}
/* ---- Settings -> Images ---- */
async function loadImageServices(){
  const r = await api('/api/image-services'); if (!r.ok) return; const st = await r.json();
  $('#imgpick').value = st.service; $('#img-poll').checked = !!st.pollinations; $('#img-cf-acct').value = st.cf_account || '';
  $('#img-gem').textContent = st.gemini ? 'Key added' : 'No key';
  for (const k of ['hf', 'cf']){ const s = st.services[k]; $('#img-' + k + '-st').textContent = s.saved ? 'Saved ' + s.hint : ''; $('#img-' + k).value = ''; $('#img-' + k).placeholder = s.saved ? 'Saved (' + s.hint + ')' : (k === 'hf' ? 'hf_...' : 'API token'); }
}
async function imageServices(body, msg){
  const r = await jpost('/api/image-services', body);
  if (!r.ok){ toast(await errorOf(r)); return; }
  await loadImageServices(); if (msg) toast(msg);
}
$('#imgpick').onchange = () => imageServices({service: $('#imgpick').value}, 'Saved');
$('#img-poll').onchange = () => imageServices({pollinations: $('#img-poll').checked});
$('#imgsvc').addEventListener('click', e => {
  const s = e.target.closest('[data-imgsave]'), d = e.target.closest('[data-imgdel]');
  if (s){ const k = s.dataset.imgsave, v = $('#img-' + k).value.trim(), body = {};
    if (k === 'cf') body.cf_account = $('#img-cf-acct').value.trim();
    if (v) body[k + '_token'] = v; else if (k !== 'cf'){ toast('Paste the token first'); return; }
    imageServices(body, 'Saved'); }
  if (d) imageServices({[d.dataset.imgdel + '_token']: ''}, 'Removed');
});
async function loadSettings(){
  loadImageServices();
  try{ SET = await jget('/api/providers'); }catch{ return; }
  if (!S.kinds.length) await refreshModels();
  $('#provlocal').innerHTML = SET.providers.filter(p => p.local).map(localCard).join('');
  const kinds = S.kinds.filter(k => !k.local).map(k => k.kind);
  $('#provlist').innerHTML = kinds.map(provCard).join('');
  $('#storagenote').innerHTML = ic('lock') + (SET.storage === 'keyring' ? 'Keys are kept in Windows Credential Manager on this PC and are never shown again in full.'
    : 'Windows Credential Manager isn\'t available, so keys are stored in a plain file on this PC.');
  if (openForm) focusForm(openForm, true);
  $('#shieldtg').checked = S.shield;
  try{
    const [st, cfg] = await Promise.all([jget('/api/status'), jget('/api/settings')]);
    $('#gsstatus').innerHTML = st.ghostscript ? '<span class="stat ok">Installed</span>' : '<span class="stat off">Not installed</span>';
    $('#lostatus').innerHTML = st.libreoffice ? '<span class="stat ok">Installed</span>' : '<span class="stat off">Not installed</span>';
    $('#about').textContent = `Haven ${st.version}. PDF and file tools with an AI assistant, running on your own PC.`;
    $('#datapath').textContent = `In ${cfg.config_path.replace(/settings\.json$/, 'haven.db')} on this PC. Attached files aren't stored, only their names and sizes.`;
  }catch{}
}
function focusForm(k, keep){
  $$('.pform').forEach(f => { if (f.dataset.form !== k) f.hidden = true; });
  const f = $(`.pform[data-form="${CSS.escape(k)}"]`); if (!f) return;
  f.hidden = false;
  if (!keep) f.querySelector('.msg').textContent = '';
  f.closest('.pcard').scrollIntoView({block:'nearest'});
  (f.querySelector('[data-f=base]') || f.querySelector('[data-f=key]')).focus();
}
async function saveKey(k){
  const f = $(`.pform[data-form="${CSS.escape(k)}"]`), msg = f.querySelector('.msg');
  const key = f.querySelector('[data-f=key]').value, label = f.querySelector('[data-f=label]').value.trim();
  const base = f.querySelector('[data-f=base]')?.value || '';
  if (!key.trim() && k !== 'custom'){ f.querySelector('[data-f=key]').focus(); return; }
  msg.className = 'msg'; msg.textContent = 'Checking the key…';
  const btn = f.querySelector('[data-save]'); btn.disabled = true;
  try{
    const r = await jpost('/api/providers', {key: key || 'none', provider: k, label, base_url: base});
    const j = await r.json();
    if (!r.ok){ msg.className = 'msg err'; msg.textContent = j.detail || 'That key did not work.'; return; }
    openForm = null;
    await refreshModels();
    const want = S.model && S.model.startsWith(k + ':') && S.models.find(m => m.full_id === j.provider.id + ':' + S.model.split(':').slice(1).join(':'));
    if (want) setModel(want.full_id);
    else if (!curInfo() || curInfo().locked){ const mine = S.models.filter(m => m.provider === j.provider.id); const best = mine.find(m => m.popular && !m.issue) || mine.find(m => !m.issue) || mine[0]; if (best) setModel(best.full_id); }
    toast(`${j.provider.name} connected: ${j.models.length} models`);
    await loadSettings();
  } finally { btn.disabled = false; }
}
$('#provlist').addEventListener('click', async e => {
  const x = e.target.closest('[data-xadd],[data-xsave],[data-xdel]');
  if (x){
    const pid = x.dataset.xadd || x.dataset.xsave || x.closest('[data-xm]').dataset.xm, p = SET.providers.find(q => q.id === pid);
    if (x.dataset.xadd) return openAddModel(pid);
    if (x.dataset.xdel) return saveExtra(pid, (p.extra_models || []).filter(m => m !== x.dataset.xdel));
    const v = x.closest('.xform').querySelector('input').value.trim(); if (!v) return;
    if (await saveExtra(pid, [...new Set([...(p.extra_models || []), v])])){ setModel(pid + ':' + v); toast(`${v} added`); }
    return;
  }
  const t = e.target.closest('[data-add],[data-save],[data-cancel],[data-tog],[data-del]'); if (!t) return;
  if (t.dataset.add){ openForm = t.dataset.add; focusForm(t.dataset.add); }
  else if (t.dataset.save) saveKey(t.dataset.save);
  else if (t.dataset.cancel){ openForm = null; t.closest('.pform').hidden = true; }
  else if (t.dataset.tog){ const p = SET.providers.find(x => x.id === t.dataset.tog); await jpost('/api/providers/' + p.id, {enabled: !p.enabled}, 'PATCH'); await refreshModels(); loadSettings(); }
  else if (t.dataset.del){ if (!confirm('Remove this key from Haven?')) return; await api('/api/providers/' + t.dataset.del, {method:'DELETE'}); await refreshModels(); loadSettings(); toast('Key removed'); }
});
$('#provlist').addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.target.matches('.pform input')){ e.preventDefault(); saveKey(e.target.closest('.pform').dataset.form); }
  if (e.key === 'Enter' && e.target.matches('[data-xin]')){ e.preventDefault(); e.target.closest('.xform').querySelector('[data-xsave]').click(); }
});
$('#provlocal').addEventListener('click', async e => { if (e.target.closest('[data-retry]')){ await refreshModels(true); loadSettings(); } });
$('#shieldtg').onchange = () => setShield($('#shieldtg').checked);
$('#addkey').onclick = addAnyKey;
$('#nkey').onkeydown = e => { if (e.key === 'Enter') addAnyKey(); };
async function addAnyKey(){
  const key = $('#nkey').value; if (!key.trim()){ $('#nkey').focus(); return; }
  $('#keymsg').textContent = 'Checking the key…'; $('#addkey').disabled = true;
  try{
    const r = await jpost('/api/providers', {key});
    const j = await r.json();
    if (!r.ok){ $('#keymsg').textContent = (j.detail || 'That key did not work.') + (j.unrecognised ? ' Use "Add key" next to the right provider above.' : ''); return; }
    $('#nkey').value = ''; $('#keymsg').textContent = `${j.provider.name}: ${j.models.length} chat models added.`;
    await refreshModels();
    if ((!curInfo() || curInfo().locked) && j.models[0]) setModel(j.models[0].full_id);
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
  try{ S.shield = (await jget('/api/settings')).shield !== false; }catch{}
  await loadProfile();
  await Promise.all([refreshModels(), loadConvs()]);
  const last = store.get('conv', '');
  if (last && S.convs.some(c => c.id === last)) await openConv(last); else renderThread();
  setInterval(refreshModels, 20000);
  document.documentElement.dataset.ready = '1';
  document.documentElement.dataset.readyAt = String(Math.round(performance.now())); // ms since navigation start
})();
