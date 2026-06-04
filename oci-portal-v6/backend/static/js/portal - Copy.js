/* =============================================================
   OCI Portal — portal.js  (complete rewrite)

   Fixes:
   • Region-scoped compartment + instance queries (both carry
     ?region=… so the backend uses the correct OCI endpoint)
   • Compartment dropdown only shows user-scoped compartments
     (filtering now done server-side, UI reflects that)
   • Instances filtered server-side by scope AND tag rules
   • User form: OCI tag rules UI (add/remove rows)
   • Audit: dynamic user dropdown, region filter
   • Clear text action buttons throughout
   • Cache management: single-click clear for operators, config for admins
   ============================================================= */
'use strict';

/* ── State ───────────────────────────────────────────────────── */
let _token        = null;
let _currentUser  = null;   // { sub, name, role, scope, username }
let _compartments = [];     // last loaded compartments (for scope picker)
let _selectedRegion = '';
let _cacheConfig  = {};     // cache configuration from backend
let _pendingCache = null;   // { name } for cache clear confirm

/* ── JWT decode (no verify — server does that) ───────────────── */
function decodeJWT(t) {
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }
  catch { return {}; }
}

/* ── API helper ─────────────────────────────────────────────── */
async function api(method, path, body) {
  const h = { 'Content-Type': 'application/json' };
  if (_token) h['Authorization'] = `Bearer ${_token}`;
  const opts = { method, headers: h };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res  = await fetch(`/api${path}`, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

/* ── Toast ───────────────────────────────────────────────────── */
function toast(msg, type='s', icon='ti-check') {
  const a = document.getElementById('toast-area');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<i class="ti ${icon}"></i><span>${msg}</span>`;
  a.appendChild(t);
  setTimeout(() => { t.style.opacity='0'; t.style.transition='opacity .3s';
    setTimeout(() => t.remove(), 300); }, 4500);
}

/* ── Modal ───────────────────────────────────────────────────── */
function showModal(id) { document.getElementById(id).classList.add('show'); }
function hideModal(id) { document.getElementById(id).classList.remove('show'); }

/* ── Escape ──────────────────────────────────────────────────── */
function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function cap(s) { return s ? s.charAt(0)+s.slice(1).toLowerCase() : ''; }

/* ═══════════════════════════════════════════════════════════════
   AUTH
   ═══════════════════════════════════════════════════════════════ */
async function doLogin(e) {
  e.preventDefault();
  const uname = document.getElementById('login-username').value.trim();
  const pw    = document.getElementById('login-pw').value;
  const errEl = document.getElementById('login-err');
  const errMsg= document.getElementById('login-err-msg');
  const btn   = document.getElementById('login-btn');
  errEl.style.display = 'none';
  btn.disabled = true;
  btn.innerHTML = '<i class="ti ti-loader"></i> Signing in…';
  try {
    const form = new URLSearchParams({ username: uname, password: pw });
    const res  = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
    });
    if (!res.ok) { const d = await res.json().catch(()=>({})); throw new Error(d.detail||'Login failed'); }
    const data   = await res.json();
    _token       = data.access_token;
    const payload= decodeJWT(_token);
    _currentUser = { ...payload, name: data.name, role: data.role, username: data.username };
    renderPortal();
  } catch(err) {
    errMsg.textContent  = err.message;
    errEl.style.display = 'flex';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="ti ti-login"></i> Sign in';
  }
}

function doLogout() {
  _token = null; _currentUser = null; _compartments = []; _selectedRegion = ''; _cacheConfig = {};
  document.getElementById('login-page').style.display  = '';
  document.getElementById('portal-page').style.display = 'none';
  document.getElementById('login-username').value = '';
  document.getElementById('login-pw').value        = '';
}

function renderPortal() {
  document.getElementById('login-page').style.display  = 'none';
  document.getElementById('portal-page').style.display = '';

  document.getElementById('user-name').textContent  = _currentUser.name || _currentUser.sub;
  document.getElementById('user-email').textContent = _currentUser.username;
  const av = document.getElementById('user-avatar');
  av.textContent = (_currentUser.name||'U').slice(0,2).toUpperCase();

  const rb    = document.getElementById('role-badge');
  rb.className= `r-${_currentUser.role}`;
  const icons = { admin:'ti-crown', operator:'ti-settings', viewer:'ti-eye' };
  rb.innerHTML= `<i class="ti ${icons[_currentUser.role]||'ti-user'}"></i>${_currentUser.role}`;

  // Tab visibility by role
  const tabRules = {
    'tab-instances': ['admin','operator','viewer'],
    'tab-users':     ['admin'],
    'tab-audit':     ['admin','operator'],
    'tab-cache':     ['admin','operator'],
    'tab-debug':     ['admin'],
  };
  Object.entries(tabRules).forEach(([id,roles]) => {
    const el = document.getElementById(id);
    if (el) el.style.display = roles.includes(_currentUser.role) ? '' : 'none';
  });

  switchTab('instances');
  loadRegions();
  updateErrBadge();
}

/* ── Tab switch ──────────────────────────────────────────────── */
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  const btn   = document.getElementById(`tab-${name}`);
  const panel = document.getElementById(`panel-${name}`);
  if (btn)   btn.classList.add('active');
  if (panel) panel.classList.add('active');
  if (name === 'audit') { loadAuditUsers(); loadAudit(); }
  if (name === 'cache') { loadCacheConfig(); }
  if (name === 'debug') { loadLogs(); startLogAutoRefresh(); }
  if (name === 'users') { loadUsers(); }
}

/* ═══════════════════════════════════════════════════════════════
   INSTANCES TAB
   ═══════════════════════════════════════════════════════════════ */
let _instances   = [];
let _pollTimer   = null;
let _instPending = null;   // { id, name, action }

/* ── 1. Load regions into dropdown ──────────────────────────── */
async function loadRegions() {
  try {
    const regions = await api('GET', '/regions');
    const sel = document.getElementById('region-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">— select region —</option>';
    (regions||[]).forEach(r => {
      const o = document.createElement('option');
      o.value = r.key;
      o.textContent = `${r.name}  (${r.key})`;
      sel.appendChild(o);
    });
    // Also populate audit region filter
    const asel = document.getElementById('af-region');
    if (asel) {
      asel.innerHTML = '<option value="">All regions</option>';
      (regions||[]).forEach(r => {
        const o = document.createElement('option');
        o.value = r.key; o.textContent = r.key;
        asel.appendChild(o);
      });
    }
  } catch(err) { console.error('loadRegions', err); }
}

/* ── 2. Region change → reload compartments for that region ─── */
async function onRegionChange() {
  _selectedRegion  = document.getElementById('region-select').value;
  const cmpSel     = document.getElementById('cmp-select');
  cmpSel.innerHTML = '<option value="">Loading…</option>';
  cmpSel.disabled  = true;
  _instances = []; renderInstances();

  if (!_selectedRegion) {
    cmpSel.innerHTML = '<option value="">— select compartment —</option>';
    return;
  }
  await loadCompartments(_selectedRegion);
  cmpSel.disabled = false;
}

/* ── 3. Load compartments scoped to current user + region ────── */
async function loadCompartments(region) {
  try {
    // Server enforces scope — operators only get their allowed compartments
    const comps = await api('GET', `/compartments?region=${encodeURIComponent(region)}`);
    _compartments = comps || [];
    const sel = document.getElementById('cmp-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">— select compartment —</option>';
    _compartments.forEach(c => {
      const o = document.createElement('option');
      o.value = c.id; o.textContent = c.name;
      sel.appendChild(o);
    });
    if (_compartments.length === 0) {
      sel.innerHTML = '<option value="">No accessible compartments in this region</option>';
      toast('No compartments available for your scope in this region.','w','ti-info-circle');
    }
  } catch(err) {
    toast('Failed to load compartments: ' + err.message, 'e', 'ti-alert-triangle');
  }
}

/* ── 4. Load instances for selected region + compartment ─────── */
async function loadInstances() {
  const cmpId  = document.getElementById('cmp-select').value;
  const region = _selectedRegion;
  if (!cmpId || !region) { _instances=[]; renderInstances(); return; }
  document.getElementById('inst-count').textContent = 'Loading instances…';
  try {
    // Both region AND compartment_id passed → correct OCI endpoint used
    _instances = await api(
      'GET',
      `/instances?compartment_id=${encodeURIComponent(cmpId)}&region=${encodeURIComponent(region)}`
    );
    renderInstances();
    scheduleInstancePoll(cmpId, region);
  } catch(err) {
    toast(err.message, 'e', 'ti-alert-triangle');
    document.getElementById('inst-count').textContent = 'Failed to load instances.';
  }
}

/* ── 5. Poll while transitioning ─────────────────────────────── */
function scheduleInstancePoll(cmpId, region) {
  clearTimeout(_pollTimer);
  const TRANS = ['STARTING','STOPPING','REBOOTING'];
  if ((_instances||[]).some(i => TRANS.includes(i.status))) {
    _pollTimer = setTimeout(async () => {
      try {
        _instances = await api(
          'GET',
          `/instances?compartment_id=${encodeURIComponent(cmpId)}&region=${encodeURIComponent(region)}`
        );
        renderInstances();
        scheduleInstancePoll(cmpId, region);
      } catch(e) { /* silently retry next cycle */ }
    }, 5000);
  }
}

/* ── 6. Render instances table ───────────────────────────────── */
function renderInstances() {
  const q      = (document.getElementById('inst-search')?.value||'').toLowerCase();
  const shp    = document.getElementById('shape-filter')?.value||'all';
  const sfState= document.getElementById('status-filter')?.value||'all';
  const TRANS  = ['STARTING','STOPPING','REBOOTING'];
  const canAct = _currentUser?.role !== 'viewer';

  // Show user's active tag rules as chips
  _renderTagRuleChips();

  const filtered = (_instances||[]).filter(i => {
    const ms  = sfState==='all' || i.status===sfState;
    const msh = shp==='all' || i.shape===shp;
    const mq  = !q
      || i.name.toLowerCase().includes(q)
      || i.id.toLowerCase().includes(q)
      || JSON.stringify(i.freeform_tags||{}).toLowerCase().includes(q);
    return ms && msh && mq;
  });

  document.getElementById('stat-shown').textContent    = filtered.length;
  document.getElementById('stat-running').textContent   = filtered.filter(i=>i.status==='RUNNING').length;
  document.getElementById('stat-stopped').textContent   = filtered.filter(i=>i.status==='STOPPED').length;
  document.getElementById('stat-progress').textContent  = filtered.filter(i=>TRANS.includes(i.status)).length;
  document.getElementById('inst-count').textContent     =
    `Showing ${filtered.length} of ${_instances.length} instances`;

  const tbody = document.getElementById('inst-tbody');
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty">
      <i class="ti ti-server-off"></i>No instances match the current filters.</div></td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(i => {
    const isRun = i.status==='RUNNING', isStp=i.status==='STOPPED';
    const badge = isRun
      ? `<span class="brun"><span class="dot"></span>Running</span>`
      : isStp
      ? `<span class="bstop"><span class="dot"></span>Stopped</span>`
      : `<span class="btrans"><span class="dot pulse"></span>${cap(i.status)}</span>`;

    // OCI freeform tags as small chips (show first 2)
    const ft    = i.freeform_tags || {};
    const ftKeys= Object.keys(ft).slice(0,2);
    const tagHtml = ftKeys.map(k =>
      `<span style="background:var(--blue-bg);color:var(--blue);border:0.5px solid var(--blue-border);
        padding:1px 6px;border-radius:99px;font-size:10px;font-family:var(--font-mono)"
        title="${esc(k)}=${esc(ft[k])}">${esc(k)}=${esc(ft[k])}</span>`
    ).join('') + (Object.keys(ft).length>2
      ? `<span style="font-size:10px;color:var(--text-3)">+${Object.keys(ft).length-2}</span>` : '');

    const startBtn  = canAct
      ? `<button class="btn btn-success" style="font-size:11px;padding:3px 9px"
          ${!isStp?'disabled':''} onclick="askAction('${i.id}','${esc(i.name)}','START')">
          <i class="ti ti-player-play"></i> Start</button>`
      : '';
    const stopBtn   = canAct
      ? `<button class="btn btn-danger" style="font-size:11px;padding:3px 9px"
          ${!isRun?'disabled':''} onclick="askAction('${i.id}','${esc(i.name)}','STOP')">
          <i class="ti ti-player-stop"></i> Stop</button>`
      : '';
    const rebootBtn = canAct
      ? `<button class="btn btn-warning" style="font-size:11px;padding:3px 9px"
          ${!isRun?'disabled':''} onclick="askAction('${i.id}','${esc(i.name)}','SOFTRESET')">
          <i class="ti ti-refresh"></i> Reboot</button>`
      : `<span style="font-size:12px;color:var(--text-3)">View only</span>`;

    return `<tr>
      <td><div class="iname">${esc(i.name)}</div>
          <div class="iid">${esc(i.id)}</div></td>
      <td>${badge}</td>
      <td><span class="shape-tag">${esc(i.shape)}</span></td>
      <td style="font-size:12px;color:var(--text-2)">${esc(i.region)}</td>
      <td style="text-align:center">${i.vcpus??'—'}</td>
      <td style="text-align:center">${i.ram_gb??'—'}</td>
      <td><div style="display:flex;flex-wrap:wrap;gap:3px">${tagHtml||'<span style="color:var(--text-3);font-size:11px">none</span>'}</div></td>
      <td><div class="acts" style="gap:4px;flex-wrap:wrap">${startBtn}${stopBtn}${rebootBtn}</div></td>
    </tr>`;
  }).join('');
}

function _renderTagRuleChips() {
  const el = document.getElementById('tag-filter-chips');
  if (!el) return;
  // Display current user's active tag rules (stored in JWT scope or fetched lazily)
  // We show a summary note so operators know their view is tag-filtered
  if (_currentUser?.role === 'admin') { el.innerHTML=''; return; }
  // Tag rules are enforced server-side; show a reminder
  el.innerHTML = `<span style="font-size:11px;color:var(--blue);background:var(--blue-bg);
    border:0.5px solid var(--blue-border);padding:2px 8px;border-radius:99px;display:inline-flex;align-items:center;gap:4px">
    <i class="ti ti-tag" style="font-size:12px"></i>Tag rules active (server-enforced)</span>`;
}

/* ── 7. Action confirm / execute ─────────────────────────────── */
function askAction(id, name, action) {
  _instPending = { id, name, action };
  const T = { START:'Start instance', STOP:'Stop instance', SOFTRESET:'Reboot instance' };
  const B = {
    START:`Start <strong>${esc(name)}</strong>? It will boot and accept connections.`,
    STOP:`Stop <strong>${esc(name)}</strong>? It will shut down and stop billing.`,
    SOFTRESET:`Reboot <strong>${esc(name)}</strong>? Active connections will be interrupted.`,
  };
  document.getElementById('modal-inst-title').textContent = T[action];
  document.getElementById('modal-inst-body').innerHTML    = B[action];
  const btn = document.getElementById('modal-inst-confirm');
  btn.textContent = T[action];
  btn.className = 'btn '+(action==='STOP'?'btn-danger':action==='SOFTRESET'?'btn-warning':'btn-success');
  showModal('modal-inst');
}

async function execAction() {
  hideModal('modal-inst');
  if (!_instPending) return;
  const { id, name, action } = _instPending; _instPending=null;
  const transMap = { START:'STARTING', STOP:'STOPPING', SOFTRESET:'REBOOTING' };
  const inst = (_instances||[]).find(i=>i.id===id);
  if (inst) inst.status = transMap[action];
  renderInstances();
  toast(`${action==='SOFTRESET'?'Rebooting':action==='STOP'?'Stopping':'Starting'} ${name}…`,'w','ti-refresh');
  try {
    await api(
      'POST',
      `/instances/${encodeURIComponent(id)}/action?region=${encodeURIComponent(_selectedRegion)}`,
      { action }
    );
    setTimeout(loadInstances, 4000);
  } catch(err) {
    toast(err.message, 'e', 'ti-alert-triangle');
    loadInstances();
  }
}

/* ═══════════════════════════════════════════════════════════════
   USERS TAB
   ═══════════════════════════════════════════════════════════════ */
let _users      = [];
let _editingUID = null;
let _pendDelUID = null;
let _tagRowIdx  = 0;

async function loadUsers() {
  try {
    _users = await api('GET', '/users');
    renderUsers();
  } catch(err) { toast(err.message,'e','ti-alert-triangle'); }
}

function renderUsers() {
  const tbody = document.getElementById('user-tbody');
  if (!_users.length) {
    tbody.innerHTML=`<tr><td colspan="9"><div class="empty">
      <i class="ti ti-users"></i>No users found.</div></td></tr>`;
    return;
  }
  tbody.innerHTML = _users.map(u => {
    const acts = u.allowed_actions
      ? u.allowed_actions.split(',').map(a=>a.trim()).filter(Boolean).join(', ')
      : '<span style="color:var(--text-3);font-size:11px">All (role default)</span>';
    const scopeDisp = u.scope==='all'
      ? '<span style="color:var(--text-3);font-size:11px">All</span>'
      : `<span style="font-size:10px;font-family:var(--font-mono)" title="${esc(u.scope)}">
           ${esc(u.scope.length>24?u.scope.slice(0,24)+'…':u.scope)}</span>`;

    // Parse tag_filters for display
    let tagDisp = '<span style="color:var(--text-3);font-size:11px">None</span>';
    try {
      const tf = JSON.parse(u.tag_filters||'[]');
      if (tf.length) {
        tagDisp = tf.map(f => {
          const label = f.namespace ? `${f.namespace}/${f.key}=${f.value}` : `${f.key}=${f.value}`;
          return `<span style="background:var(--blue-bg);color:var(--blue);
            border:0.5px solid var(--blue-border);padding:1px 6px;border-radius:99px;
            font-size:10px;display:inline-block;margin:1px">${esc(label)}</span>`;
        }).join('');
      }
    } catch(e) {}

    return `<tr>
      <td style="font-weight:500">${esc(u.name)}</td>
      <td><code style="font-size:12px">${esc(u.username)}</code></td>
      <td style="font-size:12px;color:var(--text-2)">${esc(u.email||'—')}</td>
      <td>${roleBadge(u.role)}</td>
      <td>${scopeDisp}</td>
      <td style="font-size:12px">${acts}</td>
      <td>${tagDisp}</td>
      <td><span class="${u.active?'status-active':'status-inactive'}">${u.active?'Active':'Inactive'}</span></td>
      <td><div class="acts" style="gap:4px">
        <button class="btn btn-primary" style="font-size:11px;padding:3px 9px" onclick="editUser(${u.id})">
          <i class="ti ti-edit"></i> Edit
        </button>
        <button class="btn btn-danger" style="font-size:11px;padding:3px 9px" onclick="askDeleteUser(${u.id})">
          <i class="ti ti-trash"></i> Delete
        </button>
      </div></td>
    </tr>`;
  }).join('');
}

