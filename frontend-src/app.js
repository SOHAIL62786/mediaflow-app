  // ---- Session guard: if any API call comes back 401 (session expired,
  // logged out elsewhere, etc.), bounce to the login page instead of
  // letting every page silently fail to load its data. ----
  (function(){
    const _origFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const res = await _origFetch(...args);
      const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
      if(res.status === 401 && !url.includes('/api/auth/')){
        window.location.href = '/login';
      }
      return res;
    };
  })();

  // File selection / drag & drop
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('fileInput');
  const chooseBtn = document.getElementById('chooseBtn');
  const fileRow = document.getElementById('fileRow');
  const fname = document.getElementById('fname');
  const fmeta = document.getElementById('fmeta');
  const removeFile = document.getElementById('removeFile');
  const titleInput = document.getElementById('titleInput');

  chooseBtn.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('click', (e) => { if(e.target === chooseBtn) return; fileInput.click(); });

  ['dragenter','dragover'].forEach(evt=>{
    dropzone.addEventListener(evt, e=>{ e.preventDefault(); dropzone.classList.add('dragover'); });
  });
  ['dragleave','drop'].forEach(evt=>{
    dropzone.addEventListener(evt, e=>{ e.preventDefault(); dropzone.classList.remove('dragover'); });
  });
  dropzone.addEventListener('drop', e=>{
    const file = e.dataTransfer.files[0];
    if(file) handleFile(file);
  });
  fileInput.addEventListener('change', e=>{
    const file = e.target.files[0];
    if(file) handleFile(file);
  });

  function handleFile(file){
    const sizeMB = (file.size / (1024*1024)).toFixed(1);
    fname.textContent = file.name;
    fmeta.textContent = `${sizeMB} MB`;
    fileRow.classList.add('show');
    const niceName = file.name.replace(/\.[^/.]+$/,'').replace(/[-_]/g,' ');
    titleInput.value = niceName;
  }

  removeFile.addEventListener('click', ()=>{
    fileRow.classList.remove('show');
    fileInput.value = '';
  });

  // Platform selection — only lets you select platforms that are actually connected
  document.querySelectorAll('.platform-card').forEach(card=>{
    card.addEventListener('click', ()=>{
      if(card.dataset.connected !== 'true'){
        showToast(`${card.querySelector('.platform-name').textContent} isn't connected yet.`);
        return;
      }
      card.classList.toggle('selected');
    });
  });

  // ---- Real connection status from the backend ----
  const API = ''; // same origin, since the backend also serves this page

  // ---- Multi-account switcher ----
  // One shared login, but every request is scoped to whichever account is
  // currently selected (platform connections, posts, and analytics are all
  // independent per account). The chosen account persists across reloads.
  let currentAccountId = parseInt(localStorage.getItem('mf_account_id') || '1', 10);
  let accountsCache = [];

  function withAccount(url){
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}account_id=${currentAccountId}`;
  }

  function currentAccountName(){
    const acc = accountsCache.find(a => a.id === currentAccountId);
    return acc ? acc.name : '...';
  }

  function renderAccountPill(){
    const name = currentAccountName();
    document.getElementById('accountPillName').textContent = name;
    document.getElementById('accountPillAvatar').textContent = (name[0] || '?').toUpperCase();
  }

  async function loadAccounts(){
    try{
      const res = await fetch(`${API}/api/accounts`);
      accountsCache = await res.json();
      if(!accountsCache.find(a => a.id === currentAccountId)){
        currentAccountId = accountsCache[0] ? accountsCache[0].id : 1;
        localStorage.setItem('mf_account_id', String(currentAccountId));
      }
      renderAccountPill();
      renderAccountDropdownList();
    }catch(err){
      // leave whatever was cached/defaulted
    }
  }

  function renderAccountDropdownList(){
    const list = document.getElementById('accountDropdownList');
    list.innerHTML = accountsCache.map(a => `
      <div class="account-dd-item${a.id === currentAccountId ? ' active' : ''}" data-account-id="${a.id}">
        <div class="avatar" style="width:24px;height:24px;font-size:11px;">${(a.name[0]||'?').toUpperCase()}</div>
        <span>${a.name}</span>
      </div>
    `).join('');
  }

  function switchAccount(id){
    currentAccountId = id;
    localStorage.setItem('mf_account_id', String(id));
    document.getElementById('accountDropdown').classList.remove('open');
    renderAccountPill();
    renderAccountDropdownList();
    // Re-run whatever the current page needs so it reflects the new account
    loadStatus();
    const activePage = document.querySelector('.page.active')?.dataset.page || 'dashboard';
    if(activePage === 'dashboard') loadDashboard();
    if(activePage === 'accounts') renderAcctMgmtPage();
    if(activePage === 'platforms') loadPlatformsPage();
    if(activePage === 'scheduled') loadLibrary('scheduled');
    if(activePage === 'published') loadLibrary('published');
    if(activePage === 'analytics') loadAnalytics();
    showToast(`Switched to ${currentAccountName()}`);
  }

  document.getElementById('accountPill').addEventListener('click', (e)=>{
    e.stopPropagation();
    document.getElementById('accountDropdown').classList.toggle('open');
  });
  document.addEventListener('click', ()=>{
    document.getElementById('accountDropdown').classList.remove('open');
  });
  document.getElementById('accountDropdown').addEventListener('click', (e)=> e.stopPropagation());
  document.getElementById('accountDropdownList').addEventListener('click', (e)=>{
    const item = e.target.closest('[data-account-id]');
    if(item) switchAccount(parseInt(item.dataset.accountId, 10));
  });
  async function promptCreateAccount(){
    const name = prompt('Name for the new account (e.g. a client or brand name):');
    if(!name || !name.trim()) return;
    const fd = new FormData();
    fd.append('name', name.trim());
    try{
      const res = await fetch(`${API}/api/accounts`, { method: 'POST', body: fd });
      if(!res.ok) throw new Error();
      const acc = await res.json();
      await loadAccounts();
      switchAccount(acc.id);
      showToast(`Created account "${acc.name}" — connect its platforms from Platforms.`, 5000);
    }catch(err){
      showToast('Could not create the account — is the server running?');
    }
  }
  document.getElementById('addAccountBtn').addEventListener('click', promptCreateAccount);

  // loadStatus() and the initial page load both need currentAccountId to
  // already be validated/corrected (see loadAccounts() above) before they
  // fire — otherwise, on any page load where localStorage's mf_account_id
  // points at an account this user no longer owns (e.g. it was reassigned
  // or deleted), they'll fire one request each with the stale id and 404,
  // before loadAccounts()'s correction even lands. Chaining both off the
  // same loadAccounts() promise (instead of each calling it separately,
  // or not waiting on it at all) fixes the race without changing when
  // anything else on the page sets up.
  const accountsReady = loadAccounts();

  async function loadStatus(){
    try{
      const res = await fetch(withAccount(`${API}/api/status`));
      const data = await res.json();
      Object.entries(data).forEach(([platform, info])=>{
        const card = document.querySelector(`.platform-card[data-platform="${platform}"]`);
        const accRow = document.getElementById(`acc-${platform}`);
        if(card){
          const statusEl = card.querySelector('[data-status]');
          card.dataset.connected = info.connected ? 'true' : 'false';
          if(info.connected){
            statusEl.textContent = '✓ ' + (info.channel || 'Connected');
            statusEl.style.color = 'var(--green)';
            card.classList.add('selected');
          } else {
            statusEl.textContent = 'Not connected';
            statusEl.style.color = 'var(--text-light)';
            card.classList.remove('selected');
          }
        }
        if(accRow){
          const handleEl = accRow.querySelector('[data-handle]');
          const pillEl = accRow.querySelector('[data-pill]');
          if(info.connected){
            handleEl.textContent = info.channel || 'Connected';
            pillEl.textContent = 'Connected';
            pillEl.style.background = '';
            pillEl.style.color = '';
          } else {
            handleEl.textContent = 'Not connected';
            pillEl.textContent = 'Not set up';
            pillEl.style.background = '#f1f2f6';
            pillEl.style.color = 'var(--text-mid)';
          }
        }
      });
    }catch(err){
      showToast('Could not reach the local server — is it running?');
    }
  }
  accountsReady.then(loadStatus);
  document.querySelectorAll('.toggle').forEach(t=>{
    const isDarkToggle = t.id === 'darkToggle';
    // Dark theme's actual on/off is the class an inline script in <head>
    // already applied (before first paint, reading localStorage) — this
    // toggle just needs to reflect and then change that. Every other
    // toggle keeps its old purely-visual behavior.
    let on = isDarkToggle
      ? document.documentElement.classList.contains('dark-theme')
      : t.id === 'customizeToggle';
    t.style.position='relative';
    const setDot = ()=>{
      t.style.setProperty('transition','background .15s');
      t.style.background = on ? 'var(--indigo)' : (t.id==='darkToggle' ? '#33335c':'#c9cbe0');
      t.querySelectorAll('span.dot').forEach(d=>d.remove());
      const dot = document.createElement('span');
      dot.className='dot';
      dot.style.cssText = `content:'';position:absolute;width:16px;height:16px;background:#fff;border-radius:50%;top:2px;left:${on?'18px':'2px'};transition:left .15s;`;
      t.appendChild(dot);
    };
    setDot();
    t.addEventListener('click', ()=>{
      on = !on;
      setDot();
      if(isDarkToggle){
        document.documentElement.classList.toggle('dark-theme', on);
        try{ localStorage.setItem('mf-dark-theme', on ? '1' : '0'); }catch(e){}
      }
    });
  });

  // Char count
  const captionInput = document.getElementById('captionInput');
  const charCount = document.getElementById('charCount');
  captionInput.addEventListener('input', ()=>{
    charCount.textContent = captionInput.value.length;
  });

  // Publish — real upload to the backend
  const publishBtn = document.getElementById('publishBtn');
  const toast = document.getElementById('toast');

  function showToast(msg, ms=3500){
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(()=>toast.classList.remove('show'), ms);
  }

  publishBtn.addEventListener('click', async ()=>{
    const file = fileInput.files[0];
    if(!file){
      showToast('Choose a video file first.');
      return;
    }
    const selectedCards = [...document.querySelectorAll('.platform-card.selected')];
    if(selectedCards.length === 0){
      showToast('Select at least one connected platform.');
      return;
    }
    const platforms = selectedCards.map(c => c.dataset.platform);

    const isLater = document.querySelector('input[name=schedule]:checked').value === 'later';
    let scheduledIso = null;
    if(isLater){
      const raw = document.getElementById('scheduleDatetimeInput').value; // "YYYY-MM-DDTHH:MM" in local time
      if(!raw){
        showToast('Pick a date and time to schedule for later.');
        return;
      }
      const picked = new Date(raw);
      if(isNaN(picked.getTime()) || picked.getTime() <= Date.now()){
        showToast('Scheduled time must be in the future.');
        return;
      }
      scheduledIso = picked.toISOString(); // converts local time -> UTC ISO (e.g. 2026-09-10T14:30:00.000Z)
    }

    const formData = new FormData();
    formData.append('video', file);
    formData.append('title', titleInput.value || file.name);
    formData.append('caption', captionInput.value || '');
    formData.append('platforms', platforms.join(','));
    formData.append('tags', document.getElementById('tagsInput').value || '');
    formData.append('privacy', document.getElementById('privacySelect').value);
    formData.append('made_for_kids', document.getElementById('madeForKidsInput').checked);
    formData.append('contains_synthetic_media', document.getElementById('syntheticMediaInput').checked);
    if(scheduledIso){ formData.append('scheduled_time', scheduledIso); }

    publishBtn.disabled = true;
    publishBtn.textContent = isLater ? 'Scheduling...' : 'Uploading...';

    try{
      const res = await fetch(withAccount(`${API}/api/publish`), { method: 'POST', body: formData });
      if(!res.ok){
        const err = await res.json().catch(()=>({detail: res.statusText}));
        throw new Error(err.detail || 'Upload failed');
      }
      const body = await res.json();

      if(isLater){
        const lines = Object.entries(body).map(([platform, r])=>{
          if(r.ok){
            const when = new Date(r.scheduled_for).toLocaleString();
            return `${platform}: queued — will publish at ${when}`;
          }
          return `${platform}: failed — ${r.error}`;
        });
        showToast(lines.join('  |  '), 6000);
        loadDashboard();
      } else {
        // Immediate publish now runs as a background job — open the
        // progress panel and poll it instead of waiting on one big
        // request/response.
        renderPublishSteps(platforms.map(p => ({ key: p, label: `Publishing to ${p[0].toUpperCase()}${p.slice(1)}`, status: 'pending' })));
        openPublishPanel();
        pollPublishJob(body.job_id);
      }
    }catch(err){
      showToast('Upload failed: ' + err.message, 5000);
    }finally{
      publishBtn.disabled = false;
      publishBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>Publish Now';
    }
  });

  // ---- Drafts & Templates ----
  // Both are just a saved snapshot of this form's metadata fields — no
  // video file, no schedule time (see docs/DECISIONS.md 013). Drafts are
  // unnamed and one-shot (resuming deletes them); templates are named and
  // reused indefinitely (applying doesn't delete them).
  let currentPresetKind = 'draft';
  let presetsCache = [];

  async function savePreset(kind){
    const selectedCards = [...document.querySelectorAll('.platform-card.selected')];
    const platforms = selectedCards.map(c => c.dataset.platform);
    let name = '';
    if(kind === 'template'){
      name = prompt('Name this template (e.g. "Weekly Vlog"):', '');
      if(name === null) return; // cancelled
      if(!name.trim()){ showToast('Give the template a name.'); return; }
    }
    const title = titleInput.value || '';
    const caption = captionInput.value || '';
    if(!title.trim() && !caption.trim()){
      showToast('Add a title or caption before saving.');
      return;
    }
    const fd = new FormData();
    fd.append('kind', kind);
    if(name) fd.append('name', name.trim());
    fd.append('title', title);
    fd.append('caption', caption);
    fd.append('platforms', platforms.join(','));
    fd.append('tags', document.getElementById('tagsInput').value || '');
    fd.append('privacy', document.getElementById('privacySelect').value);
    fd.append('made_for_kids', document.getElementById('madeForKidsInput').checked);
    fd.append('contains_synthetic_media', document.getElementById('syntheticMediaInput').checked);
    try{
      const res = await fetch(withAccount(`${API}/api/upload-presets`), { method: 'POST', body: fd });
      if(!res.ok){
        const err = await res.json().catch(()=>({detail:'Save failed.'}));
        throw new Error(err.detail);
      }
      showToast(kind === 'draft' ? 'Draft saved.' : 'Template saved.');
      if(currentPresetKind === kind) loadPresets(kind);
    }catch(err){
      showToast('Could not save: ' + err.message, 5000);
    }
  }
  document.getElementById('saveDraftBtn').addEventListener('click', () => savePreset('draft'));
  document.getElementById('saveTemplateBtn').addEventListener('click', () => savePreset('template'));

  async function loadPresets(kind){
    currentPresetKind = kind;
    document.getElementById('presetTabDrafts').classList.toggle('active', kind === 'draft');
    document.getElementById('presetTabTemplates').classList.toggle('active', kind === 'template');
    document.getElementById('presetTabHistory').classList.toggle('active', kind === 'history');
    const container = document.getElementById('presetList');
    container.innerHTML = '<div class="empty-state">Loading…</div>';
    try{
      const res = await fetch(withAccount(`${API}/api/upload-presets?kind=${kind}`));
      if(!res.ok) throw new Error();
      presetsCache = await res.json();
      renderPresetList();
    }catch(err){
      container.innerHTML = '<div class="empty-state">Could not load.</div>';
    }
  }

  function renderPresetList(){
    const container = document.getElementById('presetList');
    if(!presetsCache.length){
      const emptyMsg = currentPresetKind === 'draft' ? 'No drafts saved yet.'
        : currentPresetKind === 'template' ? 'No templates saved yet.'
        : 'No publish history yet — it fills in as you publish videos.';
      container.innerHTML = `<div class="empty-state">${emptyMsg}</div>`;
      return;
    }
    if(currentPresetKind === 'history'){
      container.innerHTML = presetsCache.map(p => {
        const label = p.title || p.caption || 'Untitled';
        const sub = new Date(p.created_at).toLocaleString();
        return `
          <div class="preset-row" data-preset-id="${p.id}" data-preset-open-history style="cursor:pointer;">
            <div style="min-width:0;flex:1;">
              <div class="n">${escapeHtml(label)}</div>
              <div class="d">${escapeHtml(sub)}</div>
            </div>
          </div>`;
      }).join('');
      return;
    }
    container.innerHTML = presetsCache.map(p => {
      const label = currentPresetKind === 'template' ? (p.name || 'Untitled') : (p.title || p.caption || 'Untitled draft');
      const sub = currentPresetKind === 'template'
        ? (p.title || 'No title set')
        : new Date(p.created_at).toLocaleString();
      const actionLabel = currentPresetKind === 'template' ? 'Apply' : 'Resume';
      return `
        <div class="preset-row" data-preset-id="${p.id}">
          <div style="min-width:0;flex:1;">
            <div class="n">${escapeHtml(label)}</div>
            <div class="d">${escapeHtml(sub)}</div>
          </div>
          <div class="preset-row-actions">
            <button class="acc-btn" data-preset-action="apply">${actionLabel}</button>
            <button class="acc-btn danger" data-preset-action="delete">Delete</button>
          </div>
        </div>`;
    }).join('');
  }

  document.getElementById('presetTabDrafts').addEventListener('click', () => loadPresets('draft'));
  document.getElementById('presetTabTemplates').addEventListener('click', () => loadPresets('template'));
  document.getElementById('presetTabHistory').addEventListener('click', () => loadPresets('history'));

  function applyPresetToForm(preset){
    titleInput.value = preset.title || '';
    captionInput.value = preset.caption || '';
    charCount.textContent = captionInput.value.length;
    document.getElementById('tagsInput').value = preset.tags || '';
    document.getElementById('privacySelect').value = preset.privacy || 'private';
    document.getElementById('madeForKidsInput').checked = !!preset.made_for_kids;
    document.getElementById('syntheticMediaInput').checked = !!preset.contains_synthetic_media;
    const platforms = (preset.platforms || '').split(',').map(p=>p.trim()).filter(Boolean);
    document.querySelectorAll('.platform-card').forEach(card=>{
      const shouldSelect = platforms.includes(card.dataset.platform) && card.dataset.connected === 'true';
      card.classList.toggle('selected', shouldSelect);
    });
  }

  document.getElementById('presetList').addEventListener('click', async (e) => {
    const historyRow = e.target.closest('[data-preset-open-history]');
    if(historyRow){
      const id = parseInt(historyRow.dataset.presetId, 10);
      const preset = presetsCache.find(p => p.id === id);
      if(preset) openHistoryModal(preset);
      return;
    }

    const row = e.target.closest('[data-preset-id]');
    if(!row) return;
    const id = parseInt(row.dataset.presetId, 10);
    const preset = presetsCache.find(p => p.id === id);
    if(!preset) return;
    const action = e.target.closest('[data-preset-action]');
    if(!action) return;

    if(action.dataset.presetAction === 'apply'){
      applyPresetToForm(preset);
      if(currentPresetKind === 'draft'){
        // Drafts are one-shot — resuming one consumes it.
        try{ await fetch(withAccount(`${API}/api/upload-presets/${id}`), { method: 'DELETE' }); }catch(err){}
        loadPresets('draft');
      }
      showToast(currentPresetKind === 'draft' ? 'Draft loaded into the form.' : 'Template applied.');
    } else if(action.dataset.presetAction === 'delete'){
      const ok = confirm(`Delete this ${currentPresetKind}? This can't be undone.`);
      if(!ok) return;
      try{
        const res = await fetch(withAccount(`${API}/api/upload-presets/${id}`), { method: 'DELETE' });
        if(!res.ok) throw new Error();
        loadPresets(currentPresetKind);
      }catch(err){
        showToast('Could not delete.', 4000);
      }
    }
  });

  // ---- History detail popup ----
  // Unlike drafts/templates (inline Apply/Delete in the list row), history
  // rows open a popup showing the full submitted form before deciding
  // whether to reuse or discard it — there's more to review (every field,
  // not just a title), so a quick inline button isn't enough context.
  function historyPlatformBadges(platformsStr){
    const list = (platformsStr || '').split(',').map(p => p.trim()).filter(Boolean);
    if(!list.length) return '<span style="color:var(--text-mid)">None selected</span>';
    return list.map(p => `<span class="pub-pill" style="background:var(--hover-bg);color:var(--text-dark);text-transform:capitalize;">${escapeHtml(p)}</span>`).join(' ');
  }

  function openHistoryModal(preset){
    const body = document.getElementById('historyModalBody');
    const flags = [];
    if(preset.made_for_kids) flags.push('Made for kids');
    if(preset.contains_synthetic_media) flags.push('Contains AI-generated/altered media');
    body.innerHTML = `
      <h2 style="margin-bottom:4px;">${escapeHtml(preset.title || 'Untitled')}</h2>
      <div style="font-size:12px;color:var(--text-mid);margin-bottom:18px;">Submitted ${escapeHtml(new Date(preset.created_at).toLocaleString())}</div>

      <div class="field"><label>Caption</label>
        <div style="white-space:pre-wrap;font-size:14px;color:var(--text-dark);">${escapeHtml(preset.caption || '—')}</div>
      </div>
      <div class="field"><label>Tags</label>
        <div style="font-size:14px;color:var(--text-dark);">${escapeHtml(preset.tags || '—')}</div>
      </div>
      <div class="field"><label>Platforms</label>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">${historyPlatformBadges(preset.platforms)}</div>
      </div>
      <div class="field"><label>Privacy (YouTube)</label>
        <div style="font-size:14px;color:var(--text-dark);text-transform:capitalize;">${escapeHtml(preset.privacy || 'private')}</div>
      </div>
      ${flags.length ? `<div class="modal-note">${flags.map(escapeHtml).join(' · ')}</div>` : ''}

      <div class="preset-row-actions" style="margin-top:20px;">
        <button class="acc-btn" id="historyUseBtn">Use</button>
        <button class="acc-btn danger" id="historyDeleteBtn">Delete</button>
      </div>
    `;
    document.getElementById('historyUseBtn').addEventListener('click', () => {
      applyPresetToForm(preset);
      closeHistoryModal();
      showToast('Loaded into the form.');
    });
    document.getElementById('historyDeleteBtn').addEventListener('click', async () => {
      const ok = confirm('Delete this history entry? This can\'t be undone.');
      if(!ok) return;
      try{
        const res = await fetch(withAccount(`${API}/api/upload-presets/${preset.id}`), { method: 'DELETE' });
        if(!res.ok) throw new Error();
        closeHistoryModal();
        loadPresets('history');
      }catch(err){
        showToast('Could not delete.', 4000);
      }
    });
    document.getElementById('historyModalOverlay').classList.add('show');
  }
  function closeHistoryModal(){
    document.getElementById('historyModalOverlay').classList.remove('show');
  }
  document.getElementById('historyModalClose').addEventListener('click', closeHistoryModal);
  document.getElementById('historyModalOverlay').addEventListener('click', (e) => {
    if(e.target.id === 'historyModalOverlay') closeHistoryModal();
  });

  // Radio label + datetime picker toggle
  const scheduleDatetimeWrap = document.getElementById('scheduleDatetime');
  const scheduleDatetimeInput = document.getElementById('scheduleDatetimeInput');

  // Prevent picking a time in the past.
  function updateMinScheduleTime(){
    const now = new Date(Date.now() - Date.now() % 60000); // round down to the minute
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    scheduleDatetimeInput.min = local.toISOString().slice(0,16);
  }
  updateMinScheduleTime();

  document.querySelectorAll('input[name=schedule]').forEach(r=>{
    r.addEventListener('change', ()=>{
      const isLater = document.querySelector('input[name=schedule]:checked').value === 'later';
      const textNode = publishBtn.childNodes[publishBtn.childNodes.length-1];
      if(isLater){
        textNode.textContent = 'Schedule';
        updateMinScheduleTime();
        scheduleDatetimeWrap.classList.add('show');
      } else {
        textNode.textContent = 'Publish Now';
        scheduleDatetimeWrap.classList.remove('show');
      }
    });
  });

  // ================= Page routing =================
  const PAGE_TITLES = {
    dashboard: 'Dashboard', accounts: 'Accounts', platforms: 'Platforms', upload: 'New Upload',
    scheduled: 'Scheduled', published: 'Published',
    analytics: 'Analytics', settings: 'Settings', help: 'Help & Support',
  };

  function escapeHtml(s){
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function showPage(name){
    if(!PAGE_TITLES[name]) name = 'dashboard';
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const target = document.querySelector(`.page[data-page="${name}"]`);
    if(target) target.classList.add('active');
    document.querySelectorAll('#navList li').forEach(li => li.classList.toggle('active', li.dataset.page === name));
    document.getElementById('pageTitle').textContent = PAGE_TITLES[name];
    document.title = 'MediaFlow - ' + PAGE_TITLES[name];
    history.replaceState(null, '', '/' + name);
    if(name === 'dashboard') loadDashboard();
    if(name === 'accounts') renderAcctMgmtPage();
    if(name === 'platforms') loadPlatformsPage();
    if(name === 'scheduled') loadLibrary('scheduled');
    if(name === 'published') loadLibrary('published');
    if(name === 'analytics') loadAnalytics();
    if(name === 'settings') loadSettingsPage();
    if(name === 'upload') loadPresets(currentPresetKind);
  }

  document.querySelectorAll('#navList li[data-page]').forEach(li=>{
    li.addEventListener('click', () => { showPage(li.dataset.page); closeMobileSidebar(); });
  });
  document.querySelectorAll('[data-goto]').forEach(el=>{
    el.addEventListener('click', () => { showPage(el.dataset.goto); closeMobileSidebar(); });
  });

  // "Needs Attention" doesn't have its own page — it's the failed subset of
  // the Published library. Land on Published but load the failed rows into
  // its list container instead of the normal published-only fetch.
  function goToNeedsAttention(){
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const target = document.querySelector('.page[data-page="published"]');
    if(target) target.classList.add('active');
    document.querySelectorAll('#navList li').forEach(li => li.classList.toggle('active', li.dataset.page === 'published'));
    document.getElementById('pageTitle').textContent = 'Needs Attention';
    document.title = 'MediaFlow - Needs Attention';
    history.replaceState(null, '', '/published');
    loadLibrary('failed');
    closeMobileSidebar();
  }
  document.getElementById('statFailedCard').addEventListener('click', goToNeedsAttention);

  // ---- Mobile sidebar (hamburger menu, slide-in overlay on small screens) ----
  function openMobileSidebar(){
    document.querySelector('.sidebar').classList.add('open');
    document.body.classList.add('sidebar-open');
  }
  function closeMobileSidebar(){
    document.querySelector('.sidebar').classList.remove('open');
    document.body.classList.remove('sidebar-open');
  }
  document.getElementById('menuToggle').addEventListener('click', openMobileSidebar);
  document.getElementById('sidebarBackdrop').addEventListener('click', closeMobileSidebar);

  // ---- Desktop sidebar: collapsible + drag-to-resize ----
  const sidebarEl = document.querySelector('.sidebar');
  const sidebarHandle = document.getElementById('sidebarResizeHandle');
  const sidebarReopenTab = document.getElementById('sidebarReopenTab');
  const SIDEBAR_WIDTH_KEY = 'mf_sidebar_width';
  const SIDEBAR_COLLAPSED_KEY = 'mf_sidebar_collapsed';
  const SIDEBAR_MIN = 180, SIDEBAR_MAX = 420;

  function setSidebarWidth(px){
    px = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, px));
    sidebarEl.style.width = px + 'px';
    localStorage.setItem(SIDEBAR_WIDTH_KEY, String(px));
  }
  function collapseSidebar(){
    sidebarEl.classList.add('collapsed');
    sidebarReopenTab.style.display = 'flex';
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, '1');
  }
  function expandSidebar(){
    sidebarEl.classList.remove('collapsed');
    sidebarReopenTab.style.display = 'none';
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, '0');
  }
  // Restore saved width/collapsed state
  const savedWidth = parseInt(localStorage.getItem(SIDEBAR_WIDTH_KEY), 10);
  if(savedWidth) setSidebarWidth(savedWidth);
  if(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1') collapseSidebar();

  document.getElementById('sidebarCollapseBtn').addEventListener('click', collapseSidebar);
  sidebarReopenTab.addEventListener('click', expandSidebar);

  let sidebarDragging = false, sidebarDragStartX = 0, sidebarDragStartW = 0;
  sidebarHandle.addEventListener('pointerdown', (e) => {
    if(sidebarEl.classList.contains('collapsed')) return;
    sidebarDragging = true;
    sidebarDragStartX = e.clientX;
    sidebarDragStartW = sidebarEl.getBoundingClientRect().width;
    sidebarHandle.setPointerCapture(e.pointerId);
    document.body.classList.add('sidebar-resizing');
  });
  sidebarHandle.addEventListener('pointermove', (e) => {
    if(!sidebarDragging) return;
    setSidebarWidth(sidebarDragStartW + (e.clientX - sidebarDragStartX));
  });
  function endSidebarDrag(){
    sidebarDragging = false;
    document.body.classList.remove('sidebar-resizing');
  }
  sidebarHandle.addEventListener('pointerup', endSidebarDrag);
  sidebarHandle.addEventListener('pointercancel', endSidebarDrag);
  sidebarHandle.addEventListener('dblclick', () => setSidebarWidth(230));

  // ---- Notifications drawer ----
  const notifDrawer = document.getElementById('notifDrawer');
  const notifBackdrop = document.getElementById('notifBackdrop');
  const notifBell = document.getElementById('notifBell');
  const notifBadge = document.getElementById('notifBadge');

  function renderNotifications(){
    const body = document.getElementById('notifDrawerBody');
    if(!body || !lastDashboardData) return;
    const items = [];
    if(lastDashboardData.failed_count > 0){
      items.push({
        icon: '⚠️', tone: 'warn',
        title: `${lastDashboardData.failed_count} upload${lastDashboardData.failed_count === 1 ? '' : 's'} need${lastDashboardData.failed_count === 1 ? 's' : ''} attention`,
        sub: 'A scheduled publish failed — tap to review.',
        goto: 'needs-attention'
      });
    }
    (lastDashboardData.recent || []).slice(0, 6).forEach(r => {
      const isSched = r.status === 'scheduled';
      items.push({
        icon: isSched ? '🕒' : (r.status === 'failed' ? '⚠️' : '✅'),
        tone: r.status === 'failed' ? 'warn' : 'default',
        title: r.title || r.filename || 'Untitled upload',
        sub: isSched ? 'Scheduled' : (r.status === 'failed' ? 'Failed to publish' : 'Published'),
        goto: isSched ? 'scheduled' : 'published'
      });
    });
    body.innerHTML = items.length
      ? items.map(it => `
          <div class="notif-item ${it.tone === 'warn' ? 'warn' : ''}" data-notif-goto="${it.goto}">
            <div class="notif-icon">${it.icon}</div>
            <div class="notif-text"><div class="notif-title">${escapeHtml(it.title)}</div><div class="notif-sub">${escapeHtml(it.sub)}</div></div>
          </div>`).join('')
      : '<div class="empty-state">No notifications right now.</div>';

    const count = items.length;
    if(count > 0){ notifBadge.textContent = count > 9 ? '9+' : String(count); notifBadge.style.display = 'flex'; }
    else { notifBadge.style.display = 'none'; }
  }

  document.getElementById('notifDrawerBody').addEventListener('click', (e) => {
    const item = e.target.closest('[data-notif-goto]');
    if(!item) return;
    const dest = item.dataset.notifGoto;
    if(dest === 'needs-attention') goToNeedsAttention(); else showPage(dest);
    closeNotifDrawer();
  });

  function openNotifDrawer(){
    notifDrawer.classList.add('open');
    notifBackdrop.classList.add('open');
    renderNotifications();
  }
  function closeNotifDrawer(){
    notifDrawer.classList.remove('open');
    notifBackdrop.classList.remove('open');
  }
  notifBell.addEventListener('click', () => {
    notifDrawer.classList.contains('open') ? closeNotifDrawer() : openNotifDrawer();
  });
  document.getElementById('notifCloseBtn').addEventListener('click', closeNotifDrawer);
  notifBackdrop.addEventListener('click', closeNotifDrawer);
  document.addEventListener('keydown', (e) => { if(e.key === 'Escape') closeNotifDrawer(); });

  // ---- Publish progress panel ----
  // Closing (X / backdrop / Escape) only hides the panel — the job keeps
  // running server-side either way. Cancel is the only thing that
  // actually stops it, and even then only cooperatively: it won't
  // interrupt a platform upload already in flight, only steps that
  // haven't started yet (see app/publish_jobs.py).
  const publishPanel = document.getElementById('publishPanel');
  const publishBackdrop = document.getElementById('publishBackdrop');
  const publishPanelBody = document.getElementById('publishPanelBody');
  const publishPanelTitle = document.getElementById('publishPanelTitle');
  const publishPanelFooter = document.getElementById('publishPanelFooter');
  const publishPanelCancelBtn = document.getElementById('publishPanelCancelBtn');
  let currentPublishJobId = null;
  let publishPollTimer = null;

  const STEP_ICON = { pending: '', active: '', done: '✓', failed: '✕', cancelled: '–' };

  function renderPublishSteps(steps){
    publishPanelBody.innerHTML = steps.map(s => {
      const platformLabel = s.label;
      let sub = '';
      if(s.status === 'failed' && s.error) sub = `<div class="publish-step-sub error">${escapeHtml(s.error)}</div>`;
      else if(s.status === 'cancelled') sub = `<div class="publish-step-sub">Cancelled — didn't start.</div>`;
      else if(s.status === 'active') sub = `<div class="publish-step-sub">In progress…</div>`;
      else if(s.status === 'done') sub = `<div class="publish-step-sub success">Published.</div>`;
      return `
        <div class="publish-step">
          <div class="publish-step-icon ${s.status}">${STEP_ICON[s.status] || ''}</div>
          <div class="publish-step-text">
            <div class="publish-step-label">${escapeHtml(platformLabel)}</div>
            ${sub}
          </div>
        </div>`;
    }).join('');
  }

  function openPublishPanel(){
    publishPanel.classList.add('open');
    publishBackdrop.classList.add('open');
  }
  function closePublishPanel(){
    publishPanel.classList.remove('open');
    publishBackdrop.classList.remove('open');
  }

  async function pollPublishJob(jobId){
    currentPublishJobId = jobId;
    publishPanelTitle.textContent = 'Publishing…';
    publishPanelFooter.classList.remove('hidden');
    publishPanelCancelBtn.disabled = false;
    publishPanelCancelBtn.textContent = 'Cancel';

    clearInterval(publishPollTimer);
    const poll = async () => {
      let data;
      try{
        const res = await fetch(withAccount(`${API}/api/publish/jobs/${jobId}`));
        if(!res.ok) throw new Error();
        data = await res.json();
      }catch(err){
        return; // transient network hiccup — try again next tick rather than giving up
      }
      renderPublishSteps(data.steps);
      if(data.finished){
        clearInterval(publishPollTimer);
        currentPublishJobId = null;
        publishPanelFooter.classList.add('hidden');
        const anyFailed = data.steps.some(s => s.status === 'failed');
        const anyCancelled = data.steps.some(s => s.status === 'cancelled');
        publishPanelTitle.textContent = anyFailed ? 'Finished with errors'
          : anyCancelled ? 'Cancelled' : 'Published';
        loadDashboard();
      }
    };
    await poll();
    publishPollTimer = setInterval(poll, 1500);
  }

  publishPanelCancelBtn.addEventListener('click', async () => {
    if(!currentPublishJobId) return;
    publishPanelCancelBtn.disabled = true;
    publishPanelCancelBtn.textContent = 'Cancelling…';
    try{
      await fetch(withAccount(`${API}/api/publish/jobs/${currentPublishJobId}/cancel`), { method: 'POST' });
    }catch(err){ /* next poll will just keep showing steps in flight if this failed */ }
  });

  document.getElementById('publishPanelCloseBtn').addEventListener('click', closePublishPanel);
  publishBackdrop.addEventListener('click', closePublishPanel);
  document.addEventListener('keydown', (e) => { if(e.key === 'Escape' && publishPanel.classList.contains('open')) closePublishPanel(); });

  // ================= Dashboard =================
  const PLATFORM_THUMB = {
    youtube:   {bg:'#FF0000', icon:'<svg width="16" height="16" viewBox="0 0 24 24"><path d="M10 8.5l6 3.5-6 3.5v-7z" fill="#fff"/></svg>'},
    facebook:  {bg:'#1877F2', icon:'<svg width="16" height="16" viewBox="0 0 24 24"><path d="M15.5 12.2h-2.1V19h-2.8v-6.8H9.1V9.9h1.5V8.4c0-1.5.8-3 3.2-3h2v2.3h-1.5c-.3 0-.7.2-.7.9v1.3h2.3l-.4 2.3z" fill="#fff"/></svg>'},
    instagram: {bg:'linear-gradient(135deg,#FEDA75,#D62976,#962FBF,#4F5BD5)', icon:'<svg width="15" height="15" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="4" fill="none" stroke="#fff" stroke-width="1.8"/><circle cx="12" cy="12" r="3" fill="none" stroke="#fff" stroke-width="1.8"/></svg>'},
    tiktok:    {bg:'#000', icon:'<svg width="14" height="14" viewBox="0 0 24 24"><path d="M15.5 5c.3 1.6 1.3 2.7 3 2.9v2.1c-1.1 0-2.1-.3-3-.9v4.6c0 2.4-1.9 4.2-4.2 4.2-2.4 0-4.2-1.9-4.2-4.2 0-2.3 1.8-4.2 4.1-4.2.2 0 .5 0 .7.1v2.2c-.2-.1-.4-.1-.7-.1-1.1 0-2 .9-2 2s.9 2 2 2 2.1-.9 2.1-2.1V5h2.2z" fill="#fff"/></svg>'},
  };
  function thumbHtml(platformsStr){
    const first = (platformsStr.split(',')[0] || '').trim().toLowerCase();
    const cfg = PLATFORM_THUMB[first] || {bg:'var(--text-light)', icon:''};
    return `<div class="recent-thumb" style="background:${cfg.bg}">${cfg.icon}</div>`;
  }

  function libraryRowHtml(rec){
    const platforms = rec.platforms.split(',').map(p=>p.trim()).join(', ');
    const yt = rec.results && rec.results.youtube;
    const when = rec.status === 'scheduled' && rec.scheduled_time
      ? 'Goes live ' + new Date(rec.scheduled_time).toLocaleString()
      : new Date(rec.created_at).toLocaleString();
    const link = yt && yt.ok && yt.url ? ` • <a href="${yt.url}" target="_blank" rel="noopener">View</a>` : '';
    const pillClass = rec.status === 'published' ? '' : rec.status === 'scheduled' ? 'sched' : 'fail';
    const pillLabel = rec.status.charAt(0).toUpperCase() + rec.status.slice(1);
    return `
      <div class="lib-row">
        ${thumbHtml(rec.platforms)}
        <div class="lib-info">
          <div class="n">${escapeHtml(rec.title)}</div>
          <div class="d">${escapeHtml(platforms)} • ${when}${link}</div>
        </div>
        <div class="pub-pill ${pillClass}">${pillLabel}</div>
      </div>`;
  }

  let lastDashboardData = null;

  async function loadDashboard(){
    try{
      const res = await fetch(withAccount(`${API}/api/dashboard/summary`));
      if(!res.ok) throw new Error();
      const data = await res.json();
      lastDashboardData = data;
      renderNotifications();
      document.getElementById('statScheduled').textContent = data.scheduled_count;
      document.getElementById('statPublished').textContent = data.published_count;
      document.getElementById('statConnected').textContent = data.connected_accounts;
      document.getElementById('statFailed').textContent = data.failed_count;
      document.getElementById('statFailedCard').classList.toggle('tint-warn', data.failed_count > 0);

      const list = document.getElementById('dashRecentList');
      list.innerHTML = data.recent.length
        ? data.recent.map(libraryRowHtml).join('')
        : '<div class="empty-state">No uploads yet — head to New Upload to publish your first video.</div>';

      const sidebarBox = document.getElementById('sidebarRecentUpload');
      if(sidebarBox){
        sidebarBox.innerHTML = data.recent.length
          ? libraryRowHtml(data.recent[0])
          : '<div class="empty-state">No uploads yet.</div>';
      }
    }catch(err){
      document.getElementById('dashRecentList').innerHTML = '<div class="empty-state">Could not load dashboard data.</div>';
    }
    loadDashboardPlatforms();
  }

  function fmtCompact(n){
    n = Number(n || 0);
    if(n < 1000) return String(n);
    const units = [{v:1e9,s:'B'},{v:1e6,s:'M'},{v:1e3,s:'K'}];
    for(const u of units){
      if(n >= u.v) return (n / u.v).toFixed(n % u.v === 0 ? 0 : 1).replace(/\.0$/, '') + u.s;
    }
    return String(n);
  }

  async function loadDashboardPlatforms(){
    const LABEL = {youtube: 'subscribers', facebook: 'followers', instagram: 'followers'};
    try{
      const res = await fetch(withAccount(`${API}/api/status`));
      const data = await res.json();
      ['youtube','facebook','instagram'].forEach(p=>{
        const tile = document.getElementById(`dashPlatform-${p}`);
        const countEl = document.getElementById(`dashPlatformCount-${p}`);
        if(!tile) return;
        const info = data[p] || {};
        tile.classList.toggle('connected', !!info.connected);
        const count = p === 'youtube' ? info.subscribers : info.followers;
        if(countEl){
          countEl.textContent = (info.connected && count !== undefined && count !== null)
            ? `${fmtCompact(count)} ${LABEL[p]}`
            : '';
        }
      });
    }catch(err){
      // Fetch failed — stop the skeletons from shimmering forever; leave
      // tiles in their default (disconnected-looking) state otherwise.
      ['youtube','facebook','instagram'].forEach(p=>{
        const countEl = document.getElementById(`dashPlatformCount-${p}`);
        if(countEl) countEl.textContent = '';
      });
    }
  }

  // ================= Accounts (management) page =================
  function renderAcctMgmtPage(){
    const list = document.getElementById('acctMgmtList');
    if(!list) return;
    list.innerHTML = accountsCache.map(a => `
      <div class="account-row" data-account-id="${a.id}" style="${a.id === currentAccountId ? '' : 'cursor:pointer;'}">
        <div class="acc-icon" style="background:var(--indigo);color:#fff;font-weight:700;font-size:15px;border-radius:50%;">${escapeHtml((a.name[0]||'?').toUpperCase())}</div>
        <div class="acc-info">
          <div class="n">${escapeHtml(a.name)}</div>
          <div class="h">${a.id === currentAccountId ? 'Current account' : 'Tap to switch to this account'}</div>
        </div>
        <div class="acc-row-actions">
          ${a.id === currentAccountId ? '<div class="connected-pill">Active</div>' : ''}
          <button class="acc-btn" data-action="rename-account">Rename</button>
          <button class="acc-btn danger" data-action="delete-account" ${accountsCache.length <= 1 ? 'disabled' : ''}>Delete</button>
        </div>
      </div>
    `).join('');
  }

  document.getElementById('acctMgmtList').addEventListener('click', async (e)=>{
    const row = e.target.closest('[data-account-id]');
    if(!row) return;
    const id = parseInt(row.dataset.accountId, 10);
    const acc = accountsCache.find(a => a.id === id);
    const btn = e.target.closest('[data-action]');

    if(btn && btn.dataset.action === 'rename-account'){
      const newName = prompt('New name for this account:', acc ? acc.name : '');
      if(!newName || !newName.trim() || (acc && newName.trim() === acc.name)) return;
      const fd = new FormData();
      fd.append('name', newName.trim());
      try{
        const res = await fetch(`${API}/api/accounts/${id}`, { method: 'PATCH', body: fd });
        if(!res.ok){
          const err = await res.json().catch(()=>({detail:'Rename failed.'}));
          throw new Error(err.detail);
        }
        await loadAccounts();
        renderAcctMgmtPage();
        showToast('Account renamed.');
      }catch(err){
        showToast('Could not rename account: ' + err.message, 5000);
      }
      return;
    }

    if(btn && btn.dataset.action === 'delete-account'){
      if(accountsCache.length <= 1) return;
      const ok = confirm(`Delete "${acc ? acc.name : 'this account'}"? This permanently removes its scheduled/published post history and platform connections. This can't be undone.`);
      if(!ok) return;
      try{
        const res = await fetch(`${API}/api/accounts/${id}`, { method: 'DELETE' });
        if(!res.ok){
          const err = await res.json().catch(()=>({detail:'Delete failed.'}));
          throw new Error(err.detail);
        }
        const wasCurrent = id === currentAccountId;
        await loadAccounts();
        if(wasCurrent) switchAccount(accountsCache[0].id);
        renderAcctMgmtPage();
        showToast('Account deleted.');
      }catch(err){
        showToast('Could not delete account: ' + err.message, 5000);
      }
      return;
    }

    // Row click (not a button): switch to that account.
    if(!btn && acc && acc.id !== currentAccountId){
      switchAccount(acc.id);
      renderAcctMgmtPage();
    }
  });

  document.getElementById('acctMgmtAddBtn').addEventListener('click', async ()=>{
    await promptCreateAccount();
    renderAcctMgmtPage();
  });

  // ================= Admin panel (Settings page) =================
  // Only visible to an admin (see docs/DECISIONS.md 010) — hidden by
  // default for everyone else, and every underlying /api/admin/* call is
  // independently gated server-side regardless of what the UI shows.
  let adminUsersCache = [];
  let adminAccountsCache = [];

  async function loadSettingsPage(){
    const usersCard = document.getElementById('adminUsersCard');
    const accountsCard = document.getElementById('adminAccountsCard');
    try{
      const me = await (await fetch('/api/auth/me')).json();
      if(!me.is_admin){
        usersCard.style.display = 'none';
        accountsCard.style.display = 'none';
        return;
      }
      usersCard.style.display = '';
      accountsCard.style.display = '';
      const [users, accts] = await Promise.all([
        fetch('/api/admin/users').then(r => r.json()),
        fetch('/api/admin/accounts').then(r => r.json()),
      ]);
      adminUsersCache = users;
      adminAccountsCache = accts;
      renderAdminUsers();
      renderAdminAccounts();
    }catch(err){
      showToast('Could not load admin panel — is the server running?');
    }
  }

  function renderAdminUsers(){
    const list = document.getElementById('adminUsersList');
    if(!list) return;
    list.innerHTML = adminUsersCache.map(u => `
      <div class="account-row" data-user-id="${u.id}">
        <div class="acc-icon" style="background:var(--indigo);color:#fff;font-weight:700;font-size:15px;border-radius:50%;">${escapeHtml((u.username[0]||'?').toUpperCase())}</div>
        <div class="acc-info">
          <div class="n">${escapeHtml(u.username)}</div>
          <div class="h">${u.account_count} account${u.account_count === 1 ? '' : 's'}</div>
        </div>
        <div class="acc-row-actions">
          ${u.is_admin ? '<div class="connected-pill">Admin</div>' : ''}
          <button class="acc-btn" data-action="reset-password">Reset password</button>
          <button class="acc-btn" data-action="toggle-admin">${u.is_admin ? 'Remove admin' : 'Make admin'}</button>
          <button class="acc-btn danger" data-action="delete-user" ${u.account_count > 0 ? 'disabled title="Reassign their accounts first"' : ''}>Delete</button>
        </div>
      </div>
    `).join('');
  }

  function renderAdminAccounts(){
    const list = document.getElementById('adminAccountsList');
    if(!list) return;
    const userOptions = u => adminUsersCache.map(usr =>
      `<option value="${usr.id}" ${usr.id === u ? 'selected' : ''}>${escapeHtml(usr.username)}</option>`
    ).join('');
    list.innerHTML = adminAccountsCache.map(a => `
      <div class="account-row" data-account-id="${a.id}">
        <div class="acc-icon" style="background:var(--indigo);color:#fff;font-weight:700;font-size:15px;border-radius:50%;">${escapeHtml((a.name[0]||'?').toUpperCase())}</div>
        <div class="acc-info">
          <div class="n">${escapeHtml(a.name)}</div>
          <div class="h">Owned by ${escapeHtml(a.owner_username || 'nobody (orphaned)')}</div>
        </div>
        <div class="acc-row-actions">
          <select class="reassign-select" data-action="reassign-select">${userOptions(a.user_id)}</select>
        </div>
      </div>
    `).join('');
  }

  document.getElementById('adminUsersList').addEventListener('click', async (e)=>{
    const row = e.target.closest('[data-user-id]');
    if(!row) return;
    const id = parseInt(row.dataset.userId, 10);
    const u = adminUsersCache.find(x => x.id === id);
    const btn = e.target.closest('[data-action]');
    if(!btn || btn.disabled) return;

    if(btn.dataset.action === 'reset-password'){
      const newPassword = prompt(`New password for "${u.username}" (at least 8 characters):`);
      if(!newPassword) return;
      if(newPassword.length < 8){ showToast('Password must be at least 8 characters.'); return; }
      try{
        const fd = new FormData(); fd.append('new_password', newPassword);
        const res = await fetch(`/api/admin/users/${id}/set-password`, { method: 'POST', body: fd });
        if(!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || 'Failed.');
        showToast(`Password reset for "${u.username}". They've been logged out everywhere.`, 5000);
      }catch(err){ showToast('Could not reset password: ' + err.message, 5000); }
      return;
    }

    if(btn.dataset.action === 'toggle-admin'){
      const makeAdmin = !u.is_admin;
      const verb = makeAdmin ? 'give admin access to' : 'remove admin access from';
      if(!confirm(`Are you sure you want to ${verb} "${u.username}"?`)) return;
      try{
        const fd = new FormData(); fd.append('is_admin', makeAdmin ? 'true' : 'false');
        const res = await fetch(`/api/admin/users/${id}/set-admin`, { method: 'POST', body: fd });
        if(!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || 'Failed.');
        await loadSettingsPage();
        showToast(makeAdmin ? `"${u.username}" is now an admin.` : `Removed admin access from "${u.username}".`);
      }catch(err){ showToast('Could not update admin status: ' + err.message, 5000); }
      return;
    }

    if(btn.dataset.action === 'delete-user'){
      if(!confirm(`Delete the user "${u.username}"? This can't be undone.`)) return;
      try{
        const res = await fetch(`/api/admin/users/${id}`, { method: 'DELETE' });
        if(!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || 'Failed.');
        await loadSettingsPage();
        showToast(`Deleted user "${u.username}".`);
      }catch(err){ showToast('Could not delete user: ' + err.message, 5000); }
      return;
    }
  });

  document.getElementById('adminAccountsList').addEventListener('change', async (e)=>{
    const select = e.target.closest('[data-action="reassign-select"]');
    if(!select) return;
    const row = e.target.closest('[data-account-id]');
    const accountId = parseInt(row.dataset.accountId, 10);
    const acc = adminAccountsCache.find(a => a.id === accountId);
    const newUserId = parseInt(select.value, 10);
    if(newUserId === acc.user_id) return;
    const newOwner = adminUsersCache.find(u => u.id === newUserId);
    if(!confirm(`Move "${acc.name}" to ${newOwner ? newOwner.username : 'this user'}? Its platform connections, posts, and analytics go with it.`)){
      select.value = acc.user_id;
      return;
    }
    try{
      const fd = new FormData(); fd.append('new_user_id', newUserId);
      const res = await fetch(`/api/admin/accounts/${accountId}/reassign`, { method: 'POST', body: fd });
      if(!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || 'Failed.');
      await loadSettingsPage();
      showToast(`Reassigned "${acc.name}".`);
    }catch(err){
      select.value = acc.user_id;
      showToast('Could not reassign account: ' + err.message, 5000);
    }
  });

  // ================= Platforms page =================
  async function loadPlatformsPage(){
    const nameEl = document.getElementById('platformsPageAccountName');
    if(nameEl) nameEl.textContent = currentAccountName();
    const ytRow = document.getElementById('page-acc-youtube');
    const ytHandle = ytRow.querySelector('[data-handle]');
    const ytBtn = ytRow.querySelector('.acc-btn');

    const fbRow = document.getElementById('page-acc-facebook');
    const fbHandle = fbRow.querySelector('[data-handle]');
    const fbBtn = fbRow.querySelector('.acc-btn');
    const fbForm = document.getElementById('facebookForm');

    const igRow = document.getElementById('page-acc-instagram');
    const igHandle = igRow.querySelector('[data-handle]');
    const igPill = igRow.querySelector('[data-pill]');

    try{
      const res = await fetch(withAccount(`${API}/api/status`));
      const data = await res.json();

      const yt = data.youtube;
      if(yt && yt.connected){
        ytHandle.textContent = yt.channel || 'Connected';
        ytBtn.textContent = 'Disconnect';
        ytBtn.removeAttribute('href');
        ytBtn.classList.add('danger');
        ytBtn.dataset.action = 'disconnect-youtube';
      } else {
        ytHandle.textContent = 'Not connected';
        ytBtn.textContent = 'Connect';
        ytBtn.setAttribute('href', withAccount('/api/connect/youtube'));
        ytBtn.classList.remove('danger');
        ytBtn.dataset.action = 'connect-youtube';
      }

      const fb = data.facebook;
      if(fb && fb.connected){
        fbHandle.textContent = fb.channel || 'Connected';
        fbBtn.textContent = 'Disconnect';
        fbBtn.classList.add('danger');
        fbBtn.dataset.action = 'disconnect-facebook';
        fbForm.style.display = 'none';
      } else {
        fbHandle.textContent = (fb && fb.error) ? fb.error : 'Not connected';
        fbBtn.textContent = 'Connect';
        fbBtn.classList.remove('danger');
        fbBtn.dataset.action = 'toggle-facebook-form';
      }

      const ig = data.instagram;
      if(ig && ig.connected){
        igHandle.textContent = '@' + ig.channel;
        igPill.textContent = 'Connected';
        igPill.style.background = '';
        igPill.style.color = '';
      } else {
        igHandle.textContent = (fb && fb.connected)
          ? ((ig && ig.error) || 'No Instagram Business account linked to this Page.')
          : 'Connect Facebook first';
        igPill.textContent = 'Not linked';
        igPill.style.background = '#f1f2f6';
        igPill.style.color = 'var(--text-mid)';
      }
    }catch(err){
      ytHandle.textContent = 'Could not reach the server';
      fbHandle.textContent = 'Could not reach the server';
    }
  }

  document.getElementById('page-acc-youtube').addEventListener('click', async (e)=>{
    const btn = e.target.closest('[data-action]');
    if(!btn) return;
    if(btn.dataset.action === 'disconnect-youtube'){
      e.preventDefault();
      btn.textContent = 'Disconnecting...';
      try{
        await fetch(withAccount(`${API}/api/disconnect/youtube`), { method: 'POST' });
        showToast('YouTube disconnected.');
      }catch(err){
        showToast('Could not disconnect — is the server running?');
      }
      loadPlatformsPage();
      loadStatus();
    }
    // connect-youtube: let the <a href> navigate normally to start the OAuth flow
  });

  document.getElementById('page-acc-facebook').addEventListener('click', async (e)=>{
    const btn = e.target.closest('[data-action]');
    if(!btn) return;
    if(btn.dataset.action === 'toggle-facebook-form'){
      const form = document.getElementById('facebookForm');
      form.style.display = form.style.display === 'none' ? 'block' : 'none';
    } else if(btn.dataset.action === 'disconnect-facebook'){
      btn.textContent = 'Disconnecting...';
      try{
        await fetch(withAccount(`${API}/api/disconnect/facebook`), { method: 'POST' });
        showToast('Facebook disconnected.');
      }catch(err){
        showToast('Could not disconnect — is the server running?');
      }
      loadPlatformsPage();
      loadStatus();
    }
  });

  document.getElementById('fbSaveBtn').addEventListener('click', async ()=>{
    const appId = document.getElementById('fbAppId').value.trim();
    const appSecret = document.getElementById('fbAppSecret').value.trim();
    const pageId = document.getElementById('fbPageId').value.trim();
    const pageToken = document.getElementById('fbPageToken').value.trim();
    if(!appId || !appSecret || !pageId || !pageToken){
      showToast('Fill in all four Facebook fields.');
      return;
    }
    const fd = new FormData();
    fd.append('app_id', appId);
    fd.append('app_secret', appSecret);
    fd.append('page_id', pageId);
    fd.append('page_access_token', pageToken);

    const btn = document.getElementById('fbSaveBtn');
    btn.disabled = true;
    btn.textContent = 'Connecting...';
    try{
      const res = await fetch(withAccount(`${API}/api/connect/facebook`), { method: 'POST', body: fd });
      if(!res.ok){
        const err = await res.json().catch(()=>({detail: 'Connection failed.'}));
        throw new Error(err.detail);
      }
      const data = await res.json();
      showToast(data.instagram_linked
        ? `Facebook connected — Instagram @${data.instagram_username} linked too.`
        : 'Facebook connected. (No Instagram Business account found on this Page.)', 5000);
      loadPlatformsPage();
      loadStatus();
    }catch(err){
      showToast('Facebook connect failed: ' + err.message, 6000);
    }finally{
      btn.disabled = false;
      btn.textContent = 'Save & Connect';
    }
  });

  // ================= Scheduled / Published =================
  async function loadLibrary(status){
    const containerId = status === 'scheduled' ? 'scheduledList' : 'publishedList';
    const container = document.getElementById(containerId);
    container.innerHTML = '<div class="empty-state">Loading…</div>';
    try{
      const res = await fetch(withAccount(`${API}/api/library?status=${status}`));
      if(!res.ok) throw new Error();
      const records = await res.json();
      container.innerHTML = records.length
        ? records.map(libraryRowHtml).join('')
        : `<div class="empty-state">Nothing ${status} yet.</div>`;
    }catch(err){
      container.innerHTML = '<div class="empty-state">Could not load — is the server running?</div>';
    }
  }

  document.querySelectorAll('[data-refresh]').forEach(el=>{
    el.addEventListener('click', () => loadLibrary(el.dataset.refresh));
  });

  // ================= Analytics =================
  let currentAnalyticsDays = 28;
  let currentAnalyticsPlatform = 'youtube';
  let currentAnalyticsView = 'dashboard';  // 'dashboard' or 'table'
  let lastAnalyticsData = null;  // cached so toggling view doesn't refetch

  function fmtNum(n){ return Number(n || 0).toLocaleString(); }
  function fmtHours(minutes){ return (Number(minutes || 0) / 60).toFixed(1) + 'h'; }
  function fmtDuration(seconds){
    seconds = Number(seconds || 0);
    const m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }

  function analyticsMessageHtml(message, showConnectButton){
    return `
      <div class="card" style="text-align:center;padding:56px 24px;">
        <div style="font-size:40px;margin-bottom:12px;">📊</div>
        <h2>Analytics</h2>
        <div class="sub" style="margin-top:8px;">${escapeHtml(message)}</div>
        ${showConnectButton ? '<button class="choose-btn" style="margin-top:18px;" data-goto="platforms">Go to Platforms</button>' : ''}
      </div>`;
  }

  function renderYouTubeAnalytics(data, days){
    const p = data.period_totals;
    const maxViews = Math.max(1, ...data.daily.map(d => d.views));
    const barsHtml = data.daily.map(d => {
      const h = Math.max(Math.round((d.views / maxViews) * 100), 2);
      const dateLabel = new Date(d.date + 'T00:00:00').toLocaleDateString(undefined, {month:'short', day:'numeric'});
      return `<div class="bar-wrap" title="${dateLabel}: ${fmtNum(d.views)} views"><div class="bar" style="height:${h}%"></div></div>`;
    }).join('');

    const dayOptions = [1, 7, 28, 90].map(n =>
      `<button class="pill-btn ${n === days ? 'active' : ''}" data-days="${n}">${n === 1 ? 'Today' : n + 'd'}</button>`
    ).join('');

    return `
      <div class="analytics-header">
        <div>
          <h2 style="margin:0;">${escapeHtml(data.channel_title)}</h2>
          <div class="sub">${fmtNum(data.lifetime.subscribers)} subscribers • ${fmtNum(data.lifetime.total_views)} lifetime views • ${fmtNum(data.lifetime.video_count)} videos</div>
        </div>
        <div class="day-toggle">${dayOptions}</div>
      </div>

      <div class="stat-grid">
        <div class="stat-card"><div class="stat-label">Views</div><div class="stat-value">${fmtNum(p.views)}</div></div>
        <div class="stat-card"><div class="stat-label">Watch Time</div><div class="stat-value">${fmtHours(p.watch_time_minutes)}</div></div>
        <div class="stat-card"><div class="stat-label">Avg. View Duration</div><div class="stat-value">${fmtDuration(p.avg_view_duration_seconds)}</div></div>
        <div class="stat-card"><div class="stat-label">Net Subscribers</div><div class="stat-value ${p.subscribers_net < 0 ? 'warn' : ''}">${p.subscribers_net > 0 ? '+' : ''}${fmtNum(p.subscribers_net)}</div></div>
      </div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Likes</div><div class="stat-value">${fmtNum(p.likes)}</div></div>
        <div class="stat-card"><div class="stat-label">Comments</div><div class="stat-value">${fmtNum(p.comments)}</div></div>
        <div class="stat-card"><div class="stat-label">Shares</div><div class="stat-value">${fmtNum(p.shares)}</div></div>
      </div>

      <div class="card">
        <h2>Daily Views</h2>
        <div class="sub">${days === 1 ? 'Today.' : `Last ${days} days.`}</div>
        <div class="bar-chart">${barsHtml || '<div class="empty-state">No data for this period.</div>'}</div>
      </div>

      <div class="card">
        <h2>Videos</h2>
        <div class="sub">${days === 1
          ? 'Only videos that received views today — ranked by whichever metric you pick below.'
          : `Videos with activity in the last ${days} days — ranked by whichever metric you pick below.`}</div>
        <div id="videoFilterBarContainer"></div>
        <div id="videoListContainer"><div class="empty-state">Loading…</div></div>
      </div>
    `;
  }

  function renderDailyBarChart(daily, days){
    const maxViews = Math.max(1, ...daily.map(d => d.views));
    return daily.map(d => {
      const h = Math.max(Math.round((d.views / maxViews) * 100), 2);
      const dateLabel = new Date(d.date + 'T00:00:00').toLocaleDateString(undefined, {month:'short', day:'numeric'});
      return `<div class="bar-wrap" title="${dateLabel}: ${fmtNum(d.views)}"><div class="bar" style="height:${h}%"></div></div>`;
    }).join('') || '<div class="empty-state">No data for this period.</div>';
  }

  function dayToggleHtml(days){
    return [7, 28, 90].map(n =>
      `<button class="pill-btn ${n === days ? 'active' : ''}" data-days="${n}">${n}d</button>`
    ).join('');
  }

  function renderFacebookAnalytics(data, days){
    const p = data.period_totals;
    return `
      <div class="analytics-header">
        <div>
          <h2 style="margin:0;">${escapeHtml(data.channel_title)}</h2>
          <div class="sub">${fmtNum(data.lifetime.followers)} followers</div>
        </div>
        <div class="day-toggle">${dayToggleHtml(days)}</div>
      </div>

      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Page Views</div><div class="stat-value">${fmtNum(p.views)}</div></div>
        <div class="stat-card"><div class="stat-label">Video Views</div><div class="stat-value">${fmtNum(p.video_views)}</div></div>
        <div class="stat-card"><div class="stat-label">Post Engagements</div><div class="stat-value">${fmtNum(p.engagements)}</div></div>
      </div>

      <div class="card">
        <h2>Daily Page Views</h2>
        <div class="sub">Last ${days} days.</div>
        <div class="bar-chart">${renderDailyBarChart(data.daily, days)}</div>
      </div>

      <div class="card">
        <h2>Videos</h2>
        <div class="sub">Ranked by whichever metric you pick below.</div>
        <div id="videoFilterBarContainer"></div>
        <div id="videoListContainer"><div class="empty-state">Loading…</div></div>
      </div>
    `;
  }

  function renderInstagramAnalytics(data, days){
    const p = data.period_totals;
    return `
      <div class="analytics-header">
        <div>
          <h2 style="margin:0;">${escapeHtml(data.channel_title)}</h2>
          <div class="sub">${fmtNum(data.lifetime.followers)} followers • ${fmtNum(data.lifetime.media_count)} posts</div>
        </div>
        <div class="day-toggle">${dayToggleHtml(days)}</div>
      </div>

      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Views</div><div class="stat-value">${fmtNum(p.views)}</div></div>
        <div class="stat-card"><div class="stat-label">Reach</div><div class="stat-value">${fmtNum(p.reach)}</div></div>
        <div class="stat-card"><div class="stat-label">Profile Views</div><div class="stat-value">${fmtNum(p.profile_views)}</div></div>
      </div>

      <div class="card">
        <h2>Daily Views</h2>
        <div class="sub">Last ${days} days.</div>
        <div class="bar-chart">${renderDailyBarChart(data.daily, days)}</div>
      </div>

      <div class="card">
        <h2>Posts</h2>
        <div class="sub">Ranked by whichever metric you pick below.</div>
        <div id="videoFilterBarContainer"></div>
        <div id="videoListContainer"><div class="empty-state">Loading…</div></div>
      </div>
    `;
  }

  const analyticsConfig = {
    youtube: {
      endpoint: '/api/analytics/summary',
      render: renderYouTubeAnalytics,
      connectMsg: "YouTube isn't connected yet — connect it from Platforms to see analytics.",
    },
    facebook: {
      endpoint: '/api/analytics/facebook',
      render: renderFacebookAnalytics,
      connectMsg: "Facebook isn't connected yet — connect it from Platforms to see analytics.",
    },
    instagram: {
      endpoint: '/api/analytics/instagram',
      render: renderInstagramAnalytics,
      connectMsg: "Instagram isn't connected yet — connect a Facebook Page with a linked Instagram Business account from Platforms.",
    },
  };

  // ---- Video/post list filters (client-side sort+limit over an already-fetched pool) ----
  const VIDEO_SORT_OPTIONS = {
    youtube: [
      {value: 'views', label: 'Views'},
      {value: 'watch_time_minutes', label: 'Watch Time'},
      {value: 'likes', label: 'Likes'},
      {value: 'comments', label: 'Comments'},
      {value: 'avg_view_percentage', label: 'Retention %'},
    ],
    facebook: [
      {value: 'views', label: 'Views'},
      {value: 'likes', label: 'Likes'},
      {value: 'comments', label: 'Comments'},
    ],
    instagram: [
      {value: 'views', label: 'Views'},
      {value: 'engagement', label: 'Engagement'},
      {value: 'likes', label: 'Likes'},
      {value: 'comments', label: 'Comments'},
    ],
  };
  const VIDEO_LIMIT_OPTIONS = [5, 10, 25, 999];  // 999 renders as "All"

  const VIDEO_ROW_RENDERERS = {
    youtube: v => `
      <div class="lib-row">
        <img class="vid-thumb" src="${v.thumbnail || ''}" alt="" onerror="this.style.visibility='hidden'">
        <div class="lib-info">
          <div class="n">${escapeHtml(v.title)}</div>
          <div class="d">${fmtNum(v.lifetime_views)} total views <span class="gain-pill">+${fmtNum(v.views)} ${currentAnalyticsDays === 1 ? 'today' : `in ${currentAnalyticsDays}d`}</span> • ${fmtHours(v.watch_time_minutes)} watched • ${v.avg_view_percentage}% retention • ${fmtNum(v.likes)} likes</div>
        </div>
        <button class="metrics-btn" data-platform="youtube" data-video-id="${v.video_id}">Metrics</button>
      </div>`,
    facebook: v => `
      <div class="lib-row">
        <img class="vid-thumb" src="${v.thumbnail || ''}" alt="" onerror="this.style.visibility='hidden'">
        <div class="lib-info">
          <div class="n">${escapeHtml(v.title)}</div>
          <div class="d">${fmtNum(v.views)} views • ${fmtNum(v.likes)} likes • ${fmtNum(v.comments)} comments</div>
        </div>
        <button class="metrics-btn" data-platform="facebook" data-video-id="${v.video_id}">Metrics</button>
      </div>`,
    instagram: v => `
      <div class="lib-row">
        <img class="vid-thumb" src="${v.thumbnail || ''}" alt="" onerror="this.style.visibility='hidden'">
        <div class="lib-info">
          <div class="n">${escapeHtml(v.title)}</div>
          <div class="d">${fmtNum(v.views)} views • ${fmtNum(v.likes)} likes • ${fmtNum(v.comments)} comments</div>
        </div>
        <button class="metrics-btn" data-platform="instagram" data-video-id="${v.media_id}">Metrics</button>
      </div>`,
  };

  let currentVideoList = [];
  let videoFilterState = { sortBy: 'views', limit: 5 };
  let tableSortState = { field: 'views', dir: 'desc' };

  // ---- Analytics: Table view (excel-style comparison grid) ----
  // Columns are exactly what the summary endpoint already returns per
  // video/post — no extra per-row fetches, so switching to Table view (or
  // sorting/re-sorting it) is instant.
  const TABLE_COLUMNS = {
    youtube: [
      {field: 'title', label: 'Title', type: 'title'},
      {field: 'views', label: 'Views (period)', type: 'num'},
      {field: 'lifetime_views', label: 'Lifetime Views', type: 'num'},
      {field: 'watch_time_minutes', label: 'Watch Time', type: 'num', fmt: v => fmtHours(v)},
      {field: 'avg_view_percentage', label: 'Avg. Retention', type: 'num', fmt: v => `${v}%`},
      {field: 'likes', label: 'Likes', type: 'num'},
      {field: 'comments', label: 'Comments', type: 'num'},
    ],
    facebook: [
      {field: 'title', label: 'Title', type: 'title'},
      {field: 'views', label: 'Views', type: 'num'},
      {field: 'likes', label: 'Likes', type: 'num'},
      {field: 'comments', label: 'Comments', type: 'num'},
    ],
    instagram: [
      {field: 'title', label: 'Title', type: 'title'},
      {field: 'views', label: 'Views', type: 'num'},
      {field: 'engagement', label: 'Engagement', type: 'num'},
      {field: 'likes', label: 'Likes', type: 'num'},
      {field: 'comments', label: 'Comments', type: 'num'},
    ],
  };

  function renderAnalyticsTable(platformKey, videos){
    const cols = TABLE_COLUMNS[platformKey];
    const sorted = [...videos].sort((a, b) => {
      const av = a[tableSortState.field], bv = b[tableSortState.field];
      let cmp;
      if(typeof av === 'string' || typeof bv === 'string'){
        cmp = String(av ?? '').localeCompare(String(bv ?? ''));
      } else {
        cmp = (Number(av) || 0) - (Number(bv) || 0);
      }
      return tableSortState.dir === 'asc' ? cmp : -cmp;
    });
    const limited = videoFilterState.limit >= 999 ? sorted : sorted.slice(0, videoFilterState.limit);

    const headHtml = cols.map(c => {
      const active = c.field === tableSortState.field;
      const arrow = active ? (tableSortState.dir === 'asc' ? '▲' : '▼') : '';
      return `<th data-sort-field="${c.field}" ${active ? 'data-sort-active' : ''}>${escapeHtml(c.label)}${arrow ? `<span class="sort-arrow">${arrow}</span>` : ''}</th>`;
    }).join('');

    const rowsHtml = limited.map(v => {
      const cells = cols.map(c => {
        if(c.type === 'title'){
          return `<td><img class="table-thumb" src="${v.thumbnail || ''}" alt="" onerror="this.style.visibility='hidden'"><span class="table-title" title="${escapeHtml(v.title || '')}">${escapeHtml(v.title || 'Untitled')}</span></td>`;
        }
        const raw = v[c.field];
        const display = c.fmt ? c.fmt(raw ?? 0) : fmtNum(raw ?? 0);
        return `<td class="num">${display}</td>`;
      }).join('');
      const idField = platformKey === 'instagram' ? v.media_id : v.video_id;
      return `<tr data-video-id="${idField}" data-platform="${platformKey}" style="cursor:pointer;">${cells}</tr>`;
    }).join('');

    return `
      <div class="card">
        <div class="recent-header">
          <h2>${platformKey === 'instagram' ? 'Posts' : 'Videos'} — Table</h2>
          <span class="sub">Click a column to sort, click a row for full metrics.</span>
        </div>
        <div id="videoFilterBarContainer"></div>
        <div class="analytics-table-wrap">
          <table class="analytics-table">
            <thead><tr>${headHtml}</tr></thead>
            <tbody>${rowsHtml || `<tr><td colspan="${cols.length}"><div class="empty-state">Nothing to show for this period.</div></td></tr>`}</tbody>
          </table>
        </div>
      </div>
    `;
  }


  function videoFilterBarHtml(platformKey, state){
    const limitPills = VIDEO_LIMIT_OPTIONS.map(n => {
      const label = n === 999 ? 'All' : `Top ${n}`;
      return `<button class="pill-btn ${state.limit === n ? 'active' : ''}" data-video-limit="${n}">${label}</button>`;
    }).join('');
    const opts = VIDEO_SORT_OPTIONS[platformKey];
    const sortSelect = `<select class="sort-select" id="videoSortSelect">
      ${opts.map(o => `<option value="${o.value}" ${o.value === state.sortBy ? 'selected' : ''}>Sort: ${o.label}</option>`).join('')}
    </select>`;
    return `<div class="video-filters"><div class="day-toggle">${limitPills}</div>${sortSelect}</div>`;
  }

  function sortAndLimitVideos(videos, sortBy, limit){
    const sorted = [...videos].sort((a, b) => (Number(b[sortBy]) || 0) - (Number(a[sortBy]) || 0));
    return limit >= 999 ? sorted : sorted.slice(0, limit);
  }

  function renderVideoSection(){
    const barContainer = document.getElementById('videoFilterBarContainer');
    const listContainer = document.getElementById('videoListContainer');
    if(!barContainer || !listContainer) return;

    barContainer.innerHTML = videoFilterBarHtml(currentAnalyticsPlatform, videoFilterState);
    barContainer.querySelectorAll('[data-video-limit]').forEach(btn=>{
      btn.addEventListener('click', () => {
        videoFilterState.limit = parseInt(btn.dataset.videoLimit, 10);
        renderVideoSection();
      });
    });
    document.getElementById('videoSortSelect').addEventListener('change', (e) => {
      videoFilterState.sortBy = e.target.value;
      renderVideoSection();
    });

    const filtered = sortAndLimitVideos(currentVideoList, videoFilterState.sortBy, videoFilterState.limit);
    const renderRow = VIDEO_ROW_RENDERERS[currentAnalyticsPlatform];
    listContainer.innerHTML = filtered.length
      ? filtered.map(renderRow).join('')
      : '<div class="empty-state">Nothing to show for this period.</div>';
    listContainer.querySelectorAll('[data-video-id]').forEach(btn=>{
      btn.addEventListener('click', () => openVideoMetrics(btn.dataset.platform, btn.dataset.videoId));
    });
  }

  // ---- Per-video/post metrics modal ----
  const VIDEO_DETAIL_ENDPOINTS = {
    youtube: (id) => `/api/analytics/video/${id}?days=${currentAnalyticsDays}`,
    facebook: (id) => `/api/analytics/facebook/video/${id}`,
    instagram: (id) => `/api/analytics/instagram/video/${id}`,
  };

  function renderRetentionSvg(retention){
    if(!retention || !retention.length){
      return '<div class="empty-state">Not enough views yet for retention data.</div>';
    }
    const w = 480, h = 150, pad = 6;
    const maxY = Math.max(1, ...retention.map(r => r.audience_watch_ratio));
    const points = retention.map(r => {
      const x = pad + r.elapsed_ratio * (w - pad * 2);
      const y = h - pad - (r.audience_watch_ratio / maxY) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return `
      <div class="retention-chart-wrap">
        <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
          <polyline points="${points}" fill="none" stroke="#5b5bf0" stroke-width="2.5"/>
        </svg>
        <div class="retention-axis"><span>Start</span><span>50%</span><span>End</span></div>
      </div>`;
  }

  function renderYoutubeVideoModal(v){
    const p = v.period;
    return `
      <div style="display:flex;gap:14px;align-items:flex-start;margin-bottom:16px;">
        <img src="${v.thumbnail || ''}" style="width:120px;height:90px;border-radius:10px;object-fit:cover;background:#f1f2f6;" onerror="this.style.visibility='hidden'">
        <div>
          <h2 style="margin:0 0 4px;font-size:17px;">${escapeHtml(v.title)}</h2>
          <div class="sub">Published ${new Date(v.published_at).toLocaleDateString()} • <a href="${v.url}" target="_blank" rel="noopener">Open on YouTube</a></div>
        </div>
      </div>
      <div class="sub" style="margin-bottom:6px;">Lifetime</div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);margin-bottom:16px;">
        <div class="stat-card"><div class="stat-label">Views</div><div class="stat-value">${fmtNum(v.lifetime.views)}</div></div>
        <div class="stat-card"><div class="stat-label">Likes</div><div class="stat-value">${fmtNum(v.lifetime.likes)}</div></div>
        <div class="stat-card"><div class="stat-label">Comments</div><div class="stat-value">${fmtNum(v.lifetime.comments)}</div></div>
      </div>
      <div class="sub" style="margin-bottom:6px;">${v.period_days === 1 ? 'Today' : `Last ${v.period_days} days`}</div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Views</div><div class="stat-value">${fmtNum(p.views)}</div></div>
        <div class="stat-card"><div class="stat-label">Watch Time</div><div class="stat-value">${fmtHours(p.watch_time_minutes)}</div></div>
        <div class="stat-card"><div class="stat-label">Avg. Retention</div><div class="stat-value">${p.avg_view_percentage}%</div></div>
      </div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Likes</div><div class="stat-value">${fmtNum(p.likes)}</div></div>
        <div class="stat-card"><div class="stat-label">Comments</div><div class="stat-value">${fmtNum(p.comments)}</div></div>
        <div class="stat-card"><div class="stat-label">Net Subs</div><div class="stat-value ${p.subscribers_net < 0 ? 'warn' : ''}">${p.subscribers_net > 0 ? '+' : ''}${fmtNum(p.subscribers_net)}</div></div>
      </div>
      <div class="card" style="margin-top:16px;box-shadow:none;border:1px solid var(--border);">
        <h2 style="font-size:15px;margin:0 0 4px;">Audience Retention</h2>
        <div class="sub">% of viewers still watching at each point in the video.</div>
        ${renderRetentionSvg(v.retention)}
      </div>
    `;
  }

  function renderFacebookVideoModal(v){
    const m = v.metrics;
    return `
      <div style="display:flex;gap:14px;align-items:flex-start;margin-bottom:16px;">
        <img src="${v.thumbnail || ''}" style="width:120px;height:90px;border-radius:10px;object-fit:cover;background:#f1f2f6;" onerror="this.style.visibility='hidden'">
        <div>
          <h2 style="margin:0 0 4px;font-size:17px;">${escapeHtml(v.title)}</h2>
          <div class="sub">${v.published_at ? new Date(v.published_at).toLocaleDateString() : ''} • <a href="${v.url}" target="_blank" rel="noopener">Open on Facebook</a></div>
        </div>
      </div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Views</div><div class="stat-value">${fmtNum(m.views)}</div></div>
        <div class="stat-card"><div class="stat-label">Unique Views</div><div class="stat-value">${fmtNum(m.unique_views)}</div></div>
        <div class="stat-card"><div class="stat-label">Impressions</div><div class="stat-value">${fmtNum(m.impressions)}</div></div>
      </div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Avg. Watch Time</div><div class="stat-value">${m.avg_watch_time_seconds}s</div></div>
        <div class="stat-card"><div class="stat-label">Likes</div><div class="stat-value">${fmtNum(v.likes)}</div></div>
        <div class="stat-card"><div class="stat-label">Comments</div><div class="stat-value">${fmtNum(v.comments)}</div></div>
      </div>
      <div class="sub" style="margin:12px 0 6px;">Drop-off checkpoints</div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Views at 10s</div><div class="stat-value">${fmtNum(m.views_at_10s)}</div></div>
        <div class="stat-card"><div class="stat-label">Views at 30s</div><div class="stat-value">${fmtNum(m.views_at_30s)}</div></div>
        <div class="stat-card"><div class="stat-label">Watched to End</div><div class="stat-value">${fmtNum(m.complete_views)}</div></div>
      </div>
      <div class="modal-note">${escapeHtml(v.note)}</div>
    `;
  }

  function renderInstagramVideoModal(v){
    const m = v.metrics;
    const isReel = v.media_type === 'REELS';
    const pct = (n) => (n === null || n === undefined) ? '—' : `${n}%`;

    // Reposts (like reach/saved/shares) apply to Feed posts and Stories
    // too, not just Reels, so it always gets a card. Avg. watch time and
    // skip rate are genuinely Reels-only per Instagram's API — shown only
    // for Reels rather than as a misleading 0%/0s on a photo post.
    const reelsOnlyCards = isReel ? `
      <div class="stat-grid" style="grid-template-columns:repeat(2,1fr);">
        <div class="stat-card"><div class="stat-label">Avg. Watch Time</div><div class="stat-value">${m.avg_watch_time_seconds === null ? '—' : m.avg_watch_time_seconds + 's'}</div></div>
        <div class="stat-card"><div class="stat-label">Skip Rate</div><div class="stat-value">${pct(m.skip_rate)}</div></div>
      </div>` : '';

    return `
      <div style="display:flex;gap:14px;align-items:flex-start;margin-bottom:16px;">
        <img src="${v.thumbnail || ''}" style="width:120px;height:90px;border-radius:10px;object-fit:cover;background:#f1f2f6;" onerror="this.style.visibility='hidden'">
        <div>
          <h2 style="margin:0 0 4px;font-size:17px;">${escapeHtml(v.title)}</h2>
          <div class="sub">${v.media_type || ''} • ${v.published_at ? new Date(v.published_at).toLocaleDateString() : ''}${v.url ? ` • <a href="${v.url}" target="_blank" rel="noopener">Open on Instagram</a>` : ''}</div>
        </div>
      </div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Views</div><div class="stat-value">${fmtNum(m.views)}</div></div>
        <div class="stat-card"><div class="stat-label">Reach</div><div class="stat-value">${fmtNum(m.reach)}</div></div>
        <div class="stat-card"><div class="stat-label">Saved</div><div class="stat-value">${fmtNum(m.saved)}</div></div>
      </div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Likes</div><div class="stat-value">${fmtNum(v.likes)}</div></div>
        <div class="stat-card"><div class="stat-label">Comments</div><div class="stat-value">${fmtNum(v.comments)}</div></div>
        <div class="stat-card"><div class="stat-label">Shares</div><div class="stat-value">${fmtNum(m.shares)}</div></div>
      </div>
      <div class="stat-grid" style="grid-template-columns:repeat(1,1fr);">
        <div class="stat-card"><div class="stat-label">Reposts</div><div class="stat-value">${fmtNum(m.reposts)}</div></div>
      </div>
      ${reelsOnlyCards}
      <div class="sub" style="margin:12px 0 6px;">What impacts your reach</div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">
        <div class="stat-card"><div class="stat-label">Like Rate</div><div class="stat-value">${pct(m.like_rate)}</div></div>
        <div class="stat-card"><div class="stat-label">Save Rate</div><div class="stat-value">${pct(m.save_rate)}</div></div>
        <div class="stat-card"><div class="stat-label">Share Rate</div><div class="stat-value">${pct(m.share_rate)}</div></div>
      </div>
      <div class="stat-grid" style="grid-template-columns:repeat(2,1fr);">
        <div class="stat-card"><div class="stat-label">Comment Rate</div><div class="stat-value">${pct(m.comment_rate)}</div></div>
        <div class="stat-card"><div class="stat-label">Repost Rate</div><div class="stat-value">${pct(m.repost_rate)}</div></div>
      </div>
      <div class="modal-note">${escapeHtml(v.note)}</div>
    `;
  }

  const VIDEO_MODAL_RENDERERS = {
    youtube: renderYoutubeVideoModal,
    facebook: renderFacebookVideoModal,
    instagram: renderInstagramVideoModal,
  };

  const REFRESH_INTERVALS = [
    {value: 0, label: 'Auto-refresh: Off'},
    {value: 10000, label: 'Every 10s'},
    {value: 30000, label: 'Every 30s'},
    {value: 60000, label: 'Every 1m'},
    {value: 300000, label: 'Every 5m'},
  ];

  let videoModalState = {
    platform: null, id: null, intervalMs: 0, lastUpdated: null,
    nextRefreshAt: null, refreshTimeoutId: null, countdownTickId: null,
  };

  function refreshBarHtml(){
    const opts = REFRESH_INTERVALS.map(o =>
      `<option value="${o.value}" ${o.value === videoModalState.intervalMs ? 'selected' : ''}>${o.label}</option>`
    ).join('');
    return `
      <div class="modal-refresh-bar">
        <select class="sort-select" id="modalRefreshSelect">${opts}</select>
        <button class="acc-btn refresh-ring-btn" id="modalRefreshNow" type="button">↻ Refresh now</button>
        <span class="modal-refresh-status" id="modalRefreshStatus">
          <span class="mini-spinner" id="modalMiniSpinner" style="display:none;"></span>
          <span id="modalRefreshText"></span>
        </span>
      </div>`;
  }

  // Fills in as a ring around the "Refresh now" button itself, instead of a
  // "Next refresh in Ns" countdown — same information, no text to re-read
  // every second. Ticks often enough (150ms) to look smooth without a
  // dedicated CSS animation, which would need @property to interpolate a
  // conic-gradient() smoothly and isn't reliably supported everywhere yet.
  function updateRefreshRing(){
    const btn = document.getElementById('modalRefreshNow');
    if(!btn) return;
    if(!videoModalState.nextRefreshAt || videoModalState.intervalMs <= 0){
      btn.classList.remove('refresh-ring-active');
      btn.style.removeProperty('--refresh-progress');
      return;
    }
    const total = videoModalState.intervalMs;
    const remaining = videoModalState.nextRefreshAt - Date.now();
    const pct = Math.min(100, Math.max(0, ((total - remaining) / total) * 100));
    btn.classList.add('refresh-ring-active');
    btn.style.setProperty('--refresh-progress', pct.toFixed(1));
  }

  // Self-scheduling: each auto-refresh, once it finishes, schedules the next
  // one — so the visible progress ring and the actual fetch can never drift
  // apart, and a manual "Refresh now" naturally resets the ring too (since
  // it clears+reschedules the pending timeout).
  function scheduleNextAutoRefresh(){
    if(videoModalState.refreshTimeoutId){
      clearTimeout(videoModalState.refreshTimeoutId);
      videoModalState.refreshTimeoutId = null;
    }
    if(videoModalState.intervalMs > 0){
      videoModalState.nextRefreshAt = Date.now() + videoModalState.intervalMs;
      videoModalState.refreshTimeoutId = setTimeout(() => fetchVideoMetrics(), videoModalState.intervalMs);
      if(!videoModalState.countdownTickId){
        videoModalState.countdownTickId = setInterval(updateRefreshRing, 150);
      }
    } else {
      videoModalState.nextRefreshAt = null;
      if(videoModalState.countdownTickId){
        clearInterval(videoModalState.countdownTickId);
        videoModalState.countdownTickId = null;
      }
    }
    updateRefreshRing();
  }

  function wireModalRefreshControls(){
    document.getElementById('modalRefreshSelect').addEventListener('change', (e) => {
      videoModalState.intervalMs = parseInt(e.target.value, 10);
      scheduleNextAutoRefresh();
    });
    document.getElementById('modalRefreshNow').addEventListener('click', () => fetchVideoMetrics());
  }

  async function fetchVideoMetrics(){
    const { platform, id } = videoModalState;
    if(!platform || !id) return;
    const contentEl = document.getElementById('videoModalContent');
    const spinner = document.getElementById('modalMiniSpinner');
    const textEl = document.getElementById('modalRefreshText');
    if(!contentEl) return;  // modal got closed while this was in flight

    const isFirstLoad = !videoModalState.lastUpdated;
    if(!isFirstLoad){
      contentEl.classList.add('modal-content-loading');
      if(spinner) spinner.style.display = 'inline-block';
      if(textEl) textEl.textContent = 'Refreshing…';
    }

    try{
      const res = await fetch(withAccount(`${API}${VIDEO_DETAIL_ENDPOINTS[platform](id)}`), {cache: 'no-store'});
      // If the modal was closed or switched to a different video mid-flight, drop this response.
      if(videoModalState.platform !== platform || videoModalState.id !== id) return;

      if(!res.ok){
        const err = await res.json().catch(()=>({detail: 'Could not load metrics.'}));
        contentEl.innerHTML = `<div class="empty-state">${escapeHtml(err.detail)}</div>`;
        if(textEl) textEl.textContent = '';
        videoModalState.intervalMs = 0;  // hard stop — a broken connection won't fix itself on a timer
        const selectEl = document.getElementById('modalRefreshSelect');
        if(selectEl) selectEl.value = '0';
        return;
      }
      const data = await res.json();
      contentEl.innerHTML = VIDEO_MODAL_RENDERERS[platform](data);
      videoModalState.lastUpdated = new Date();
      if(textEl) textEl.textContent = `Updated ${videoModalState.lastUpdated.toLocaleTimeString()}`;
    }catch(err){
      if(videoModalState.platform !== platform || videoModalState.id !== id) return;
      if(textEl) textEl.textContent = 'Refresh failed — will retry';
    }finally{
      if(spinner) spinner.style.display = 'none';
      if(contentEl) contentEl.classList.remove('modal-content-loading');
      scheduleNextAutoRefresh();  // reschedules if intervalMs > 0, or clears the countdown if it was just set to 0
    }
  }

  async function openVideoMetrics(platform, videoId){
    if(videoModalState.refreshTimeoutId) clearTimeout(videoModalState.refreshTimeoutId);
    if(videoModalState.countdownTickId) clearInterval(videoModalState.countdownTickId);
    videoModalState = {
      platform, id: videoId, intervalMs: 0, lastUpdated: null,
      nextRefreshAt: null, refreshTimeoutId: null, countdownTickId: null,
    };

    const overlay = document.getElementById('videoModalOverlay');
    const body = document.getElementById('videoModalBody');
    overlay.classList.add('show');
    body.innerHTML = refreshBarHtml() + '<div id="videoModalContent"><div class="empty-state">Loading…</div></div>';
    wireModalRefreshControls();
    await fetchVideoMetrics();
  }

  function closeVideoModal(){
    if(videoModalState.refreshTimeoutId) clearTimeout(videoModalState.refreshTimeoutId);
    if(videoModalState.countdownTickId) clearInterval(videoModalState.countdownTickId);
    videoModalState = {
      platform: null, id: null, intervalMs: 0, lastUpdated: null,
      nextRefreshAt: null, refreshTimeoutId: null, countdownTickId: null,
    };
    document.getElementById('videoModalOverlay').classList.remove('show');
  }
  document.getElementById('videoModalClose').addEventListener('click', closeVideoModal);
  document.getElementById('videoModalOverlay').addEventListener('click', (e) => {
    if(e.target.id === 'videoModalOverlay') closeVideoModal();
  });
  document.addEventListener('keydown', (e) => {
    if(e.key === 'Escape') closeVideoModal();
  });

  function videoLimitBarHtml(state){
    const limitPills = VIDEO_LIMIT_OPTIONS.map(n => {
      const label = n === 999 ? 'All' : `Top ${n}`;
      return `<button class="pill-btn ${state.limit === n ? 'active' : ''}" data-video-limit="${n}">${label}</button>`;
    }).join('');
    return `<div class="video-filters"><div class="day-toggle">${limitPills}</div></div>`;
  }

  function renderAnalyticsBody(){
    const body = document.getElementById('analyticsBody');
    if(!lastAnalyticsData) return;
    const platformKey = currentAnalyticsPlatform;
    const cfg = analyticsConfig[platformKey];

    if(currentAnalyticsView === 'table'){
      currentVideoList = lastAnalyticsData.top_videos || [];
      body.innerHTML = renderAnalyticsTable(platformKey, currentVideoList);

      const barContainer = document.getElementById('videoFilterBarContainer');
      barContainer.innerHTML = videoLimitBarHtml(videoFilterState);
      barContainer.querySelectorAll('[data-video-limit]').forEach(btn=>{
        btn.addEventListener('click', () => {
          videoFilterState.limit = parseInt(btn.dataset.videoLimit, 10);
          renderAnalyticsBody();
        });
      });
      body.querySelectorAll('[data-sort-field]').forEach(th=>{
        th.addEventListener('click', () => {
          const field = th.dataset.sortField;
          if(tableSortState.field === field){
            tableSortState.dir = tableSortState.dir === 'asc' ? 'desc' : 'asc';
          } else {
            tableSortState = { field, dir: 'desc' };
          }
          renderAnalyticsBody();
        });
      });
      body.querySelectorAll('tr[data-video-id]').forEach(tr=>{
        tr.addEventListener('click', () => openVideoMetrics(tr.dataset.platform, tr.dataset.videoId));
      });
      return;
    }

    body.innerHTML = cfg.render(lastAnalyticsData, currentAnalyticsDays);
    body.querySelectorAll('[data-days]').forEach(btn=>{
      btn.addEventListener('click', () => loadAnalytics(parseInt(btn.dataset.days, 10)));
    });
    currentVideoList = lastAnalyticsData.top_videos || [];
    renderVideoSection();
  }

  document.getElementById('analyticsViewToggle').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-analytics-view]');
    if(!btn || btn.classList.contains('active')) return;
    document.querySelectorAll('#analyticsViewToggle [data-analytics-view]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentAnalyticsView = btn.dataset.analyticsView;
    renderAnalyticsBody();
  });

  async function loadAnalytics(days){
    currentAnalyticsDays = days || currentAnalyticsDays;
    const cfg = analyticsConfig[currentAnalyticsPlatform];
    const body = document.getElementById('analyticsBody');
    body.innerHTML = '<div class="analytics-progress-track"><div class="analytics-progress-fill"></div></div><div class="empty-state">Loading…</div>';
    try{
      const res = await fetch(withAccount(`${API}${cfg.endpoint}?days=${currentAnalyticsDays}`));
      if(res.status === 401){
        body.innerHTML = analyticsMessageHtml(cfg.connectMsg, true);
        wireGotoButtons(body);
        return;
      }
      if(!res.ok){
        const errData = await res.json().catch(()=>({detail:'Could not load analytics.'}));
        body.innerHTML = analyticsMessageHtml(errData.detail, res.status === 403);
        wireGotoButtons(body);
        return;
      }
      lastAnalyticsData = await res.json();
      videoFilterState = { sortBy: VIDEO_SORT_OPTIONS[currentAnalyticsPlatform][0].value, limit: 5 };
      tableSortState = { field: 'views', dir: 'desc' };
      renderAnalyticsBody();
    }catch(err){
      body.innerHTML = '<div class="card"><div class="empty-state">Could not reach the server.</div></div>';
    }
  }

  document.querySelectorAll('.platform-pick').forEach(card=>{
    card.addEventListener('click', ()=>{
      if(card.classList.contains('selected')) return;
      document.querySelectorAll('.platform-pick').forEach(c=>c.classList.remove('selected'));
      card.classList.add('selected');
      currentAnalyticsPlatform = card.dataset.platform;
      loadAnalytics(currentAnalyticsDays);
    });
  });

  function wireGotoButtons(scope){
    scope.querySelectorAll('[data-goto]').forEach(el=>{
      el.addEventListener('click', () => showPage(el.dataset.goto));
    });
  }

  // ---- Current user (sidebar footer) + logout ----
  async function loadCurrentUser(){
    try{
      const res = await fetch('/api/auth/me');
      if(!res.ok) return;
      const data = await res.json();
      document.getElementById('currentUserName').textContent = data.username;
      document.getElementById('currentUserAvatar').textContent = data.username.charAt(0).toUpperCase();
    }catch(err){
      // sidebar just keeps its placeholder; not worth surfacing an error for
    }
  }
  document.getElementById('logoutBtn').addEventListener('click', async () => {
    try{ await fetch('/api/auth/logout', { method: 'POST' }); }catch(err){}
    window.location.href = '/login';
  });
  loadCurrentUser();

  // ================= Initial route =================
  // Path-based URLs (e.g. /dashboard) are now canonical (see
  // docs/DECISIONS.md) — server.py serves this same index.html at each
  // known page path. Old ?page=xxx bookmarks/links still work once: read
  // the query string as a fallback and normalize the URL to the new path
  // form so it doesn't keep showing the old style.
  function initialPageFromLocation(){
    const pathPage = location.pathname.replace(/^\/+|\/+$/g, '');
    if (pathPage && PAGE_TITLES[pathPage]) return pathPage;
    const legacyPage = new URLSearchParams(location.search).get('page');
    if (legacyPage && PAGE_TITLES[legacyPage]) {
      history.replaceState(null, '', '/' + legacyPage);
      return legacyPage;
    }
    return 'dashboard';
  }
  const initialPage = initialPageFromLocation();
  accountsReady.then(() => showPage(initialPage));