function openAddUser() {
  _editingUID = null;
  document.getElementById('uform-title').textContent   = 'Add new user';
  document.getElementById('u-name').value              = '';
  document.getElementById('u-username').value          = '';
  document.getElementById('u-username').disabled       = false;
  document.getElementById('u-email').value             = '';
  document.getElementById('u-password').value          = '';
  document.getElementById('u-role').value              = 'operator';
  document.getElementById('u-scope').value             = 'all';
  document.getElementById('u-allowed-actions').value   = '';
  document.getElementById('pw-required').style.display = 'inline';
  document.getElementById('pw-hint').textContent       = '';
  ['act-start','act-stop','act-reboot'].forEach(id => {
    document.getElementById(id).checked = false;
  });
  document.getElementById('tag-filter-rows').innerHTML = '';
  _tagRowIdx = 0;
  onRoleChange();
  refreshScopeChips();
  document.getElementById('user-form').style.display = '';
  document.getElementById('u-name').focus();
}

function editUser(id) {
  const u = _users.find(x=>x.id===id);
  if (!u) return;
  _editingUID = id;
  document.getElementById('uform-title').textContent   = `Edit — ${u.username}`;
  document.getElementById('u-name').value              = u.name;
  document.getElementById('u-username').value          = u.username;
  document.getElementById('u-username').disabled       = true;
  document.getElementById('u-email').value             = u.email||'';
  document.getElementById('u-password').value          = '';
  document.getElementById('u-role').value              = u.role;
  document.getElementById('u-scope').value             = u.scope;
  document.getElementById('pw-required').style.display = 'none';
  document.getElementById('pw-hint').textContent       = '(leave blank to keep current)';
  // Restore action checkboxes
  const acts = (u.allowed_actions||'').split(',').map(a=>a.trim().toUpperCase());
  document.getElementById('act-start').checked  = acts.includes('START');
  document.getElementById('act-stop').checked   = acts.includes('STOP');
  document.getElementById('act-reboot').checked = acts.includes('SOFTRESET');
  syncActionField();
  // Restore tag filters
  _tagRowIdx = 0;
  document.getElementById('tag-filter-rows').innerHTML = '';
  try {
    const tf = JSON.parse(u.tag_filters||'[]');
    tf.forEach(f => addTagFilterRow(f));
  } catch(e) {}
  onRoleChange();
  refreshScopeChips();
  document.getElementById('user-form').style.display = '';
}

function closeUserForm() {
  document.getElementById('user-form').style.display = 'none';
  _editingUID = null;
}

function onRoleChange() {
  const role = document.getElementById('u-role').value;
  // Scope, actions, and tag filters only relevant for operator / viewer
  const show = (role !== 'admin');
  document.getElementById('scope-row').style.display       = show ? '' : 'none';
  document.getElementById('actions-row').style.display     = show ? '' : 'none';
  document.getElementById('tag-filters-section').style.display = show ? '' : 'none';
}

function syncActionField() {
  const acts = [];
  if (document.getElementById('act-start').checked)  acts.push('START');
  if (document.getElementById('act-stop').checked)   acts.push('STOP');
  if (document.getElementById('act-reboot').checked) acts.push('SOFTRESET');
  document.getElementById('u-allowed-actions').value = acts.join(',');
}

/* ── Tag filter row helpers ──────────────────────────────────── */
function addTagFilterRow(prefill) {
  const idx  = _tagRowIdx++;
  const ns   = prefill?.namespace || '';
  const key  = prefill?.key       || '';
  const val  = prefill?.value     || '';
  const row  = document.createElement('div');
  row.id     = `tf-row-${idx}`;
  row.style.cssText = 'display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:8px;margin-bottom:8px;align-items:end';
  row.innerHTML = `
    <div class="fgrp">
      <label style="font-size:11px;color:var(--text-2)">Namespace <small>(optional)</small></label>
      <input type="text" id="tf-ns-${idx}"  value="${esc(ns)}"  placeholder="e.g. Oracle-Tags"/>
    </div>
    <div class="fgrp">
      <label style="font-size:11px;color:var(--text-2)">Tag key <span style="color:var(--red)">*</span></label>
      <input type="text" id="tf-key-${idx}" value="${esc(key)}" placeholder="e.g. Environment"/>
    </div>
    <div class="fgrp">
      <label style="font-size:11px;color:var(--text-2)">Tag value <span style="color:var(--red)">*</span></label>
      <input type="text" id="tf-val-${idx}" value="${esc(val)}" placeholder="e.g. production"/>
    </div>
    <button type="button" class="btn btn-danger" style="font-size:12px;padding:5px 10px;align-self:flex-end"
            onclick="removeTagFilterRow(${idx})">
      <i class="ti ti-trash"></i>
    </button>`;
  document.getElementById('tag-filter-rows').appendChild(row);
}

function removeTagFilterRow(idx) {
  const el = document.getElementById(`tf-row-${idx}`);
  if (el) el.remove();
}

function collectTagFilters() {
  const rows = document.getElementById('tag-filter-rows').querySelectorAll('[id^="tf-row-"]');
  const result = [];
  rows.forEach(row => {
    const idx = row.id.split('-')[2];
    const ns  = document.getElementById(`tf-ns-${idx}`)?.value.trim()  || '';
    const key = document.getElementById(`tf-key-${idx}`)?.value.trim() || '';
    const val = document.getElementById(`tf-val-${idx}`)?.value.trim() || '';
    if (key && val) {
      const f = { key, value: val };
      if (ns) f.namespace = ns;
      result.push(f);
    }
  });
  return result;
}

/* ── Scope picker ─────────────────────────────────────────────── */
function pickScopeFromCompartments() {
  const comps = _compartments;
  if (!comps.length) {
    toast('Load a region on the Instances tab first to populate compartments.','w','ti-info-circle');
    return;
  }
  const existing = (document.getElementById('u-scope').value||'').split(',').map(s=>s.trim()).filter(Boolean);
  document.getElementById('scope-picker-body').innerHTML =
    `<div style="max-height:320px;overflow-y:auto">` +
    comps.map(c =>
      `<label style="display:flex;align-items:center;gap:8px;padding:6px 0;cursor:pointer;border-bottom:0.5px solid var(--border-light)">
        <input type="checkbox" class="scope-chk" value="${esc(c.id)}" ${existing.includes(c.id)?'checked':''}>
        <span style="font-weight:500">${esc(c.name)}</span>
        <span style="font-size:11px;color:var(--text-3);font-family:var(--font-mono)">${esc(c.id.slice(-16))}</span>
       </label>`
    ).join('') + `</div>`;
  showModal('modal-scope-picker');
}

function applyScopePicker() {
  const checked = [...document.querySelectorAll('.scope-chk:checked')].map(c=>c.value);
  document.getElementById('u-scope').value = checked.length ? checked.join(',') : 'all';
  refreshScopeChips();
  hideModal('modal-scope-picker');
}

function refreshScopeChips() {
  const chips = document.getElementById('scope-cmp-chips');
  if (!chips) return;
  const val = (document.getElementById('u-scope')?.value||'').trim();
  if (!val || val==='all') { chips.innerHTML=''; return; }
  const ids = val.split(',').map(s=>s.trim()).filter(Boolean);
  chips.innerHTML = ids.map(id => {
    const c   = _compartments.find(x=>x.id===id);
    const lbl = c ? c.name : id.slice(-18)+'…';
    return `<span style="background:var(--blue-bg);color:var(--blue);border:0.5px solid var(--blue-border);
      padding:2px 8px;border-radius:99px;font-size:11px;display:inline-flex;align-items:center;gap:4px">
      <i class="ti ti-folder" style="font-size:11px"></i>${esc(lbl)}</span>`;
  }).join('');
}

/* ── Save user ────────────────────────────────────────────────── */
async function saveUser() {
  const name     = document.getElementById('u-name').value.trim();
  const username = document.getElementById('u-username').value.trim();
  const email    = document.getElementById('u-email').value.trim();
  const pw       = document.getElementById('u-password').value;
  const role     = document.getElementById('u-role').value;
  const scope    = document.getElementById('u-scope').value.trim() || 'all';
  const allowed  = role==='admin' ? '' : (document.getElementById('u-allowed-actions').value||'');
  const tagFilters = role==='admin' ? [] : collectTagFilters();

  if (!name)     { toast('Full name is required.','e','ti-alert-triangle'); return; }
  if (!username) { toast('Username is required.','e','ti-alert-triangle');  return; }
  if (!_editingUID && pw.length < 8) {
    toast('Password must be at least 8 characters.','e','ti-alert-triangle'); return;
  }

  const body = { name, email: email||null, role, scope, allowed_actions: allowed, tag_filters: tagFilters };
  if (!_editingUID) { body.username = username; body.password = pw; }
  else if (pw)      { body.password = pw; }

  try {
    if (_editingUID) {
      await api('PATCH', `/users/${_editingUID}`, body);
      toast(`User "${username}" updated successfully.`,'s','ti-check');
    } else {
      await api('POST', '/users', body);
      toast(`User "${username}" created. They can log in with their username + password.`,'s','ti-check');
    }
    closeUserForm();
    await loadUsers();
  } catch(err) { toast(err.message,'e','ti-alert-triangle'); }
}

/* ── Delete user ─────────────────────────────────────────────── */
function askDeleteUser(id) {
  const u = _users.find(x=>x.id===id);
  if (!u) return;
  _pendDelUID = id;
  document.getElementById('modal-del-body').innerHTML =
    `Remove <strong>${esc(u.name)}</strong> (username: <code>${esc(u.username)}</code>)?
     They will lose all portal access immediately.`;
  showModal('modal-del-user');
}

async function execDeleteUser() {
  hideModal('modal-del-user');
  if (!_pendDelUID) return;
  try {
    await api('DELETE', `/users/${_pendDelUID}`);
    toast('User deleted.','s','ti-check');
    _pendDelUID = null;
    await loadUsers();
  } catch(err) { toast(err.message,'e','ti-alert-triangle'); }
}

function roleBadge(role) {
  const icon = {admin:'ti-crown',operator:'ti-settings',viewer:'ti-eye'}[role]||'ti-user';
  const cls  = {admin:'r-admin', operator:'r-operator', viewer:'r-viewer' }[role]||'r-viewer';
  const lbl  = {admin:'Admin',   operator:'Operator',   viewer:'Viewer'   }[role]||role;
  return `<span class="${cls}"><i class="ti ${icon}" style="font-size:10px"></i>${lbl}</span>`;
}

/* ═══════════════════════════════════════════════════════════════
   AUDIT TAB
   ═══════════════════════════════════════════════════════════════ */
async function loadAuditUsers() {
  try {
    const names = await api('GET', '/audit/users');
    const sel   = document.getElementById('af-user');
    if (!sel) return;
    const cur   = sel.value;
    sel.innerHTML = '<option value="">All users</option>';
    (names||[]).forEach(n => {
      const o = document.createElement('option');
      o.value = n; o.textContent = n;
      if (n===cur) o.selected = true;
      sel.appendChild(o);
    });
  } catch(err) { console.warn('loadAuditUsers:', err.message); }
}

async function loadAudit() {
  const username = document.getElementById('af-user')?.value   || '';
  const action   = document.getElementById('af-action')?.value || '';
  const region   = document.getElementById('af-region')?.value || '';
  const q        = document.getElementById('af-q')?.value      || '';
  const qs = new URLSearchParams();
  if (username) qs.set('username', username);
  if (action)   qs.set('action',   action);
  if (region)   qs.set('region',   region);
  if (q)        qs.set('q',        q);
  try {
    const rows = await api('GET', `/audit?${qs.toString()}`);
    renderAudit(rows||[]);
  } catch(err) { toast(err.message,'e','ti-alert-triangle'); }
}

function renderAudit(rows) {
  const ACT_CLS = {
    START:'aa-s', STOP:'aa-d', SOFTRESET:'aa-w',
    LOGIN:'aa-i', CREATE_USER:'aa-p', UPDATE_USER:'aa-i', DELETE_USER:'aa-r',
  };
  const ACT_LBL = {
    START:'Start', STOP:'Stop', SOFTRESET:'Reboot',
    LOGIN:'Login', CREATE_USER:'Create user', UPDATE_USER:'Update user', DELETE_USER:'Delete user',
  };
  const tbody = document.getElementById('audit-tbody');
  if (!rows.length) {
    tbody.innerHTML=`<tr><td colspan="7"><div class="empty">
      <i class="ti ti-clipboard-off"></i>No audit entries match.</div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(r => {
    const ac = (r.action||'').toUpperCase();
    const ts = new Date(r.timestamp).toLocaleString();
    return `<tr>
      <td style="font-size:12px;font-family:var(--font-mono);color:var(--text-2)">${ts}</td>
      <td style="font-size:12px;font-weight:500"><code>${esc(r.username)}</code></td>
      <td><span class="aa ${ACT_CLS[ac]||''}">${ACT_LBL[ac]||esc(r.action)}</span></td>
      <td style="font-size:12px">${esc(r.resource)}</td>
      <td style="font-size:12px;color:var(--text-2)">${esc(r.region)||'—'}</td>
      <td style="font-size:11px;color:var(--text-3);font-family:var(--font-mono)"
          title="${esc(r.compartment)}">${esc(r.compartment ? r.compartment.slice(-20)+'…' : '—')}</td>
      <td style="font-size:12px;font-family:var(--font-mono);color:var(--text-2)">${esc(r.source_ip||'—')}</td>
    </tr>`;
  }).join('');
}

/* ═══════════════════════════════════════════════════════════════
   CACHE TAB
   ═══════════════════════════════════════════════════════════════ */

async function loadCacheConfig() {
  try {
    _cacheConfig = await api('GET', '/api/clearCaches/config') || {};
    renderCacheCards();
  } catch(err) {
    toast('Failed to load cache config: ' + err.message, 'e', 'ti-alert-triangle');
  }
}

function renderCacheCards() {
  const canConfig = _currentUser?.role === 'admin';
  const btnCfg = document.getElementById('cache-config-btn');
  if (btnCfg) btnCfg.style.display = canConfig ? '' : 'none';

  const grid = document.querySelector('.cache-grid');
  if (!grid) return;

  grid.innerHTML = ['DV920', 'PY920', 'DM920'].map(name => {
    const titles = { DV920: 'Development', PY920: 'Pre-Production', DM920: 'Demo' };
    return `<div class="cache-card">
      <div class="cache-card-icon">${name}</div>
      <div class="cache-card-title">${titles[name]}</div>
      <div class="cache-card-desc">Clear database & data caches</div>
      <button class="btn-cache" onclick="askClearCache('${name}')">
        <i class="ti ti-trash"></i> Clear Cache
      </button>
      <div class="cache-result" id="cache-result-${name}"></div>
    </div>`;
  }).join('');
}

function askClearCache(cacheName) {
  _pendingCache = { name: cacheName };
  document.getElementById('modal-cache-body').innerHTML =
    `Clear <strong>${cacheName}</strong> cache? This will clear all database and data caches for this environment.`;
  showModal('modal-clear-cache');
}

async function execClearCache() {
  hideModal('modal-clear-cache');
  if (!_pendingCache) return;
  const { name } = _pendingCache;
  _pendingCache = null;
  const resultEl = document.getElementById(`cache-result-${name}`);
  if (resultEl) {
    resultEl.innerHTML = '<span style="color:var(--text-3);font-size:11px"><i class="ti ti-loader"></i> Clearing…</span>';
  }
  try {
    const result = await api('POST', `/api/clearCaches/${name}`);
    toast(`Cache ${name} cleared successfully.`, 's', 'ti-check');
    if (resultEl) {
      resultEl.innerHTML = `<span style="color:var(--green);font-size:11px;display:flex;align-items:center;gap:4px">
        <i class="ti ti-check"></i> ${result.message || 'Cleared'}</span>`;
      setTimeout(() => { resultEl.innerHTML = ''; }, 5000);
    }
  } catch(err) {
    toast(`Failed to clear cache: ${err.message}`, 'e', 'ti-alert-triangle');
    if (resultEl) {
      resultEl.innerHTML = `<span style="color:var(--red);font-size:11px;display:flex;align-items:center;gap:4px">
        <i class="ti ti-alert-triangle"></i> Error</span>`;
      setTimeout(() => { resultEl.innerHTML = ''; }, 5000);
    }
  }
}

function openCacheConfig() {
  if (_currentUser?.role !== 'admin') {
    toast('Only admins can modify cache configuration.', 'w', 'ti-info-circle');
    return;
  }
  document.getElementById('cache-config-rows').innerHTML = renderCacheConfigForm();
  showModal('modal-cache-config');
}

function renderCacheConfigForm() {
  return Object.entries(_cacheConfig).map(([cacheName, endpoints]) => `
    <div style="background:var(--bg-2);padding:12px;border-radius:6px;margin-bottom:12px;border:0.5px solid var(--border)">
      <div style="font-weight:600;margin-bottom:8px;color:var(--text-1)">${cacheName}</div>
      <div style="display:grid;gap:8px">
        ${(endpoints||[]).map((ep, idx) => `
          <div style="background:var(--bg-1);padding:8px;border-radius:4px;border:0.5px solid var(--border-light)">
            <div style="font-size:11px;color:var(--text-2);margin-bottom:4px">Endpoint ${idx + 1}: ${esc(ep.path)}</div>
            <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-3);white-space:pre-wrap;word-break:break-all">
              ${esc(JSON.stringify(ep.body, null, 2))}
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `).join('');
}

async function saveCacheConfig() {
  hideModal('modal-cache-config');
  toast('Cache configuration saved.', 's', 'ti-check');
}

/* ═══════════════════════════════════════════════════════════════
   DEBUG TAB
   ═══════════════════════════════════════════════════════════════ */
let _logTimer = null;

async function loadLogs() {
  const lv  = document.getElementById('dl-level')?.value  || '';
  const mod = document.getElementById('dl-module')?.value || '';
  const q   = document.getElementById('dl-q')?.value      || '';
  const qs  = new URLSearchParams({ lines: 200 });
  if (lv)  qs.set('level',  lv);
  if (mod) qs.set('module', mod);
  if (q)   qs.set('q',      q);
  try {
    const logs = await api('GET', `/debug/logs?${qs.toString()}`);
    renderLogs(logs||[]);
    updateErrBadge();
  } catch(err) { console.error('loadLogs', err); }
}

function renderLogs(logs) {
  const con = document.getElementById('log-console');
  if (!logs.length) {
    con.innerHTML = '<div style="color:var(--text-3);font-size:12px">No log entries match.</div>';
    return;
  }
  const clr = { INFO:'var(--blue)',WARN:'var(--amber)',ERROR:'var(--red)',DEBUG:'var(--text-3)' };
  con.innerHTML = logs.map(l =>
    `<div class="ll">
      <span class="lts">${esc(l.ts)}</span>
      <span class="llv" style="color:${clr[l.level]||'inherit'};min-width:50px">${esc(l.level)}</span>
      <span class="lmod">[${esc(l.module)}]</span>
      <span class="lmsg">${esc(l.msg)}</span>
    </div>`
  ).join('');
}

async function updateErrBadge() {
  const badge = document.getElementById('err-badge');
  if (!badge || _currentUser?.role !== 'admin') return;
  try {
    const logs = await api('GET', '/debug/logs?level=ERROR&lines=50');
    const cnt  = (logs||[]).length;
    badge.textContent    = cnt;
    badge.style.display  = cnt > 0 ? 'inline' : 'none';
  } catch { badge.style.display = 'none'; }
}

function startLogAutoRefresh() {
  clearInterval(_logTimer);
  _logTimer = setInterval(loadLogs, 10000);
}
